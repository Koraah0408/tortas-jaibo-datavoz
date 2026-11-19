"""Agente Orquestador (supervisor): transcribe, clasifica la intención, resuelve el contexto,
valida cada paso de los especialistas, decide reintentos y actualiza la memoria."""

from __future__ import annotations

import re
import uuid
from datetime import datetime

from ..basedatos import resumen_ventas
from ..config import obtener_config
from ..herramientas import detectar_alertas_tool, exportar_reporte_tool, transcribir_voz_tool
from ..llm import ErrorLLM, invocar_llm
from ..seguridad import es_intencion_peligrosa
from ..utilidades import normalizar
from . import prompts
from .base import EstadoDataVoz, contexto_para_prompt, historial_para_prompt, nodo
from .asesor_negocio import ANALISIS
from .revision_sql import revisar_semantica

INTENCIONES = {"consulta_datos", "reporte", "limpieza_datos", "conversacion", "fuera_de_alcance", "peligrosa"}

RESPUESTA_PELIGROSA = ("No puedo hacer eso: DataVoz solo tiene permiso para **leer** tus datos, nunca para "
                       "borrarlos, modificarlos ni agregar registros. Si quieres, puedo ayudarte a analizarlos; "
                       "por ejemplo: «¿Qué productos se vendieron más en diciembre?» o «¿Cuánto vendí por mes?».")

_PATRON_REPORTE = re.compile(r"\b(genera|generar|exporta|exportar|descarga|descargar|crea|crear|hazme|haz|dame|"
                             r"quiero)\b.*\b(reporte|informe|pdf)\b|\b(reporte|informe)\s+(pdf|de la sesion)\b")
# El PDF de la CONVERSACIÓN solo si la nombra; «reporte de ventas del 18» es el reporte de ventas de ese día
_PATRON_CONVERSACION = re.compile(r"\b(conversacion|sesion|chat|platica|preguntas que (te )?hice)\b")
_PATRON_REPORTE_VENTAS = re.compile(r"\b(reporte|informe|resumen|corte|pdf)\b")


@nodo("Orquestador", "transcribir_voz")
def transcribir(estado: EstadoDataVoz) -> dict:
    resultado = transcribir_voz_tool.invoke({"ruta_audio": str(estado["audio"])})
    texto = (resultado.get("texto") or "").strip()
    actualizacion = {"transcripcion": resultado, "_detalle": {"herramienta": "transcribir_voz", **resultado}}
    if texto:
        actualizacion["pregunta"] = texto
    else:
        actualizacion["intencion"] = "error_voz"
        actualizacion["respuesta_directa"] = (f"No pude entender la nota de voz ({resultado.get('error') or 'audio vacío'}). "
                                              "¿Puedes repetirla o escribir tu pregunta?")
    return actualizacion


def _estado_datos(estado: EstadoDataVoz) -> str:
    datos = estado.get("datos") or {}
    resumen = datos.get("resumen") or {}
    if not resumen or "error" in resumen:
        return "No hay datos cargados."
    return (f"Negocio: {datos.get('negocio') or 'pequeño negocio'}. "
            f"Datos cargados ({datos.get('origen', 'ejemplo')}): ventas del {resumen.get('desde')} al "
            f"{resumen.get('hasta')}, {resumen.get('renglones')} renglones, {resumen.get('productos')} productos. "
            f"Tablas: {', '.join(datos.get('tablas') or ['ventas'])}. Limpieza aplicada: "
            f"{'sí' if datos.get('limpio') else 'no'}."
            + (" Análisis especializados disponibles: pronostico_pan, rentabilidad_canales, promociones, compras, reporte_ventas."
               if datos.get("dominio") == "jaibo" else ""))


