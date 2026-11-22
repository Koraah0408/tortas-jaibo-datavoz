"""Agente Asesor de negocio (Tortas Jaibo): elige la herramienta de decisión y sus parámetros.

El Orquestador lo llama cuando la pregunta es de decisión: cuánto pan comprar, qué canal deja más
o qué promoción conviene. El LLM solo elige la herramienta y propone parámetros (fechas, productos,
precio, comisiones); este nodo los VALIDA con reglas (productos que existen, rangos, fechas
calculadas sin LLM) y los cálculos los hacen herramientas deterministas en Python. El resultado
sigue el camino normal: Visualizador → Narrador (con verificación de cifras) → Memoria.
"""

from __future__ import annotations

import os
import re
from datetime import date, datetime
from zoneinfo import ZoneInfo

from ..config import obtener_config
from ..herramientas import HERRAMIENTAS_NEGOCIO
from ..herramientas.limpiar_datos import DIAS_SEMANA
from ..herramientas.negocio_jaibo import ErrorAnalisis, _consulta, fechas_de_pregunta, productos_de, resolver_producto
from ..herramientas.reporte_ventas import periodo_de_pregunta
from ..llm import ErrorLLM, invocar_llm
from ..seguridad import neutralizar
from ..utilidades import normalizar
from . import prompts
from .base import EstadoDataVoz, nodo

# análisis que decide el Orquestador → herramientas que puede usar el Asesor
ANALISIS = {"pronostico_pan": ("pronosticar_pan",), "rentabilidad_canales": ("rentabilidad_canales",),
            "promociones": ("combinaciones_frecuentes", "simular_promocion"), "compras": ("lista_de_compras",),
            "reporte_ventas": ("reporte_de_ventas",)}
ZONA = ZoneInfo("America/Monterrey")


def hoy_local() -> date:
    """Fecha de hoy en Monterrey; DATAVOZ_HOY (AAAA-MM-DD) la fija para evaluaciones reproducibles."""
    fija = os.getenv("DATAVOZ_HOY")
    return date.fromisoformat(fija) if fija else datetime.now(ZONA).date()


def _numero(v) -> float | None:
    try:
        return float(str(v).replace("$", "").replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _fraccion(v, maximo: float) -> float | None:
    x = _numero(v)
    if x is None:
        return None
    x = x / 100 if x > 1 else x
    return x if 0 <= x <= maximo else None


def _dias(v) -> int | None:
    x = _numero(v)
    return int(x) if x is not None and 7 <= x <= 1000 else None


def _precio_de_pregunta(pregunta: str) -> float | None:
    m = re.search(r"\$\s*(\d+(?:\.\d+)?)", pregunta) or re.search(r"\b(\d+(?:\.\d+)?)\s*(?:pesos|varos)\b",
                                                                   normalizar(pregunta))
    return float(m.group(1)) if m else None


_MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
          "noviembre", "diciembre"]


def mes_de_pregunta(pregunta: str) -> tuple[int | None, int | None]:
    """Mes (y año, si lo dice) que nombra la pregunta: «en octubre de 2026» → (10, 2026)."""
    t = normalizar(pregunta)
    m = re.search(r"\b(" + "|".join(_MESES) + r")\b(?:\s+(?:de|del)?\s*(\d{4}))?", t)
    if not m:
        return None, None
    return _MESES.index(m.group(1)) + 1, int(m.group(2)) if m.group(2) else None


def _combo_de_pregunta(pregunta: str, productos: list[str]) -> dict[str, int]:
    """Productos que la pregunta nombra completos, con la cantidad que los antecede («2 Mega barda»)."""
    t = f" {normalizar(pregunta)} "
    combo = {}
    for p in sorted(productos, key=len, reverse=True):
        n = normalizar(p)
        m = re.search(rf"(?:\b(\d+)\s*(?:x\s*)?)?\b{re.escape(n)}\b", t)
        if m and not any(n in normalizar(otro) for otro in combo):
            combo[p] = int(m.group(1)) if m.group(1) else 1
            t = t.replace(n, " ")
    return combo


