"""Métricas de evaluación de DataVoz (comparación de resultados, limpieza, voz y gráficas)."""

from __future__ import annotations

import json
import re
from pathlib import Path

from datavoz.utilidades import normalizar


# ---------------------------------------------------------------------------
# Exactitud del SQL: se compara el RESULTADO (no el texto del SQL)
# ---------------------------------------------------------------------------
def _num(v) -> float | None:
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    return None


def _cerca(a: float, b: float) -> bool:
    return abs(a - b) <= max(0.051, 0.001 * abs(b))


def _columnas_numericas(res: dict) -> list[int]:
    filas = res.get("filas") or []
    return [i for i in range(len(res.get("columnas") or []))
            if any(_num(f[i]) is not None for f in filas) and all(_num(f[i]) is not None or f[i] is None for f in filas)]


def _contiene(valores_ref: list[float], valores_gen: list[float]) -> bool:
    """Cada valor de la referencia debe emparejarse con un valor distinto del agente."""
    disponibles = list(valores_gen)
    for r in valores_ref:
        idx = next((i for i, g in enumerate(disponibles) if _cerca(g, r)), None)
        if idx is None:
            return False
        disponibles.pop(idx)
    return True


def comparar_resultados(gen: dict | None, ref: dict, comparar: list[str] | None = None, clave: str | None = None,
                        ordenado: bool = False) -> tuple[bool, str]:
    """¿El resultado del agente contiene la respuesta de la consulta de referencia?

    * Se comparan las columnas numéricas indicadas (o todas las de la referencia) por valor, con
      tolerancia de redondeo, sin importar el nombre de la columna ni el formato (largo o ancho).
    * ``clave``: columna de texto de la referencia (p. ej. producto) que debe aparecer igual.
    * ``ordenado``: en rankings, los primeros valores deben coincidir en el mismo orden.
    * El resultado del agente no puede tener muchas más filas que la referencia (evita "SELECT *").
    """
    if not gen or gen.get("error"):
        return False, f"error del agente: {gen.get('error') if gen else 'sin resultado'}"
    if ref.get("error"):
        return False, f"error en la referencia: {ref['error']}"
    gfilas, rfilas = gen.get("filas") or [], ref.get("filas") or []
    if len(gfilas) > len(rfilas) + 15:
        return False, f"el agente devolvió demasiadas filas ({len(gfilas)} vs {len(rfilas)})"
    rcols = ref.get("columnas") or []
    idx_ref = [rcols.index(c) for c in comparar if c in rcols] if comparar else _columnas_numericas(ref)
    idx_gen = _columnas_numericas(gen)
    todos_gen = [_num(v) for f in gfilas for v in f if _num(v) is not None]

    for i in idx_ref:
        valores_ref = [_num(f[i]) for f in rfilas if _num(f[i]) is not None]
        if not valores_ref:
            continue
        ok_col = False
        for j in idx_gen:
            valores_gen = [_num(f[j]) for f in gfilas if _num(f[j]) is not None]
            if ordenado:
                if len(valores_gen) >= len(valores_ref) and all(_cerca(g, r) for g, r in zip(valores_gen, valores_ref)):
                    ok_col = True
            elif _contiene(valores_ref, valores_gen):
                ok_col = True
            if ok_col:
                break
        if not ok_col and not (not ordenado and _contiene(valores_ref, todos_gen)):
            return False, f"no coincide la columna '{rcols[i]}' (esperado {valores_ref[:5]})"

    if clave and clave in rcols:
        k = rcols.index(clave)
        esperados = [normalizar(str(f[k])) for f in rfilas]
        textos_gen = [[normalizar(str(f[j])) for f in gfilas] for j in range(len(gen.get("columnas") or []))
                      if j not in idx_gen]
        ok_clave = False
        for col in textos_gen:
            if ordenado and col[:len(esperados)] == esperados:
                ok_clave = True
            elif not ordenado and set(esperados) <= set(col):
                ok_clave = True
        if not ok_clave:
            return False, f"no coincide la columna clave '{clave}' (esperado {esperados[:5]})"
    return True, "coincide con la referencia"