@nodo("Orquestador", "clasificar_intencion")
def orquestar(estado: EstadoDataVoz) -> dict:
    pregunta = (estado.get("pregunta") or "").strip()
    if estado.get("intencion") == "error_voz":
        return {"_detalle": {"motivo": "la transcripción falló"}}
    if not pregunta:
        return {"intencion": "conversacion", "pregunta_completa": "",
                "respuesta_directa": "¿Qué te gustaría saber de tus ventas?", "_detalle": {"motivo": "mensaje vacío"}}

    # Defensa previa al LLM: peticiones para modificar datos o saltarse reglas
    if es_intencion_peligrosa(pregunta):
        return {"intencion": "peligrosa", "pregunta_completa": pregunta, "respuesta_directa": RESPUESTA_PELIGROSA,
                "_detalle": {"motivo": "patrón de intención peligrosa detectado antes del LLM"}}
    t = normalizar(pregunta)
    es_jaibo = (estado.get("datos") or {}).get("dominio") == "jaibo"
    if es_jaibo and _PATRON_REPORTE_VENTAS.search(t) and not _PATRON_CONVERSACION.search(t):
        return {"intencion": "consulta_datos", "pregunta_completa": pregunta, "analisis": "reporte_ventas",
                "_detalle": {"motivo": "reporte de ventas de un día o periodo detectado por patrón",
                             "analisis": "reporte_ventas"}}
    if _PATRON_REPORTE.search(t) and (not es_jaibo or _PATRON_CONVERSACION.search(t)):
        return {"intencion": "reporte", "pregunta_completa": pregunta,
                "_detalle": {"motivo": "petición de reporte detectada por patrón"}}

    usuario = (f"Datos disponibles: {_estado_datos(estado)}\n\n"
               f"Conversación previa:\n{historial_para_prompt(estado.get('historial') or [])}\n\n"
               f"Contexto actual: {contexto_para_prompt(estado.get('contexto') or {})}\n\n"
               f"Mensaje del usuario: {pregunta}")
    try:
        r = invocar_llm("orquestador", prompts.ORQUESTADOR, usuario)
    except ErrorLLM as e:
        # Sin LLM: se asume una consulta de datos con la pregunta literal
        return {"intencion": "consulta_datos", "pregunta_completa": pregunta, "error": str(e),
                "_detalle": {"error_llm": str(e), "respaldo": "se asume consulta_datos"}}
    intencion = r.get("intencion") if r.get("intencion") in INTENCIONES else "consulta_datos"
    datos = estado.get("datos") or {}
    reencauzada = None
    if intencion == "limpieza_datos" and datos.get("dominio") == "jaibo" and not datos.get("reporte_limpieza"):
        # La copia del POS no viene de un archivo subido: no hay limpieza de la que hablar. Preguntas como
        # «¿cuántos pedidos se corrigieron?» son sobre las órdenes del negocio (canceladas por modificación).
        intencion, reencauzada = "consulta_datos", "limpieza_datos sin archivo en Jaibo → consulta_datos"
    analisis = r.get("analisis") if (r.get("analisis") in ANALISIS and intencion == "consulta_datos"
                                     and (estado.get("datos") or {}).get("dominio") == "jaibo") else None
    pregunta_completa = (r.get("pregunta_completa") or pregunta).strip()
    if intencion == "peligrosa":
        respuesta_directa = r.get("respuesta_directa") or RESPUESTA_PELIGROSA
    else:
        respuesta_directa = r.get("respuesta_directa")
    return {"intencion": intencion, "pregunta_completa": pregunta_completa, "analisis": analisis,
            "es_seguimiento": bool(r.get("es_seguimiento")), "contexto_turno": r.get("contexto") or {},
            "respuesta_directa": respuesta_directa,
            "_detalle": {"intencion": intencion, "reencauzada": reencauzada, "analisis": analisis, "es_seguimiento": bool(r.get("es_seguimiento")),
                         "pregunta_completa": pregunta_completa, "contexto": r.get("contexto")}}


def ruta_inicio(estado: EstadoDataVoz) -> str:
    if estado.get("archivo"):
        return "limpiador"
    if estado.get("audio"):
        return "transcribir"
    return "orquestador"


def ruta_intencion(estado: EstadoDataVoz) -> str:
    intencion = estado.get("intencion")
    if intencion == "consulta_datos":
        return "asesor_negocio" if estado.get("analisis") in ANALISIS else "analista_sql"
    if intencion == "reporte":
        return "exportar"
    return "responder"


