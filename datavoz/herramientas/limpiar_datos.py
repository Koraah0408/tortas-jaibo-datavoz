"""Herramienta ``limpiar_datos``: perfila, corrige y carga a DuckDB un archivo de ventas.

Detecta y corrige: valores nulos, filas duplicadas, fechas en varios formatos,
precios con texto, nombres de producto inconsistentes, cantidades negativas y
totales que no cuadran. Cada problema queda registrado con la fila de origen
para que el agente Limpiador lo reporte y para evaluar su exactitud.
"""

from __future__ import annotations

import difflib
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from ..utilidades import normalizar

COLUMNAS_CANONICAS = ["fecha", "hora", "ticket", "producto", "categoria", "cantidad",
                      "precio_unitario", "total", "metodo_pago", "promocion"]
REQUERIDAS = ["fecha", "producto", "cantidad"]

SINONIMOS = {
    "fecha": ["fecha", "fecha de venta", "fecha venta", "dia", "date", "fecha_venta", "f. venta"],
    "hora": ["hora", "hora de venta", "time", "hora venta"],
    "ticket": ["ticket", "no. ticket", "no ticket", "folio", "num ticket", "numero de ticket", "nota", "id ticket"],
    "producto": ["producto", "articulo", "descripcion", "item", "nombre del producto", "product", "mercancia"],
    "categoria": ["categoria", "departamento", "familia", "linea", "tipo de producto", "category"],
    "cantidad": ["cantidad", "cant", "cant.", "unidades", "piezas", "pzas", "qty", "cantidad vendida"],
    "precio_unitario": ["precio_unitario", "precio unitario", "precio", "p. unitario", "precio venta", "pu", "price"],
    "total": ["total", "importe", "subtotal", "monto", "venta", "total venta", "amount"],
    "metodo_pago": ["metodo_pago", "metodo de pago", "forma de pago", "pago", "tipo de pago"],
    "promocion": ["promocion", "promo", "oferta", "descuento aplicado"],
}

MESES = {"ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6, "jul": 7, "ago": 8,
         "sep": 9, "set": 9, "oct": 10, "nov": 11, "dic": 12, "jan": 1, "apr": 4, "aug": 8, "dec": 12}
DIAS_SEMANA = ["lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"]
NOMBRES_MES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
               "septiembre", "octubre", "noviembre", "diciembre"]
PAGOS = {"efectivo": "efectivo", "cash": "efectivo", "tarjeta": "tarjeta", "tarjeta de credito": "tarjeta",
         "tarjeta de debito": "tarjeta", "credito": "tarjeta", "debito": "tarjeta", "tdc": "tarjeta",
         "tdd": "tarjeta", "transferencia": "transferencia", "transf.": "transferencia", "transf": "transferencia",
         "spei": "transferencia", "deposito": "transferencia"}


@dataclass
class ResultadoLimpieza:
    datos: pd.DataFrame
    problemas: list[dict]
    mapeo: dict[str, str]
    columnas_ignoradas: list[str]
    notas: list[str] = field(default_factory=list)
    filas_entrada: int = 0

    def resumen(self) -> dict:
        por_tipo: dict[str, dict[str, int]] = {}
        for p in self.problemas:
            t = por_tipo.setdefault(p["tipo"], {"detectados": 0, "corregidos": 0, "eliminados": 0})
            t["detectados"] += 1
            if p["accion"] == "corregido":
                t["corregidos"] += 1
            elif p["accion"] == "eliminado":
                t["eliminados"] += 1
        return {
            "filas_entrada": self.filas_entrada,
            "filas_limpias": int(len(self.datos)),
            "filas_eliminadas": self.filas_entrada - int(len(self.datos)),
            "problemas_detectados": len(self.problemas),
            "por_tipo": por_tipo,
            "mapeo_columnas": self.mapeo,
            "columnas_ignoradas": self.columnas_ignoradas,
            "notas": self.notas,
        }


