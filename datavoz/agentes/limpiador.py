"""Agente Limpiador: decide el mapeo de columnas, limpia el archivo y lo carga a DuckDB."""

from __future__ import annotations

import json
from pathlib import Path

from ..basedatos import resumen_ventas, tablas_y_columnas
import pandas as pd

from ..datos import escribir_limpieza, limpiar_archivo_usuario
from ..seguridad import neutralizar, parece_instruccion
from ..herramientas.limpiar_datos import (COLUMNAS_CANONICAS, columnas_faltantes, leer_archivo,
                                          mapear_columnas_heuristico, perfilar)
from ..llm import ErrorLLM, invocar_llm
from ..verificacion import verificar_texto
from . import prompts
from .analista_sql import olvidar_cache
from .base import EstadoDataVoz, nodo


_ACCION = {"corregido": "corrijo", "eliminado": "elimino", "marcado": "marco"}
_NOMBRES = {"duplicado": "filas duplicadas", "nulo": "celdas vacías", "fecha_formato": "fechas con otro formato",
            "precio_texto": "precios escritos con texto", "producto_formato": "nombres de producto inconsistentes",
            "cantidad_negativa": "cantidades negativas", "total_inconsistente": "totales que no cuadran"}


def texto_plan(resumen: dict, nombre: str, limpieza) -> str:
    """Lo que el Limpiador PROPONE cambiar, para que el dueño lo apruebe antes de escribir nada."""
    partes = []
    for tipo, v in resumen.get("por_tipo", {}).items():
        cambios = []
        if v["eliminados"]:
            cambios.append(f"elimino {v['eliminados']}")
        if v["corregidos"]:
            cambios.append(f"corrijo {v['corregidos']}")
        resto = v["detectados"] - v["eliminados"] - v["corregidos"]
        if resto:
            cambios.append(f"marco {resto}")
        partes.append(f"- {_NOMBRES.get(tipo, tipo.replace('_', ' '))}: {' y '.join(cambios)}")
    texto = (f"Revisé «{nombre}» ({resumen['filas_entrada']} filas) y **todavía no he cargado nada**. "
             "Esto es lo que voy a cambiar:\n\n" + ("\n".join(partes) or "- nada: el archivo no tiene errores") +
             f"\n\nQuedarían {resumen['filas_limpias']} filas"
             + (f" ({resumen['filas_eliminadas']} se eliminan)." if resumen["filas_eliminadas"] else "."))
    raros = resumen.get("textos_que_parecen_instrucciones") or []
    if raros:
        texto += (f"\n\nOjo: {len(raros)} valor(es) del archivo parecen instrucciones (por ejemplo «{raros[0]}»). "
                  "Los guardo solo como texto; nunca se ejecutan.")
    return texto + "\n\n¿Apruebas estos cambios? Responde «sí, cárgalo» o «no»."


def resumen_plantilla(resumen: dict, nombre: str) -> str:
    pt = resumen.get("por_tipo", {})
    nombres = {"duplicado": "filas duplicadas", "nulo": "celdas vacías", "fecha_formato": "fechas con otro formato",
               "precio_texto": "precios escritos con texto", "producto_formato": "nombres de producto inconsistentes",
               "cantidad_negativa": "cantidades negativas", "total_inconsistente": "totales que no cuadraban"}
    partes = [f"{v['detectados']} {nombres.get(k, k.replace('_', ' '))}" for k, v in pt.items()]
    texto = f"Revisé tu archivo «{nombre}» ({resumen['filas_entrada']} filas). "
    texto += (f"Encontré y atendí {resumen['problemas_detectados']} problemas: {', '.join(partes)}. "
              if partes else "No encontré errores en los datos. ")
    if resumen.get("notas"):
        texto += " ".join(resumen["notas"]) + " "
    texto += (f"Quedaron {resumen['filas_limpias']} filas listas"
              + (f" ({resumen['filas_eliminadas']} se eliminaron por duplicadas o incompletas)" if resumen['filas_eliminadas'] else "")
              + ". Ya puedes preguntarme sobre estas ventas.")
    return texto


def _neutralizar_todo(x):
    if isinstance(x, dict):
        return {k: _neutralizar_todo(v) for k, v in x.items()}
    if isinstance(x, list):
        return [_neutralizar_todo(v) for v in x]
    return neutralizar(x)


