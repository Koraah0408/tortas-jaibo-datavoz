"""Funciones auxiliares compartidas: JSON del LLM, texto y formato de números."""

from __future__ import annotations

import json
import math
import re
import unicodedata
from datetime import date, datetime
from decimal import Decimal
from typing import Any


def sin_acentos(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn")


def normalizar(texto: str) -> str:
    """Minúsculas, sin acentos y con espacios colapsados."""
    return re.sub(r"\s+", " ", sin_acentos(str(texto)).lower()).strip()


def extraer_json(texto: str) -> dict:
    """Extrae el primer objeto JSON de la respuesta de un LLM.

    Tolera bloques ```json ... ```, texto antes/después y comas finales.
    Lanza ``ValueError`` si no encuentra un objeto válido.
    """
    if isinstance(texto, list):  # algunos modelos devuelven bloques de contenido
        texto = "".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in texto)
    texto = texto.strip()
    bloque = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", texto, flags=re.S)
    candidatos = [bloque.group(1)] if bloque else []
    inicio = texto.find("{")
    if inicio >= 0:
        profundidad, en_cadena, escape = 0, False, False
        for i in range(inicio, len(texto)):
            c = texto[i]
            if en_cadena:
                if escape:
                    escape = False
                elif c == "\\":
                    escape = True
                elif c == '"':
                    en_cadena = False
                continue
            if c == '"':
                en_cadena = True
            elif c == "{":
                profundidad += 1
            elif c == "}":
                profundidad -= 1
                if profundidad == 0:
                    candidatos.append(texto[inicio:i + 1])
                    break
    for cand in candidatos:
        sin_comas = re.sub(r",\s*([}\]])", r"\1", cand)
        # Reparación: algunos modelos escapan comillas simples del SQL (\') u otros caracteres, lo que no es JSON válido
        sin_escapes = re.sub(r'\\(?!["\\/bfnrtu])', "", sin_comas)
        for intento in (cand, sin_comas, sin_escapes):
            try:
                # strict=False acepta saltos de línea literales dentro de los textos (el SQL en varias líneas)
                valor = json.loads(intento, strict=False)
                if isinstance(valor, dict):
                    return valor
            except json.JSONDecodeError:
                continue
    raise ValueError(f"La respuesta del modelo no contiene JSON válido: {texto[:200]!r}")


def a_json_serializable(valor: Any) -> Any:
    """Convierte tipos de pandas/numpy/fechas a tipos nativos para JSON."""
    if valor is None:
        return None
    if isinstance(valor, (str, bool, int)):
        return valor
    if isinstance(valor, float):
        return None if math.isnan(valor) or math.isinf(valor) else valor
    if isinstance(valor, Decimal):
        return float(valor)
    if isinstance(valor, (datetime, date)):
        return valor.isoformat()
    if hasattr(valor, "item"):  # numpy
        try:
            return a_json_serializable(valor.item())
        except Exception:
            pass
    if isinstance(valor, dict):
        return {str(k): a_json_serializable(v) for k, v in valor.items()}
    if isinstance(valor, (list, tuple, set)):
        return [a_json_serializable(v) for v in valor]
    try:
        import pandas as pd
        if pd.isna(valor):
            return None
    except Exception:
        pass
    return str(valor)


def formato_numero(valor: Any, decimales: int = 2) -> str:
    """Formatea números al estilo mexicano: 12,345.67 (enteros sin decimales)."""
    if valor is None:
        return "—"
    try:
        x = float(valor)
    except (TypeError, ValueError):
        return str(valor)
    if math.isnan(x):
        return "—"
    if abs(x - round(x)) < 1e-9:
        return f"{int(round(x)):,}"
    return f"{x:,.{decimales}f}"


def tabla_markdown(columnas: list[str], filas: list[list], max_filas: int = 30) -> str:
    """Representa un resultado como tabla Markdown compacta para los prompts."""
    if not columnas:
        return "(sin columnas)"
    lineas = ["| " + " | ".join(columnas) + " |", "|" + "---|" * len(columnas)]
    for fila in filas[:max_filas]:
        celdas = []
        for v in fila:
            if isinstance(v, float):
                celdas.append(formato_numero(v))
            else:
                celdas.append("NULL" if v is None else str(v))
        lineas.append("| " + " | ".join(celdas) + " |")
    if len(filas) > max_filas:
        lineas.append(f"... ({len(filas) - max_filas} filas más)")
    return "\n".join(lineas)


def recortar(texto: str, n: int = 400) -> str:
    texto = str(texto)
    return texto if len(texto) <= n else texto[: n - 1] + "…"