# ---------------------------------------------------------------------------
# Lectura y mapeo de columnas
# ---------------------------------------------------------------------------
def leer_archivo(ruta: str | Path) -> pd.DataFrame:
    """Lee CSV o Excel como texto (sin interpretar tipos) para poder auditar cada celda."""
    ruta = Path(ruta)
    if ruta.suffix.lower() in (".xlsx", ".xls", ".xlsm"):
        df = pd.read_excel(ruta, dtype=object)
    else:
        df = None
        for codificacion in ("utf-8-sig", "latin-1"):
            try:
                df = pd.read_csv(ruta, dtype=str, keep_default_na=False, encoding=codificacion, sep=None,
                                 engine="python")
                break
            except UnicodeDecodeError:
                continue
        if df is None:
            raise ValueError("No se pudo leer el archivo CSV (codificación desconocida).")
    df.columns = [str(c).strip() for c in df.columns]
    return df


def perfilar(df: pd.DataFrame, n_muestras: int = 3) -> list[dict]:
    """Perfil de cada columna (para que el LLM proponga el mapeo de columnas)."""
    perfil = []
    for c in df.columns:
        serie = df[c].astype(str).str.strip()
        no_vacios = serie[(serie != "") & (serie.str.lower() != "nan") & (serie.str.lower() != "none")]
        perfil.append({"columna": c, "no_vacios": int(len(no_vacios)),
                       "ejemplos": no_vacios.drop_duplicates().head(n_muestras).tolist()})
    return perfil


def mapear_columnas_heuristico(columnas: list[str]) -> dict[str, str]:
    """Mapea columnas del archivo → columnas canónicas usando sinónimos."""
    mapeo: dict[str, str] = {}
    usadas: set[str] = set()
    for col in columnas:
        clave = normalizar(col).replace("_", " ").strip()
        for canonica, sinonimos in SINONIMOS.items():
            if canonica in usadas:
                continue
            opciones = [normalizar(s).replace("_", " ") for s in sinonimos]
            if clave in opciones:
                mapeo[col] = canonica
                usadas.add(canonica)
                break
    return mapeo


def columnas_faltantes(mapeo: dict[str, str]) -> list[str]:
    presentes = set(mapeo.values())
    faltan = [c for c in REQUERIDAS if c not in presentes]
    if "precio_unitario" not in presentes and "total" not in presentes:
        faltan.append("precio_unitario o total")
    return faltan


# ---------------------------------------------------------------------------
# Parsers de valores
# ---------------------------------------------------------------------------
def _vacio(v) -> bool:
    if v is None:
        return True
    if isinstance(v, float) and np.isnan(v):
        return True
    return str(v).strip().lower() in ("", "nan", "none", "null", "nat", "n/a", "na", "-")


def firma_fecha(v) -> str:
    """Identifica el formato de una fecha (para detectar formatos inconsistentes)."""
    if isinstance(v, (datetime, date, pd.Timestamp)):
        return "fecha_nativa"
    s = str(v).strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}( 00:00:00)?", s):
        return "iso"
    if re.fullmatch(r"\d{1,2}/\d{1,2}/\d{4}", s):
        return "dd/mm/aaaa"
    if re.fullmatch(r"\d{4}/\d{1,2}/\d{1,2}", s):
        return "aaaa/mm/dd"
    if re.fullmatch(r"\d{1,2}-\d{1,2}-\d{4}", s):
        return "dd-mm-aaaa"
    if re.fullmatch(r"\d{1,2}-[A-Za-zñÑ]{3,}\.?-\d{2,4}", s):
        return "dd-mes-aaaa"
    if re.search(r"\d{1,2}\s+de\s+[a-záéíóú]+\s+de\s+\d{4}", s.lower()):
        return "texto"
    if re.fullmatch(r"\d{5}(\.0)?", s):
        return "serial_excel"
    return "desconocido"


