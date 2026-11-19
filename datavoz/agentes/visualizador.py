"""Agente Visualizador: elige el tipo de gráfica y la agrega al dashboard."""

from __future__ import annotations

import pandas as pd

from ..config import obtener_config
from ..herramientas import generar_grafica_tool
from ..herramientas.generar_grafica import TIPOS
from ..llm import ErrorLLM, invocar_llm
from ..utilidades import normalizar, tabla_markdown
from . import prompts
from .base import EstadoDataVoz, nodo

TIEMPO = ["fecha", "mes", "nombre_mes", "semana", "inicio_semana", "dia", "hora_del_dia", "trimestre"]
PALABRAS_PROPORCION = ("proporcion", "porcentaje", "participacion", "distribucion", "que parte", "cuanto representa",
                       "metodo de pago", "metodos de pago", "forma de pago")


def _numericas(df: pd.DataFrame) -> list[str]:
    return [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c]) and not pd.api.types.is_bool_dtype(df[c])]


def propuesta_heuristica(columnas: list[str], filas: list[list], pregunta: str) -> dict:
    """Reglas de respaldo y punto de partida para el LLM.

    Devuelve la especificación con ``confianza``: "alta" cuando la forma del resultado deja clara la
    gráfica (un número, una serie de tiempo, un ranking simple); "baja" cuando hay varias opciones
    razonables y conviene que decida el LLM.
    """
    df = pd.DataFrame(filas, columns=columnas)
    num = _numericas(df)
    metricas = [c for c in num if c not in ("mes", "anio", "semana", "dia", "num_dia_semana", "trimestre",
                                            "hora_del_dia", "id_venta")]
    texto = [c for c in columnas if c not in num]
    p = normalizar(pregunta)
    if df.empty or not metricas:
        return {"tipo": "tabla", "titulo": "Resultado", "confianza": "alta"}
    if len(df) == 1 and len(metricas) == 1:
        return {"tipo": "indicador", "y": metricas, "titulo": metricas[0].replace("_", " ").capitalize(),
                "confianza": "alta"}
    if len(df) == 1:
        return {"tipo": "barras", "x": None, "y": metricas, "titulo": "Comparación", "confianza": "alta"}
    dims_tiempo = [c for c in columnas if c in TIEMPO]
    dims = [c for c in columnas if c not in metricas and c != "num_dia_semana"]
    if len(dims) >= 2 and ("hora_del_dia" in dims or "dia_semana" in dims) and len(df) >= 12:
        x = "hora_del_dia" if "hora_del_dia" in dims else dims[0]
        y_dim = next((d for d in dims if d != x), None)
        return {"tipo": "mapa_calor", "x": x, "y_dim": y_dim, "valor": metricas[0], "titulo": "Mapa de calor",
                "confianza": "baja"}
    if dims_tiempo and len(df) >= 4:
        x = "mes" if "mes" in dims_tiempo else dims_tiempo[0]
        color = next((c for c in texto if c not in TIEMPO and c != "dia_semana"), None)
        return {"tipo": "lineas", "x": x, "y": metricas[:2], "color": color, "titulo": "Evolución",
                "confianza": "alta" if len(metricas) == 1 and color is None else "baja"}
    x = (texto or columnas)[0]
    if any(k in p for k in PALABRAS_PROPORCION) and 2 <= len(df) <= 6:
        return {"tipo": "pastel", "x": x, "y": metricas[:1], "titulo": "Distribución", "confianza": "alta"}
    largo = df[x].astype(str).str.len().max() if x in df else 0
    tipo = "barras_horizontales" if (largo and largo > 14 and len(df) > 5) else "barras"
    simple = len(texto) <= 1 and len(metricas) == 1 and not dims_tiempo
    return {"tipo": tipo, "x": x, "y": metricas[:2] if len(metricas) > 1 and len(df) <= 6 else metricas[:1],
            "titulo": "Comparación", "confianza": "alta" if simple else "baja"}


def titulo_automatico(spec: dict, pregunta: str) -> str:
    """Título corto a partir de la métrica y el eje («Ventas por mes»), o la pregunta recortada."""
    y = spec.get("y") or spec.get("valor")
    y = y[0] if isinstance(y, list) and y else y
    x = {"nombre_mes": "mes", "hora_del_dia": "hora del día", "dia_semana": "día de la semana",
         "num_dia_semana": "día de la semana"}.get(spec.get("x"), spec.get("x"))
    if y and x and spec.get("tipo") != "indicador":
        return f"{str(y).replace('_', ' ').capitalize()} por {str(x).replace('_', ' ')}"
    if y:
        return str(y).replace("_", " ").capitalize()
    return pregunta if len(pregunta) <= 70 else pregunta[:67].rsplit(" ", 1)[0] + "…"


def validar_spec(spec: dict, columnas: list[str], respaldo: dict) -> dict:
    if not isinstance(spec, dict) or spec.get("tipo") not in TIPOS:
        return respaldo
    y = spec.get("y")
    if isinstance(y, str):
        y = [y]
    spec["y"] = [c for c in (y or []) if c in columnas] or respaldo.get("y")
    if spec.get("x") not in columnas:
        spec["x"] = respaldo.get("x")
    for k in ("color", "y_dim", "valor"):
        if spec.get(k) not in columnas:
            spec[k] = respaldo.get(k)
    return spec


@nodo("Visualizador", "elegir_y_generar_grafica")
def visualizador(estado: EstadoDataVoz) -> dict:
    resultado = estado.get("resultado") or {}
    columnas, filas = resultado.get("columnas") or [], resultado.get("filas") or []
    pregunta = estado.get("pregunta_completa") or estado.get("pregunta") or ""
    heuristica = propuesta_heuristica(columnas, filas, pregunta)
    spec, origen, error_llm = heuristica, "reglas", None
    if resultado.get("grafica_sugerida"):  # las herramientas del Asesor saben qué gráfica comunica su resultado
        spec, origen = validar_spec(dict(resultado["grafica_sugerida"]), columnas, heuristica), "herramienta"
        heuristica = {**heuristica, "confianza": "alta"}
    # El LLM solo se consulta cuando la forma del resultado admite varias gráficas razonables
    if obtener_config().visualizador_con_llm and heuristica.get("confianza") == "baja":
        df = pd.DataFrame(filas, columns=columnas)
        tipos = ", ".join(f"{c} ({'numérica' if c in _numericas(df) else 'texto/fecha'})" for c in columnas)
        usuario = (f"Pregunta: {pregunta}\nColumnas: {tipos}\nNúmero de filas: {len(filas)}\n"
                   f"Primeras filas:\n{tabla_markdown(columnas, filas, 12)}\n\n"
                   f"Sugerencia de las reglas automáticas: {heuristica}")
        try:
            propuesta = invocar_llm("visualizador", prompts.VISUALIZADOR, usuario)
            spec = validar_spec(propuesta, columnas, heuristica)
            origen = "llm"
        except ErrorLLM as e:
            error_llm = str(e)
    if not spec.get("titulo") or spec.get("titulo") in ("Comparación", "Evolución", "Distribución", "Resultado"):
        spec["titulo"] = titulo_automatico(spec, pregunta)
    grafica = generar_grafica_tool.invoke({"columnas": columnas, "filas": filas, "spec": spec})
    return {"grafica": grafica,
            "_detalle": {"herramienta": "generar_grafica", "origen_decision": origen, "tipo": grafica["spec"].get("tipo"),
                         "spec": {k: v for k, v in grafica["spec"].items() if k != "razon"},
                         "razon": spec.get("razon"), "error": grafica.get("error") or error_llm}}