def elegir(analisis: str, pregunta: str, propuesta: dict, productos: list[str], hoy: date,
           ultimo: date | None = None, original: str | None = None) -> tuple[str, dict]:
    """Valida la herramienta y los parámetros que propuso el LLM y completa lo que falte con reglas.

    ``original``: lo que escribió el dueño. Las fechas relativas («mañana», «el fin de semana», «ayer») se calculan con
    ella y no con la pregunta reescrita por el Orquestador, que a veces las convierte mal en fechas concretas."""
    original = original or pregunta
    if analisis == "reporte_ventas":  # el periodo se saca de la pregunta con reglas («del 18», «de ayer»…)
        desde, hasta = periodo_de_pregunta(original, ultimo or hoy, hoy)
        if (desde, hasta) == ((ultimo or hoy),) * 2 and original != pregunta:  # el seguimiento no dijo periodo
            desde, hasta = periodo_de_pregunta(pregunta, ultimo or hoy, hoy)
        return "reporte_de_ventas", {"desde": desde.isoformat(), "hasta": hasta.isoformat()}
    p = propuesta.get("parametros") if isinstance(propuesta.get("parametros"), dict) else {}
    herramienta = propuesta.get("herramienta") if propuesta.get("herramienta") in ANALISIS[analisis] else None
    # Comisiones y márgenes son datos del DUEÑO: solo se aceptan si su pregunta menciona un porcentaje
    # (el modelo tiende a "rellenarlos" con los supuestos de las reglas del negocio)
    dijo_porcentaje = bool(re.search(r"\d+(?:\.\d+)?\s*(?:%|por ciento|porciento)", normalizar(pregunta)))
    if not dijo_porcentaje:
        p = {k: v for k, v in p.items() if k not in ("comisiones", "margen", "margen_bruto")}
    if analisis in ("pronostico_pan", "compras"):
        # Las fechas se calculan con reglas: los modelos pequeños suelen equivocarse con el día de la semana
        fechas = fechas_de_pregunta(original, hoy) or fechas_de_pregunta(pregunta, hoy)
        if not fechas:
            for f in (p.get("fechas") or [])[:14] if isinstance(p.get("fechas"), list) else []:
                try:
                    d = date.fromisoformat(str(f))
                except ValueError:
                    continue
                if 0 <= (d - hoy).days <= 31:
                    fechas.append(d)
        if analisis == "compras":
            return "lista_de_compras", {"fechas": [f.isoformat() for f in fechas] or None,
                                        "margen": _fraccion(p.get("margen"), 0.5), "hoy": hoy.isoformat()}
        semanas = _numero(p.get("semanas"))
        return "pronosticar_pan", {"fechas": [f.isoformat() for f in fechas] or None,
                                   "semanas": int(semanas) if semanas and 4 <= semanas <= 12 else 8,
                                   "margen": _fraccion(p.get("margen"), 0.5), "hoy": hoy.isoformat()}
    if analisis == "rentabilidad_canales":
        comisiones = {}
        if isinstance(p.get("comisiones"), dict):
            for canal, v in p["comisiones"].items():
                x = _fraccion(v, 0.6)
                if x is not None and canal:
                    comisiones[str(canal)] = x
        mes, anio = mes_de_pregunta(pregunta)  # «en octubre de 2026»: ese mes y no los últimos 90 días
        return "rentabilidad_canales", {"dias": None if mes else (_dias(p.get("dias")) or 90), "mes": mes, "anio": anio,
                                        "comisiones": comisiones or None}
    # promociones: simular un combo concreto o buscar combinaciones
    combo: dict[str, int] = {}
    for item in p.get("productos") or [] if isinstance(p.get("productos"), list) else []:
        if isinstance(item, dict):
            nombre = resolver_producto(str(item.get("producto") or ""), productos)
            cantidad = _numero(item.get("cantidad")) or 1
            if nombre:
                combo[nombre] = combo.get(nombre, 0) + max(1, min(int(cantidad), 10))
    combo = combo or _combo_de_pregunta(pregunta, productos)
    precio = _numero(p.get("precio_promocional")) or _precio_de_pregunta(pregunta)
    if herramienta != "combinaciones_frecuentes" and combo and precio and precio > 0:
        return "simular_promocion", {"productos": combo, "precio_promocional": precio,
                                     "dias": _dias(p.get("dias")) or 90,
                                     "margen_bruto": _fraccion(p.get("margen_bruto"), 0.9)}
    return "combinaciones_frecuentes", {"dias": _dias(p.get("dias")) or 180}