@nodo("Orquestador", "supervisar_sql")
def supervisar(estado: EstadoDataVoz) -> dict:
    """Valida el trabajo del Analista SQL y decide: continuar, reintentar o pedir aclaración."""
    cfg = obtener_config()
    intentos = estado.get("intentos_sql") or []
    ultimo = intentos[-1] if intentos else {}
    resultado = estado.get("resultado") or {}
    n = len(intentos)
    if ultimo.get("falta_informacion") and not ultimo.get("sql"):
        return {"decision_supervisor": "aclarar",
                "respuesta_directa": f"No puedo responder eso con los datos disponibles: {ultimo['falta_informacion']}",
                "_detalle": {"decision": "aclarar", "motivo": "el Analista indicó que falta información"}}
    if ultimo.get("error_llm"):
        err = ultimo["error_llm"]
        if "JSON" in err and n <= cfg.max_reintentos_sql:
            # El modelo sí respondió, pero en un formato ilegible: se le pide de nuevo (cuenta como reintento)
            return {"decision_supervisor": "reintentar",
                    "retroalimentacion": ("Tu respuesta anterior no era un objeto JSON válido. Responde solo con el "
                                          "objeto JSON; dentro del SQL usa comillas simples normales, sin barras invertidas."),
                    "_detalle": {"decision": "reintentar", "intento": n, "motivo": "respuesta del modelo con formato inválido"}}
        if "No hay ningún modelo" in err:
            texto = ("No hay un modelo de lenguaje configurado: copia `.env.example` a `.env` y agrega tu "
                     "GOOGLE_API_KEY (o GROQ_API_KEY).")
        elif "JSON" in err:
            texto = ("El modelo respondió varias veces en un formato que no pude leer. Intenta de nuevo o "
                     "reformula la pregunta.")
        elif "todos los respaldos" in err:
            texto = ("Ningún modelo de Gemini está disponible ahora: se agotó la cuota gratuita del día o están "
                     "saturados. Intenta más tarde, o agrega una GROQ_API_KEY en `.env` como respaldo.")
        else:
            texto = "No pude consultar al modelo de lenguaje en este momento (conexión). Intenta de nuevo en un minuto."
        return {"decision_supervisor": "aclarar", "respuesta_directa": texto,
                "_detalle": {"decision": "aclarar", "motivo": err}}
    error = resultado.get("error")
    vacio = not error and (resultado.get("n_filas", 0) == 0 or
                           (resultado.get("n_filas") == 1 and all(v is None for v in resultado["filas"][0])))
    if error or vacio:
        if n <= cfg.max_reintentos_sql:
            if error:
                retro = (f"La consulta anterior falló con este error: {error}. Corrige la consulta "
                         "(revisa nombres de columnas, tablas, tipos y sintaxis de DuckDB).")
            else:
                retro = ("La consulta anterior no devolvió resultados. Revisa los filtros: usa el nombre exacto del "
                         "producto o ILIKE con una palabra clave, el número de mes correcto y que existan datos en ese periodo.")
            return {"decision_supervisor": "reintentar", "retroalimentacion": retro,
                    "_detalle": {"decision": "reintentar", "intento": n, "motivo": error or "resultado vacío"}}
        if error:
            return {"decision_supervisor": "aclarar",
                    "respuesta_directa": "No logré construir una consulta correcta para tu pregunta después de "
                                         f"{n} intentos. ¿Puedes reformularla o dar más detalles (producto, mes, categoría)?",
                    "_detalle": {"decision": "aclarar", "motivo": f"error tras {n} intentos: {error}"}}
        return {"decision_supervisor": "continuar",
                "_detalle": {"decision": "continuar", "motivo": f"resultado vacío tras {n} intentos; se informa al usuario"}}
    # Revisión semántica: consultas que corren bien pero responden mal
    problema = revisar_semantica(resultado.get("sql") or estado.get("sql"), (estado.get("datos") or {}).get("tablas"))
    if problema and n <= cfg.max_reintentos_sql:
        intentos = [dict(i) for i in intentos]
        intentos[-1]["problema"] = f"revisión del Orquestador: {problema}"
        return {"decision_supervisor": "reintentar", "retroalimentacion": problema, "intentos_sql": intentos,
                "_detalle": {"decision": "reintentar", "intento": n, "motivo": "revisión semántica", "problema": problema}}
    return {"decision_supervisor": "continuar",
            "_detalle": {"decision": "continuar", "filas": resultado.get("n_filas"), "intentos": n}}


