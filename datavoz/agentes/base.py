"""Estado compartido del grafo y utilidades comunes de los agentes."""

from __future__ import annotations

import functools
import time
from datetime import datetime
from typing import Any, Callable, TypedDict

from ..llm import llamadas_a_dict, registrar_llamadas


class EstadoDataVoz(TypedDict, total=False):
    # --- Entrada del turno ---
    pregunta: str
    audio: str | None
    archivo: str | None
    mapeo_columnas: dict | None
    # --- Resultado del turno ---
    transcripcion: dict | None
    intencion: str
    pregunta_completa: str
    es_seguimiento: bool
    contexto_turno: dict
    respuesta_directa: str | None
    analisis: str | None
    herramienta_negocio: dict | None
    contexto_rag: dict
    sql: str | None
    explicacion_sql: str
    intentos_sql: list[dict]
    resultado: dict | None
    consultas_apoyo: list[dict]
    retroalimentacion: str | None
    decision_supervisor: str
    grafica: dict | None
    respuesta: str
    verificacion: dict | None
    limpieza: dict | None
    reporte_pdf: str | None
    pasos: list[dict]
    sql_ejecutadas: list[str]
    error: str | None
    # --- Memoria de la sesión (persiste entre turnos gracias al checkpointer) ---
    historial: list[dict]
    contexto: dict
    datos: dict
    dashboard: list[dict]


CAMPOS_TURNO = {
    "audio": None, "archivo": None, "mapeo_columnas": None, "transcripcion": None, "intencion": "",
    "pregunta_completa": "", "es_seguimiento": False, "contexto_turno": {}, "respuesta_directa": None, "analisis": None, "herramienta_negocio": None,
    "contexto_rag": {}, "sql": None, "explicacion_sql": "", "intentos_sql": [], "resultado": None,
    "consultas_apoyo": [], "retroalimentacion": None, "decision_supervisor": "", "grafica": None,
    "respuesta": "", "verificacion": None, "limpieza": None, "reporte_pdf": None, "pasos": [],
    "sql_ejecutadas": [], "error": None,
}


def nodo(agente: str, accion: str) -> Callable:
    """Decorador de nodos: mide tiempo, registra llamadas al LLM y agrega un paso a la traza.

    La función del nodo puede incluir en su actualización la clave ``_detalle``
    (dict) con información para la traza; el decorador la mueve a ``pasos``.
    """
    def decorador(fn: Callable[[EstadoDataVoz], dict]) -> Callable[[EstadoDataVoz], dict]:
        @functools.wraps(fn)
        def envoltura(estado: EstadoDataVoz) -> dict:
            inicio = time.perf_counter()
            with registrar_llamadas() as llamadas:
                actualizacion = fn(estado) or {}
            detalle = actualizacion.pop("_detalle", {})
            paso = {
                "agente": agente,
                "accion": accion,
                "hora": datetime.now().strftime("%H:%M:%S"),
                "duracion_s": round(time.perf_counter() - inicio, 3),
                "llamadas_llm": llamadas_a_dict(llamadas),
                "detalle": detalle,
            }
            actualizacion["pasos"] = list(estado.get("pasos") or []) + [paso]
            return actualizacion
        return envoltura
    return decorador


def historial_para_prompt(historial: list[dict], n: int = 4) -> str:
    if not historial:
        return "(sin conversación previa)"
    lineas = []
    for t in historial[-n:]:
        lineas.append(f"- Usuario: {t.get('pregunta')}")
        if t.get("pregunta_completa") and t.get("pregunta_completa") != t.get("pregunta"):
            lineas.append(f"  (interpretada como: {t['pregunta_completa']})")
        if t.get("analisis"):
            lineas.append(f"  Análisis usado: {t['analisis']}")
        if t.get("sql"):
            lineas.append(f"  SQL usado: {' '.join(t['sql'].split())[:400]}")
        if t.get("respuesta"):
            lineas.append(f"  Respuesta: {t['respuesta'][:300]}")
    return "\n".join(lineas)


def contexto_para_prompt(contexto: dict) -> str:
    utiles = {k: v for k, v in (contexto or {}).items() if v not in (None, "", [], {}) and k != "ultimo_sql"}
    return ", ".join(f"{k}: {v}" for k, v in utiles.items()) or "(sin contexto previo)"


def valor(estado: dict, clave: str, defecto: Any = None) -> Any:
    v = estado.get(clave)
    return defecto if v is None else v
