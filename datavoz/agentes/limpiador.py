"""Agente Limpiador: decide el mapeo de columnas, limpia el archivo y lo carga a DuckDB."""

from __future__ import annotations

import json
from pathlib import Path

from ..basedatos import resumen_ventas, tablas_y_columnas
from ..datos import cargar_archivo_usuario
from ..herramientas.limpiar_datos import (COLUMNAS_CANONICAS, columnas_faltantes, leer_archivo,
                                          mapear_columnas_heuristico, perfilar)
from ..llm import ErrorLLM, invocar_llm
from ..verificacion import verificar_texto
from . import prompts
from .analista_sql import olvidar_cache
from .base import EstadoDataVoz, nodo


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
                            "Perfil de columnas del archivo:\n" + json.dumps(perfil, ensure_ascii=False, indent=1))
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

    # 2) Limpiar y cargar (herramienta limpiar_datos)
    try:
        ruta_db, limpieza = cargar_archivo_usuario(ruta, mapeo=mapeo, sesion_id=(estado.get("datos") or {}).get("sesion_id"))
    except Exception as e:
        return {"intencion": "limpieza_datos", "respuesta": f"No pude limpiar el archivo: {e}",
                "_detalle": {**detalle, "error": str(e)}}
    olvidar_cache(str(ruta_db))
    resumen = limpieza.resumen()

    # 3) Explicación para el dueño (LLM con verificación de cifras; plantilla de respaldo)
    plantilla = resumen_plantilla(resumen, nombre)
    texto = plantilla
    try:
        candidato = invocar_llm("limpiador_resumen", prompts.LIMPIADOR_RESUMEN,
                                f"Archivo: {nombre}\nReporte de limpieza:\n{json.dumps(resumen, ensure_ascii=False)}",
                                json_salida=False)
        reporte_como_resultado = {"columnas": ["texto"], "filas": [[json.dumps(resumen, ensure_ascii=False)]], "n_filas": 1}
        if verificar_texto(candidato, [reporte_como_resultado], [], nombre)["ok"]:
            texto = candidato
    except ErrorLLM as e:
        detalle["error_llm_resumen"] = str(e)

    datos = dict(estado.get("datos") or {})
    datos.update({"ruta_db": str(ruta_db), "origen": nombre, "limpio": True, "resumen": resumen_ventas(ruta_db),
                  "tablas": sorted(tablas_y_columnas(ruta_db)), "reporte_limpieza": resumen})
    return {"intencion": "limpieza_datos", "datos": datos, "respuesta": texto,
            "limpieza": {"resumen": resumen, "problemas": limpieza.problemas[:2000]},
            "_detalle": {**detalle, "herramienta": "limpiar_datos", "resumen": resumen}}