def ruta_supervisor(estado: EstadoDataVoz) -> str:
    decision = estado.get("decision_supervisor")
    return {"reintentar": "analista_sql", "aclarar": "responder"}.get(decision, "visualizador")


@nodo("Orquestador", "responder_directo")
def responder(estado: EstadoDataVoz) -> dict:
    intencion = estado.get("intencion")
    texto = estado.get("respuesta_directa")
    if not texto:
        if intencion == "limpieza_datos":
            limpieza = (estado.get("datos") or {}).get("reporte_limpieza")
            if limpieza:
                pt = limpieza.get("por_tipo", {})
                partes = [f"{v['detectados']} de tipo «{k.replace('_', ' ')}»" for k, v in pt.items()]
                texto = (f"En la última revisión de tus datos encontré {limpieza.get('problemas_detectados', 0)} problemas"
                         + (f" ({', '.join(partes)})" if partes else "") +
                         f". Quedaron {limpieza.get('filas_limpias')} filas listas para analizar.")
            else:
                texto = ("Los datos de ejemplo ya están limpios y cargados. Si quieres revisar tu propio archivo, "
                         "súbelo en formato CSV o Excel desde el panel lateral.")
        elif intencion == "fuera_de_alcance":
            if (estado.get("datos") or {}).get("dominio") == "jaibo":
                texto = ("Esa información no está en las ventas de Tortas Jaibo. Puedo ayudarte con ventas, pan, "
                         "canales (mostrador, Didi, Rappi) y promociones; por ejemplo: «¿Qué día de la semana vendo más?».")
            else:
                texto = ("Esa información no está en los datos de la tienda. Puedo ayudarte con ventas, productos, "
                         "existencias y promociones; por ejemplo: «¿Qué día de la semana vendo más?».")
        elif (estado.get("datos") or {}).get("dominio") == "jaibo":
            texto = ("¡Hola! Soy el asistente de Tortas Jaibo. Pregúntame por texto o por voz, por ejemplo: "
                     "«¿Cuánto pan compro para mañana?» o «¿Qué promoción me recomiendas?».")
        else:
            texto = ("¡Hola! Soy DataVoz. Pregúntame por texto o por voz sobre tus ventas, por ejemplo: "
                     "«¿Cuáles fueron los productos más vendidos en diciembre?» o «¿Funcionó la promoción de papas?».")
    return {"respuesta": texto, "_detalle": {"intencion": intencion}}


@nodo("Narrador", "exportar_reporte")
def exportar(estado: EstadoDataVoz) -> dict:
    datos = estado.get("datos") or {}
    ruta_db = datos.get("ruta_db") or str(obtener_config().ruta_db)
    try:
        alertas = detectar_alertas_tool.invoke({"ruta_db": ruta_db})
    except Exception:
        alertas = []
    historial = [t for t in (estado.get("historial") or []) if t.get("intencion") == "consulta_datos"]
    ruta = exportar_reporte_tool.invoke({"historial": historial, "resumen_datos": datos.get("resumen"),
                                         "alertas": alertas})
    texto = (f"Listo, generé tu reporte PDF con {len(historial)} análisis de esta sesión"
             + (f" y {len(alertas)} alertas automáticas" if alertas else "") + ". Puedes descargarlo con el botón de abajo.")
    if not historial:
        texto = "Generé el reporte, pero todavía no hay preguntas analizadas en esta sesión; haz algunas preguntas y vuelve a generarlo."
    return {"respuesta": texto, "reporte_pdf": ruta, "_detalle": {"herramienta": "exportar_reporte", "ruta": ruta,
                                                                  "analisis": len(historial), "alertas": len(alertas)}}