def parsear_fecha(v) -> date | None:
    if _vacio(v):
        return None
    if isinstance(v, pd.Timestamp):
        return v.date()
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = str(v).strip().lower()
    try:
        if m := re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})( 00:00:00)?", s):
            return date(int(m[1]), int(m[2]), int(m[3]))
        if m := re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", s):          # formato mexicano dd/mm/aaaa
            return date(int(m[3]), int(m[2]), int(m[1]))
        if m := re.fullmatch(r"(\d{4})/(\d{1,2})/(\d{1,2})", s):
            return date(int(m[1]), int(m[2]), int(m[3]))
        if m := re.fullmatch(r"(\d{1,2})-(\d{1,2})-(\d{4})", s):
            return date(int(m[3]), int(m[2]), int(m[1]))
        if m := re.fullmatch(r"(\d{1,2})-([a-zñ]{3,})\.?-(\d{2,4})", s):
            anio = int(m[3]) + (2000 if len(m[3]) == 2 else 0)
            return date(anio, MESES[m[2][:3]], int(m[1]))
        if m := re.search(r"(\d{1,2})\s+de\s+([a-záéíóú]+)\s+de\s+(\d{4})", s):
            mes = normalizar(m[2])[:3]
            return date(int(m[3]), MESES[mes], int(m[1]))
        if m := re.fullmatch(r"(\d{5})(\.0)?", s):                         # serial de Excel
            return (datetime(1899, 12, 30) + timedelta(days=int(m[1]))).date()
    except (ValueError, KeyError):
        return None
    return None


def firma_numero(v) -> str:
    if isinstance(v, (int, float, np.integer, np.floating)) and not isinstance(v, bool):
        return "numero"
    s = str(v)
    if s != s.strip():
        return "espacios"
    if re.fullmatch(r"-?\d+(\.\d+)?", s):
        return "numero"
    if re.fullmatch(r"\$\d{1,3}(,\d{3})*(\.\d+)?", s) or re.fullmatch(r"\$\d+(\.\d+)?", s):
        return "moneda"
    return "texto"


def parsear_numero(v) -> float | None:
    if _vacio(v):
        return None
    if isinstance(v, (int, float, np.integer, np.floating)) and not isinstance(v, bool):
        return float(v)
    s = str(v).strip().lower()
    s = re.sub(r"(mxn|pesos|peso|aprox\.?|c/u|p/u|\$|\s)", "", s)
    if re.fullmatch(r"-?\d+,\d{1,2}", s):        # coma decimal: 25,50
        s = s.replace(",", ".")
    else:
        s = s.replace(",", "")                     # separador de miles
    try:
        return float(s)
    except ValueError:
        return None


def normalizar_hora(v) -> str | None:
    if _vacio(v):
        return None
    if hasattr(v, "hour") and hasattr(v, "minute"):
        return f"{v.hour:02d}:{v.minute:02d}"
    m = re.match(r"(\d{1,2}):(\d{2})", str(v).strip())
    return f"{int(m[1]):02d}:{m[2]}" if m else None