@nodo("Limpiador", "limpiar_y_cargar")
def limpiador(estado: EstadoDataVoz) -> dict:
    ruta = Path(estado["archivo"])
    nombre = ruta.name
    detalle: dict = {"archivo": nombre}
    try:
        crudo = leer_archivo(ruta)
    except Exception as e:
        return {"intencion": "limpieza_datos", "respuesta": f"No pude leer el archivo «{nombre}»: {e}",
                "_detalle": {**detalle, "error": str(e)}}

    # 1) Decidir el mapeo de columnas (reglas → LLM si faltan columnas obligatorias)
    mapeo = estado.get("mapeo_columnas") or mapear_columnas_heuristico(list(crudo.columns))
    origen_mapeo = "usuario" if estado.get("mapeo_columnas") else "reglas"
    if columnas_faltantes(mapeo):
        perfil = perfilar(crudo)
        try:
            r = invocar_llm("limpiador", prompts.LIMPIADOR_MAPEO,
                            "Perfil de columnas del archivo:\n" + json.dumps(_neutralizar_todo(perfil), ensure_ascii=False, indent=1))
            propuesto = {k: v for k, v in (r.get("mapeo") or {}).items()
                         if k in crudo.columns and v in COLUMNAS_CANONICAS}
            # se respetan las columnas ya mapeadas por reglas y se completan con las del LLM
            usados = set(mapeo.values())
            for k, v in propuesto.items():
                if k not in mapeo and v not in usados:
                    mapeo[k] = v
                    usados.add(v)
            origen_mapeo = "reglas + LLM"
            detalle["comentario_llm"] = r.get("comentario")
        except ErrorLLM as e:
            detalle["error_llm"] = str(e)
    faltan = columnas_faltantes(mapeo)
    detalle["mapeo"] = mapeo
    detalle["origen_mapeo"] = origen_mapeo
    if faltan:
        return {"intencion": "limpieza_datos",
                "respuesta": (f"No pude identificar en «{nombre}» las columnas: {', '.join(faltan)}. "
                              f"Columnas encontradas: {', '.join(crudo.columns)}. Renómbralas (por ejemplo «fecha», "
                              "«producto», «cantidad», «precio_unitario») y vuelve a subir el archivo."),
                "_detalle": {**detalle, "faltan": faltan}}

    # 2) Limpiar EN MEMORIA (herramienta limpiar_datos): todavía no se escribe nada
    try:
        limpieza = limpiar_archivo_usuario(ruta, mapeo=mapeo)
    except Exception as e:
        return {"intencion": "limpieza_datos", "respuesta": f"No pude limpiar el archivo: {e}",
                "_detalle": {**detalle, "error": str(e)}}
    resumen = limpieza.resumen()
    sospechosos = [v for v in pd.unique(limpieza.datos.select_dtypes("object").values.ravel()) if parece_instruccion(v)]
    resumen["textos_que_parecen_instrucciones"] = [str(v) for v in sospechosos[:10]]

    # 3) Confirmación humana: sin la aprobación del dueño, solo se le muestra lo que va a cambiar
    if not estado.get("carga_aprobada"):
        return {"intencion": "confirmar_carga", "respuesta": texto_plan(resumen, nombre, limpieza),
                "carga_pendiente": {"archivo": str(ruta), "mapeo": mapeo, "nombre": nombre, "resumen": resumen},
                "limpieza": {"resumen": resumen, "problemas": limpieza.problemas[:2000]},
                "_detalle": {**detalle, "herramienta": "limpiar_datos", "resumen": resumen,
                             "escritura": "pendiente: esperando la aprobación del dueño"}}

    # 4) Aprobado: ÚNICA escritura del sistema (base propia de la sesión)
    ruta_db = escribir_limpieza(limpieza, sesion_id=(estado.get("datos") or {}).get("sesion_id"))
    olvidar_cache(str(ruta_db))

    # 5) Explicación para el dueño (LLM con verificación de cifras; plantilla de respaldo)
    plantilla = resumen_plantilla(resumen, nombre)
    texto = plantilla
    try:
        candidato = invocar_llm("limpiador_resumen", prompts.LIMPIADOR_RESUMEN,
                                f"Archivo: {nombre}\nReporte de limpieza:\n"
                                f"{json.dumps(_neutralizar_todo(resumen), ensure_ascii=False)}",
                                json_salida=False)
        reporte_como_resultado = {"columnas": ["texto"], "filas": [[json.dumps(resumen, ensure_ascii=False)]], "n_filas": 1}
        if verificar_texto(candidato, [reporte_como_resultado], [], nombre)["ok"]:
            texto = candidato
    except ErrorLLM as e:
        detalle["error_llm_resumen"] = str(e)

    datos = dict(estado.get("datos") or {})
    # El archivo tiene la estructura estándar de ventas (no la del POS): se analiza con el conocimiento genérico
    datos.update({"archivo_subido": True, "dominio": "abarrotes", "negocio": f"negocio del archivo «{nombre}»",
                  "ruta_db": str(ruta_db), "origen": nombre, "limpio": True, "resumen": resumen_ventas(ruta_db),
                  "tablas": sorted(tablas_y_columnas(ruta_db)), "reporte_limpieza": resumen})
    return {"intencion": "limpieza_datos", "datos": datos, "respuesta": texto, "carga_pendiente": None,
            "limpieza": {"resumen": resumen, "problemas": limpieza.problemas[:2000]},
            "_detalle": {**detalle, "herramienta": "limpiar_datos", "resumen": resumen,
                         "escritura": "aplicada con la aprobación del dueño", "aprobado_por_el_dueno": True}}