@nodo("Orquestador", "actualizar_memoria")
def actualizar_memoria(estado: EstadoDataVoz) -> dict:
    """Guarda el turno en el historial, actualiza el resumen de contexto y el dashboard."""
    historial = list(estado.get("historial") or [])
    contexto = dict(estado.get("contexto") or {})
    dashboard = list(estado.get("dashboard") or [])
    resultado = estado.get("resultado") or {}
    intencion = estado.get("intencion") or ("limpieza_datos" if estado.get("limpieza") else "")
    turno = {
        "id": uuid.uuid4().hex[:8],
        "hora": datetime.now().isoformat(timespec="seconds"),
        "pregunta": estado.get("pregunta") or (f"[archivo] {estado.get('archivo')}" if estado.get("archivo") else ""),
        "pregunta_completa": estado.get("pregunta_completa"),
        "intencion": intencion,
        "respuesta": estado.get("respuesta"),
        "sql": estado.get("sql"),
        "analisis": estado.get("analisis"),
        "resultado": {"columnas": resultado.get("columnas"), "filas": (resultado.get("filas") or [])[:200],
                      "n_filas": resultado.get("n_filas")} if resultado else None,
        "grafica": {"spec": (estado.get("grafica") or {}).get("spec")} if estado.get("grafica") else None,
    }
    historial = (historial + [turno])[-30:]
    if intencion == "consulta_datos":
        for k, v in (estado.get("contexto_turno") or {}).items():
            if v not in (None, "", "null"):
                contexto[k] = v
        contexto["ultima_pregunta"] = estado.get("pregunta_completa")
        contexto["ultimo_sql"] = estado.get("sql")
        grafica = estado.get("grafica") or {}
        if grafica.get("figura_json") or (grafica.get("spec") or {}).get("tipo") == "tabla":
            dashboard.append({"id": turno["id"], "pregunta": turno["pregunta_completa"] or turno["pregunta"],
                              "titulo": (grafica.get("spec") or {}).get("titulo") or turno["pregunta"],
                              "spec": grafica.get("spec"), "figura_json": grafica.get("figura_json"),
                              "resultado": turno["resultado"], "respuesta": turno["respuesta"]})
            dashboard = dashboard[-12:]
    if estado.get("limpieza"):
        contexto = {}
    return {"historial": historial, "contexto": contexto, "dashboard": dashboard,
            "_detalle": {"turnos_en_memoria": len(historial), "contexto": {k: v for k, v in contexto.items()
                                                                          if k != "ultimo_sql"},
                         "tarjetas_dashboard": len(dashboard)}}


NEGOCIOS = {
    "abarrotes": ("datos de ejemplo (tienda sintética 2025)",
                  "tienda de abarrotes familiar en Ciudad Madero (datos sintéticos de ejemplo)"),
    "jaibo": ("Tortas Jaibo · POS (solo lectura)",
              "Tortas Jaibo, tortería que vende tortas (barda, pierna, mixta, barbacoa; Normal y Mega), barbacoa por "
              "kilo, tacos, gorditas, bocoles, desayunos, platillo del día y bebidas, en mostrador (Local), Didi, Rappi "
              "y a crédito para empleados de las empresas Legacy y Automatas"),
}


def datos_iniciales(ruta_db: str | None = None, origen: str | None = None, dominio: str = "abarrotes") -> dict:
    from ..basedatos import tablas_y_columnas
    ruta = str(ruta_db or obtener_config().ruta_db)
    try:
        tablas = sorted(tablas_y_columnas(ruta))
    except Exception:
        tablas = []
    origen_defecto, negocio = NEGOCIOS.get(dominio, NEGOCIOS["abarrotes"])
    return {"ruta_db": ruta, "origen": origen or origen_defecto, "limpio": True, "resumen": resumen_ventas(ruta),
            "tablas": tablas, "reporte_limpieza": None, "dominio": dominio, "negocio": negocio}