# ---------------------------------------------------------------------------
# Limpieza principal
# ---------------------------------------------------------------------------
def limpiar_datos(fuente: str | Path | pd.DataFrame, mapeo: dict[str, str] | None = None,
                  catalogo: pd.DataFrame | None = None) -> ResultadoLimpieza:
    """Limpia un archivo/DataFrame de ventas y devuelve los datos listos para DuckDB.

    Args:
        fuente: ruta a CSV/Excel o DataFrame crudo.
        mapeo: {columna_del_archivo: columna_canónica}. Si falta, se usa el heurístico.
        catalogo: DataFrame con columnas producto, categoria, precio_lista (opcional) para
            normalizar nombres de productos, completar categorías y precios.
    """
    crudo = fuente.copy() if isinstance(fuente, pd.DataFrame) else leer_archivo(fuente)
    crudo = crudo.reset_index(drop=True)
    filas_entrada = len(crudo)
    mapeo = dict(mapeo) if mapeo else mapear_columnas_heuristico(list(crudo.columns))
    mapeo = {k: v for k, v in mapeo.items() if k in crudo.columns and v in COLUMNAS_CANONICAS}
    faltan = columnas_faltantes(mapeo)
    if faltan:
        raise ValueError(f"Faltan columnas obligatorias: {', '.join(faltan)}")
    ignoradas = [c for c in crudo.columns if c not in mapeo]

    df = crudo[list(mapeo)].rename(columns=mapeo).copy()
    for c in COLUMNAS_CANONICAS:
        if c not in df.columns:
            df[c] = None
    df["fila_origen"] = np.arange(len(df))
    problemas: list[dict] = []
    notas: list[str] = []

    def registrar(fila, tipo, columna, original, corregido, accion):
        problemas.append({"fila": int(fila), "tipo": tipo, "columna": columna,
                          "valor_original": None if _vacio(original) else str(original),
                          "valor_corregido": None if corregido is None else str(corregido), "accion": accion})

    # 1) Duplicados exactos (sobre los valores crudos de las columnas mapeadas)
    claves = df[[c for c in COLUMNAS_CANONICAS]].astype(str)
    duplicados = claves.duplicated(keep="first")
    for fila in df.loc[duplicados, "fila_origen"]:
        registrar(fila, "duplicado", "*", None, None, "eliminado")
    df = df.loc[~duplicados].copy()

    # 2) Producto: espacios, mayúsculas y nombres del catálogo
    nombres_catalogo: dict[str, str] = {}
    if catalogo is not None and "producto" in catalogo:
        nombres_catalogo = {normalizar(p): p for p in catalogo["producto"]}
    else:
        conteo = Counter(re.sub(r"\s+", " ", str(p)).strip() for p in df["producto"] if not _vacio(p))
        for nombre, _ in conteo.most_common():
            nombres_catalogo.setdefault(normalizar(nombre), nombre)
    claves_catalogo = list(nombres_catalogo)
    eliminar: set[int] = set()
    productos = []
    for fila, v in zip(df["fila_origen"], df["producto"]):
        if _vacio(v):
            registrar(fila, "nulo", "producto", v, None, "eliminado")
            eliminar.add(fila)
            productos.append(None)
            continue
        original = str(v)
        clave = normalizar(original)
        canonico = nombres_catalogo.get(clave)
        if canonico is None:
            parecidos = difflib.get_close_matches(clave, claves_catalogo, n=1, cutoff=0.88)
            canonico = nombres_catalogo[parecidos[0]] if parecidos else re.sub(r"\s+", " ", original).strip()
            if not parecidos and catalogo is not None:
                registrar(fila, "producto_desconocido", "producto", original, canonico, "marcado")
        if canonico != original:
            registrar(fila, "producto_formato", "producto", original, canonico, "corregido")
        productos.append(canonico)
    df["producto"] = productos

    # 3) Fechas: formato dominante y formatos minoritarios
    firmas = [firma_fecha(v) for v in df["fecha"] if not _vacio(v)]
    dominante = Counter(firmas).most_common(1)[0][0] if firmas else "iso"
    if dominante not in ("iso", "fecha_nativa"):
        notas.append(f"Las fechas venían en formato {dominante}; se convirtieron a AAAA-MM-DD.")
    fechas = []
    filas_fecha_invalida: set[int] = set()
    for fila, v in zip(df["fila_origen"], df["fecha"]):
        if _vacio(v):
            fechas.append(None)
            continue
        f = parsear_fecha(v)
        if f is None:
            filas_fecha_invalida.add(int(fila))
        elif firma_fecha(v) != dominante:
            registrar(fila, "fecha_formato", "fecha", v, f.isoformat(), "corregido")
        fechas.append(f)
    df["fecha"] = fechas
    # Fechas nulas o inválidas: se infieren del mismo ticket si es posible
    fecha_por_ticket = (df.dropna(subset=["fecha"]).loc[lambda d: ~d["ticket"].map(_vacio)]
                        .groupby("ticket")["fecha"].first().to_dict())
    for i in df.index[df["fecha"].isna()]:
        fila, ticket = df.at[i, "fila_origen"], df.at[i, "ticket"]
        tipo = "fecha_invalida" if int(fila) in filas_fecha_invalida else "nulo"
        if not _vacio(ticket) and ticket in fecha_por_ticket:
            df.at[i, "fecha"] = fecha_por_ticket[ticket]
            registrar(fila, tipo, "fecha", None, fecha_por_ticket[ticket].isoformat(), "corregido")
        else:
            registrar(fila, tipo, "fecha", None, None, "eliminado")
            eliminar.add(fila)

    # 4) Cantidad, precio y total
    firmas_precio = [firma_numero(v) for v in df["precio_unitario"] if not _vacio(v)]
    dom_precio = Counter(firmas_precio).most_common(1)[0][0] if firmas_precio else "numero"
    if dom_precio == "moneda":
        notas.append("Los precios venían con signo de pesos; se convirtieron a número.")
    cantidades, precios, totales = [], [], []
    precio_catalogo = {}
    if catalogo is not None and "precio_lista" in catalogo:
        precio_catalogo = dict(zip(catalogo["producto"], catalogo["precio_lista"]))
    for fila, prod, q_raw, p_raw, t_raw in zip(df["fila_origen"], df["producto"], df["cantidad"],
                                               df["precio_unitario"], df["total"]):
        q, p, t = parsear_numero(q_raw), parsear_numero(p_raw), parsear_numero(t_raw)
        # precio con texto
        if not _vacio(p_raw) and firma_numero(p_raw) != dom_precio:
            if p is None:
                registrar(fila, "precio_invalido", "precio_unitario", p_raw, None, "marcado")
            else:
                registrar(fila, "precio_texto", "precio_unitario", p_raw, f"{p:.2f}", "corregido")
        if not _vacio(q_raw) and q is None:
            registrar(fila, "cantidad_invalida", "cantidad", q_raw, None, "marcado")
        # cantidad negativa
        if q is not None and q < 0:
            registrar(fila, "cantidad_negativa", "cantidad", q_raw, f"{abs(q):g}", "corregido")
            q = abs(q)
        # cantidad nula → total / precio
        if q is None:
            if t is not None and p:
                q = round(t / p, 3)
                registrar(fila, "nulo", "cantidad", None, f"{q:g}", "corregido")
            else:
                registrar(fila, "nulo", "cantidad", None, None, "eliminado")
                eliminar.add(fila)
        elif q == 0:
            registrar(fila, "cantidad_cero", "cantidad", q_raw, None, "eliminado")
            eliminar.add(fila)
        # precio nulo → total / cantidad, o precio de catálogo
        if p is None and q:
            if t is not None:
                p = round(t / q, 2)
            elif prod in precio_catalogo:
                p = float(precio_catalogo[prod])
            if p is not None:
                registrar(fila, "nulo", "precio_unitario", None, f"{p:.2f}", "corregido")
            else:
                registrar(fila, "nulo", "precio_unitario", None, None, "eliminado")
                eliminar.add(fila)
        # total nulo o inconsistente
        if q and p is not None:
            esperado = round(q * p, 2)
            if t is None:
                if not _vacio(t_raw):
                    registrar(fila, "total_invalido", "total", t_raw, f"{esperado:.2f}", "corregido")
                elif "total" in mapeo.values():
                    registrar(fila, "nulo", "total", None, f"{esperado:.2f}", "corregido")
                t = esperado
            elif abs(t - esperado) > max(0.05, 0.01 * esperado):
                registrar(fila, "total_inconsistente", "total", t_raw, f"{esperado:.2f}", "corregido")
                t = esperado
        cantidades.append(q)
        precios.append(p)
        totales.append(t)
    df["cantidad"], df["precio_unitario"], df["total"] = cantidades, precios, totales

    # 5) Categoría desde el catálogo, método de pago, promoción y hora
    cat_por_producto = dict(zip(catalogo["producto"], catalogo["categoria"])) if catalogo is not None else {}
    categorias = []
    for fila, prod, cat in zip(df["fila_origen"], df["producto"], df["categoria"]):
        correcta = cat_por_producto.get(prod)
        if _vacio(cat):
            if correcta:
                if "categoria" in mapeo.values():
                    registrar(fila, "nulo", "categoria", None, correcta, "corregido")
                categorias.append(correcta)
            else:
                categorias.append("Sin categoría")
        else:
            cat = re.sub(r"\s+", " ", str(cat)).strip()
            if correcta and normalizar(cat) == normalizar(correcta) and cat != correcta:
                registrar(fila, "categoria_formato", "categoria", cat, correcta, "corregido")
                cat = correcta
            categorias.append(cat)
    df["categoria"] = categorias
    if "categoria" not in mapeo.values() and cat_por_producto:
        notas.append("El archivo no traía categoría; se completó con el catálogo de productos.")

    pagos = []
    for v in df["metodo_pago"]:
        if _vacio(v):
            pagos.append("no registrado")
        else:
            pagos.append(PAGOS.get(normalizar(v), normalizar(v)))
    df["metodo_pago"] = pagos
    df["promocion"] = [None if _vacio(v) else str(v).strip() for v in df["promocion"]]
    df["hora"] = [normalizar_hora(v) for v in df["hora"]]
    df["ticket"] = [None if _vacio(v) else str(v).strip() for v in df["ticket"]]

    df = df[~df["fila_origen"].isin(eliminar)].copy()
    df = df.sort_values(["fecha", "hora", "ticket"], na_position="last", kind="stable").reset_index(drop=True)
    return ResultadoLimpieza(datos=agregar_columnas_calendario(df), problemas=problemas, mapeo=mapeo,
                             columnas_ignoradas=ignoradas, notas=notas, filas_entrada=filas_entrada)