@nodo("Asesor de negocio", "analisis_especializado")
def asesor_negocio(estado: EstadoDataVoz) -> dict:
    datos = estado.get("datos") or {}
    ruta_db = datos.get("ruta_db") or str(obtener_config().ruta_db)
    pregunta = estado.get("pregunta_completa") or estado.get("pregunta") or ""
    analisis = estado.get("analisis") if estado.get("analisis") in ANALISIS else "pronostico_pan"
    hoy = hoy_local()
    try:
        productos = productos_de(ruta_db)
    except ErrorAnalisis as e:
        return {"decision_supervisor": "aclarar", "respuesta_directa": f"No pude leer los datos del negocio: {e}",
                "_detalle": {"error": str(e)}}
    resumen = datos.get("resumen") or {}
    usuario = (f"Hoy es {hoy.isoformat()} ({DIAS_SEMANA[hoy.weekday()]}). Datos del {resumen.get('desde')} al "
               f"{resumen.get('hasta')}.\nAnálisis que eligió el Orquestador: {analisis}\n"
               f"Productos del menú (nombres exactos): <datos>{', '.join(str(neutralizar(p)) for p in productos)}</datos>\n\nPregunta del dueño: {pregunta}")
    error_llm = None
    try:
        propuesta = {} if analisis == "reporte_ventas" else invocar_llm("asesor", prompts.ASESOR, usuario)
    except ErrorLLM as e:  # sin LLM se eligen herramienta y parámetros solo con reglas
        propuesta, error_llm = {}, str(e)
    propuesta = propuesta if isinstance(propuesta, dict) else {}
    ultimo = None
    if analisis == "reporte_ventas":
        try:
            ultimo = _consulta("SELECT MAX(fecha) AS f FROM ordenes", ruta_db, []).iloc[0]["f"]
            ultimo = date.fromisoformat(str(ultimo)[:10])
        except Exception:
            ultimo = None
    herramienta, parametros = elegir(analisis, pregunta, propuesta, productos, hoy, ultimo,
                                     original=estado.get("pregunta") or pregunta)
    try:
        res = HERRAMIENTAS_NEGOCIO[herramienta].invoke(
            {"ruta_db": ruta_db, **{k: v for k, v in parametros.items() if v is not None}})
    except ErrorAnalisis as e:
        return {"decision_supervisor": "aclarar", "respuesta_directa": f"No pude hacer ese análisis: {e}",
                "_detalle": {"herramienta": herramienta, "parametros": parametros, "error": str(e),
                             "propuesta_llm": propuesta, "error_llm": error_llm}}
    apoyo = [{"proposito": a["proposito"], "columnas": a["columnas"], "filas": a["filas"], "n_filas": a["n_filas"],
              "error": None, "ejecutada": True} for a in res["apoyo"]]
    return {
        "resultado": {"columnas": res["columnas"], "filas": res["filas"], "n_filas": res["n_filas"], "error": None,
                      "ejecutada": True, "herramienta": herramienta, "titulo": res["titulo"],
                      "grafica_sugerida": res.get("grafica")},
        "consultas_apoyo": apoyo,
        "explicacion_sql": res["explicacion"],
        "sql": None,
        "reporte_pdf": res.get("pdf"),
        "decision_supervisor": "continuar",
        "herramienta_negocio": {"nombre": herramienta, "titulo": res["titulo"], "parametros": res["parametros"],
                                "supuestos": res["supuestos"]},
        "sql_ejecutadas": list(estado.get("sql_ejecutadas") or []) + res["sql_ejecutadas"],
        "_detalle": {"herramienta": herramienta, "propuesta_llm": propuesta, "parametros": res["parametros"],
                     "filas": res["n_filas"], "supuestos": res["supuestos"], "error_llm": error_llm},
    }


def ruta_asesor(estado: EstadoDataVoz) -> str:
    if estado.get("decision_supervisor") == "aclarar":
        return "responder"
    from .orquestador import necesita_grafica
    return "visualizador" if necesita_grafica(estado.get("resultado")) else "narrador"
