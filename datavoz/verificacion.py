"""Verificación de cifras: el Narrador solo puede mencionar números respaldados por los datos.

Se extraen todos los números del texto y se comparan contra:
  * los valores del resultado principal y de las consultas de apoyo (incluidos los
    números dentro de textos y fechas, p. ej. "Refresco 3 L" o "2025-12-08"),
  * los "hechos calculados" (totales, máximos, cambios porcentuales, participaciones),
  * los números de la pregunta y el número de filas,
  * y las cifras derivadas de un par de valores (diferencia, cambio % y proporción %).

Se tolera el redondeo (±0.5 en enteros o 0.5 % relativo).
"""

from __future__ import annotations

import re
from itertools import combinations, permutations

from .utilidades import formato_numero

_NUMERO = re.compile(r"(?<![\w.,])(-?\$?\s?\d{1,3}(?:,\d{3})+(?:\.\d+)?|-?\$?\s?\d+(?:\.\d+)?)(\s?%|\s?mil\b)?",
                     re.IGNORECASE)


def _a_float(token: str) -> float | None:
    limpio = token.replace("$", "").replace(",", "").replace(" ", "")
    try:
        return float(limpio)
    except ValueError:
        return None


def extraer_numeros(texto: str, ignorar: list[str] | None = None) -> list[dict]:
    """Números mencionados en un texto. ``ignorar``: frases (p. ej. nombres de productos) a omitir."""
    texto = texto or ""
    for frase in sorted(ignorar or [], key=len, reverse=True):
        if frase and len(frase) > 2:
            texto = re.sub(re.escape(frase), " ", texto, flags=re.IGNORECASE)
    # fechas tipo 2025-12-08 o 08/12/2025 se tratan como texto
    texto = re.sub(r"\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}/\d{1,2}/\d{2,4}\b", " ", texto)
    # horas tipo 19:00
    texto = re.sub(r"\b\d{1,2}:\d{2}\b", " ", texto)
    salida = []
    for m in _NUMERO.finditer(texto):
        valor = _a_float(m.group(1))
        if valor is None:
            continue
        sufijo = (m.group(2) or "").strip().lower()
        if sufijo == "mil":
            valor *= 1000
        salida.append({"texto": m.group(0).strip(), "valor": abs(valor), "porcentaje": sufijo == "%"})
    return salida


def _numeros_en_valor(v) -> list[float]:
    if v is None or isinstance(v, bool):
        return []
    if isinstance(v, (int, float)):
        return [abs(float(v))]
    return [float(x) for x in re.findall(r"\d+(?:\.\d+)?", str(v))]


def _cerca(x: float, v: float) -> bool:
    return abs(x - v) <= max(0.51, 0.005 * abs(v))