def es_quincena(d: date) -> bool:
    ultimo = (date(d.year + (d.month == 12), d.month % 12 + 1, 1) - timedelta(days=1)).day
    return d.day in (15, 16, 17) or d.day >= ultimo - 1 or d.day <= 2


def agregar_columnas_calendario(df: pd.DataFrame) -> pd.DataFrame:
    """Columnas derivadas de la fecha que facilitan el SQL generado por el LLM."""
    df = df.copy()
    fechas = pd.to_datetime(df["fecha"])
    df.insert(0, "id_venta", np.arange(1, len(df) + 1))
    df["fecha"] = fechas.dt.date
    df["cantidad"] = df["cantidad"].astype(float)
    if (df["cantidad"] % 1 == 0).all():
        df["cantidad"] = df["cantidad"].astype("int64")
    df["precio_unitario"] = df["precio_unitario"].astype(float).round(2)
    df["total"] = df["total"].astype(float).round(2)
    df["en_promocion"] = df["promocion"].notna()
    df["anio"] = fechas.dt.year.astype("int64")
    df["mes"] = fechas.dt.month.astype("int64")
    df["nombre_mes"] = [NOMBRES_MES[m - 1] for m in fechas.dt.month]
    df["dia"] = fechas.dt.day.astype("int64")
    df["dia_semana"] = [DIAS_SEMANA[d] for d in fechas.dt.weekday]
    df["num_dia_semana"] = (fechas.dt.weekday + 1).astype("int64")
    df["semana"] = fechas.dt.isocalendar().week.astype("int64").values
    df["trimestre"] = fechas.dt.quarter.astype("int64")
    df["hora_del_dia"] = pd.array([int(h[:2]) if isinstance(h, str) else None for h in df["hora"]], dtype="Int64")
    df["es_fin_de_semana"] = fechas.dt.weekday >= 5
    df["es_quincena"] = [es_quincena(d) for d in df["fecha"]]
    orden = ["id_venta", "fecha", "hora", "ticket", "producto", "categoria", "cantidad", "precio_unitario",
             "total", "metodo_pago", "promocion", "en_promocion", "anio", "mes", "nombre_mes", "dia",
             "dia_semana", "num_dia_semana", "semana", "trimestre", "hora_del_dia", "es_fin_de_semana",
             "es_quincena", "fila_origen"]
    return df[orden]