# ---------------------------------------------------------------------------
# Pertinencia de la gráfica (rúbrica 1–5)
# ---------------------------------------------------------------------------
def puntuar_grafica(tipo: str | None, ideal: list[str], aceptable: list[str], hubo_resultado: bool) -> int:
    """5 = tipo ideal · 4 = aceptable · 3 = tabla cuando se esperaba gráfica · 2 = tipo inadecuado · 1 = sin salida."""
    if hubo_resultado and not tipo and "ninguna" in ideal:
        return 5  # un solo número: el Orquestador decidió bien no llamar al Visualizador
    if not hubo_resultado or not tipo:
        return 1
    if tipo in ideal:
        return 5
    if tipo in aceptable:
        return 4
    if tipo == "tabla":
        return 3
    return 2


# ---------------------------------------------------------------------------
# Limpieza de datos
# ---------------------------------------------------------------------------
def evaluar_limpieza(problemas: list[dict], ruta_errores: str | Path) -> dict:
    """Compara los problemas reportados por el Limpiador con los errores inyectados (respuesta conocida)."""
    inyectados = json.loads(Path(ruta_errores).read_text(encoding="utf-8"))["errores"]
    por_fila: dict[int, list[dict]] = {}
    for p in problemas:
        por_fila.setdefault(p["fila"], []).append(p)
    detectados = corregidos = 0
    por_tipo: dict[str, dict] = {}
    for e in inyectados:
        t = por_tipo.setdefault(e["tipo"], {"inyectados": 0, "detectados": 0, "corregidos": 0})
        t["inyectados"] += 1
        candidatos = [p for p in por_fila.get(e["fila"], [])
                      if p["tipo"] == e["tipo"] and (e["columna"] == "*" or p["columna"] == e["columna"])]
        if not candidatos:
            continue
        detectados += 1
        t["detectados"] += 1
        p = candidatos[0]
        correcto = False
        if e["tipo"] == "duplicado":
            correcto = p["accion"] == "eliminado"
        elif p.get("valor_corregido") is not None:
            a, b = p["valor_corregido"], e["valor_correcto"]
            try:
                correcto = abs(float(a) - float(b)) < 0.011
            except (TypeError, ValueError):
                correcto = str(a).strip() == str(b).strip()
        if correcto:
            corregidos += 1
            t["corregidos"] += 1
    filas_con_error = {e["fila"] for e in inyectados}
    falsos_positivos = [p for p in problemas if p["fila"] not in filas_con_error]
    n = len(inyectados)
    return {"inyectados": n, "detectados": detectados, "corregidos": corregidos,
            "tasa_deteccion": round(100 * detectados / n, 1) if n else 0.0,
            "tasa_correccion": round(100 * corregidos / n, 1) if n else 0.0,
            "falsos_positivos": len(falsos_positivos), "por_tipo": por_tipo}


# ---------------------------------------------------------------------------
# Voz
# ---------------------------------------------------------------------------
_NUMEROS = {"uno": "1", "una": "1", "dos": "2", "tres": "3", "cuatro": "4", "cinco": "5", "seis": "6", "siete": "7",
            "ocho": "8", "nueve": "9", "diez": "10", "once": "11", "doce": "12", "quince": "15", "veinte": "20"}


def _palabras(texto: str) -> list[str]:
    return [_NUMEROS.get(p, p) for p in re.findall(r"[a-z0-9ñ]+", normalizar(texto))]


def similitud_transcripcion(referencia: str, hipotesis: str) -> float:
    """1 − WER (tasa de error por palabra) con normalización de acentos, signos y números."""
    r, h = _palabras(referencia), _palabras(hipotesis)
    if not r:
        return 0.0
    d = list(range(len(h) + 1))
    for i in range(1, len(r) + 1):
        previo, d[0] = d[0], i
        for j in range(1, len(h) + 1):
            actual = d[j]
            d[j] = min(d[j] + 1, d[j - 1] + 1, previo + (r[i - 1] != h[j - 1]))
            previo = actual
    return round(max(0.0, 1 - d[len(h)] / len(r)), 3)