def calcular_hechos(resultado: dict, etiqueta: str = "") -> list[dict]:
    """Cifras derivadas útiles para el Narrador (y que el verificador acepta)."""
    columnas, filas = resultado.get("columnas") or [], resultado.get("filas") or []
    hechos: list[dict] = []
    if not filas:
        return hechos
    numericas = [i for i, c in enumerate(columnas)
                 if all(isinstance(f[i], (int, float)) and not isinstance(f[i], bool) or f[i] is None for f in filas)
                 and any(isinstance(f[i], (int, float)) for f in filas)]
    etiquetas_idx = [i for i in range(len(columnas)) if i not in numericas]
    def nombre_fila(f):
        return " / ".join(str(f[i]) for i in etiquetas_idx) if etiquetas_idx else ""
    ignorar_cols = {"mes", "anio", "semana", "dia", "num_dia_semana", "trimestre", "hora_del_dia", "id_venta"}
    for i in numericas:
        col = columnas[i]
        if col in ignorar_cols:
            continue
        valores = [(f[i], nombre_fila(f)) for f in filas if f[i] is not None]
        if len(valores) >= 2:
            total = sum(v for v, _ in valores)
            hechos.append({"descripcion": f"{etiqueta}suma de {col}", "valor": round(total, 2)})
            hechos.append({"descripcion": f"{etiqueta}promedio de {col}", "valor": round(total / len(valores), 2)})
            vmax = max(valores, key=lambda t: t[0])
            vmin = min(valores, key=lambda t: t[0])
            hechos.append({"descripcion": f"{etiqueta}máximo de {col} ({vmax[1]})", "valor": vmax[0]})
            hechos.append({"descripcion": f"{etiqueta}mínimo de {col} ({vmin[1]})", "valor": vmin[0]})
            empatados_min = [n for v, n in valores if v == vmin[0]]
            if len(empatados_min) > 1:
                hechos.append({"descripcion": f"{etiqueta}número de filas empatadas con el mínimo de {col} "
                                              f"({', '.join(empatados_min[:6])})", "valor": len(empatados_min)})
            empatados_max = [n for v, n in valores if v == vmax[0]]
            if len(empatados_max) > 1:
                hechos.append({"descripcion": f"{etiqueta}número de filas empatadas con el máximo de {col} "
                                              f"({', '.join(empatados_max[:6])})", "valor": len(empatados_max)})
            if total and len(valores) <= 12 and all(v >= 0 for v, _ in valores):
                for v, n in valores[:12]:
                    hechos.append({"descripcion": f"{etiqueta}participación de {n} en {col} (%)",
                                   "valor": round(100 * v / total, 1)})
            if len(valores) in (2, 3):
                (a, na), (b, nb) = valores[0], valores[1]
                if a:
                    hechos.append({"descripcion": f"{etiqueta}cambio % de {col} de {na} a {nb}",
                                   "valor": round(100 * (b - a) / a, 1)})
                if b:
                    hechos.append({"descripcion": f"{etiqueta}cambio % de {col} de {nb} a {na}",
                                   "valor": round(100 * (a - b) / b, 1)})
                hechos.append({"descripcion": f"{etiqueta}diferencia de {col} entre {na} y {nb}",
                               "valor": round(abs(a - b), 2)})
    return hechos


def hechos_a_texto(hechos: list[dict]) -> str:
    return "\n".join(f"- {h['descripcion']}: {formato_numero(h['valor'])}" for h in hechos) or "(sin hechos)"


def numeros_permitidos(resultados: list[dict], hechos: list[dict], pregunta: str) -> tuple[list[float], list[float]]:
    """Devuelve (valores para cifras derivadas, valores permitidos)."""
    base: list[float] = []
    pares: list[float] = []
    for r in resultados:
        filas = r.get("filas") or []
        for fila in filas:
            for v in fila:
                base.extend(_numeros_en_valor(v))
                if len(filas) <= 12 and isinstance(v, (int, float)) and not isinstance(v, bool):
                    pares.append(abs(float(v)))
        base.append(float(r.get("n_filas") or 0))
    permitidos = list(base)
    permitidos += [abs(float(h["valor"])) for h in hechos if isinstance(h.get("valor"), (int, float))]
    permitidos += [n["valor"] for n in extraer_numeros(pregunta)]
    permitidos += [0.0, 1.0, 2.0, 100.0]
    return pares, permitidos


def verificar_texto(texto: str, resultados: list[dict], hechos: list[dict], pregunta: str,
                    ignorar: list[str] | None = None) -> dict:
    """Verifica que cada cifra del texto esté respaldada. Devuelve el detalle de la verificación."""
    numeros = extraer_numeros(texto, ignorar)
    pares, permitidos = numeros_permitidos(resultados, hechos, pregunta)
    # cifras derivadas (cambio % y proporción %) solo entre valores numéricos de resultados pequeños
    candidatos = sorted({round(v, 4) for v in pares if v})[:40]
    verificados, no_verificados = [], []
    for n in numeros:
        x = n["valor"]
        ok = any(_cerca(x, v) for v in permitidos)
        if not ok and n["porcentaje"] and len(candidatos) >= 2:
            ok = any(_cerca(x, abs(100 * (a - b) / b)) or _cerca(x, 100 * a / b)
                     for a, b in permutations(candidatos, 2))
        if not ok and not n["porcentaje"] and len(candidatos) >= 2:
            # suma de dos filas del resultado («Didi y Rappi sumaron…»): cifra derivada, no inventada
            ok = any(_cerca(x, a + b) for a, b in combinations(candidatos, 2))
        (verificados if ok else no_verificados).append(n["texto"])
    total = len(numeros)
    return {"total_cifras": total, "verificadas": len(verificados), "no_verificadas": no_verificados,
            "porcentaje": 100.0 if total == 0 else round(100 * len(verificados) / total, 1),
            "ok": not no_verificados}
