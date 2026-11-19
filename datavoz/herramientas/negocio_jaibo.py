"""Herramientas del Asesor de negocio de Tortas Jaibo (cálculos deterministas, sin LLM).

Las preguntas de decisión («¿cuánto pan compro?», «¿me conviene Rappi?», «¿qué combo armo?») no se
responden bien con una sola consulta SQL escrita por un modelo pequeño: necesitan un método fijo,
medir su error y separar lo que se sabe de lo que se supone. Cada herramienta:

  * lee la copia local de solo lectura con el mismo guardia de SQL que usa el Analista,
  * devuelve un resultado con la forma que esperan el Visualizador y el Narrador
    (``columnas``/``filas`` + tablas de ``apoyo`` con las cifras que el Narrador puede citar),
  * declara sus ``supuestos`` (comisiones, márgenes y costos que falta confirmar con el dueño).

Costos y supuestos: ``data/jaibo/costos.yaml`` (no se sube a git) o, si no existe, la plantilla
``conocimiento/jaibo/costos.ejemplo.yaml``.
"""

from __future__ import annotations

import math
import os
import re
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import yaml

from ..basedatos import ejecutar_select
from ..config import RAIZ, obtener_config
from ..rag import _coincide_patron, grupos_del_negocio
from ..utilidades import normalizar
from .limpiar_datos import DIAS_SEMANA, es_quincena

RUTA_COSTOS = RAIZ / "data" / "jaibo" / "costos.yaml"
CANALES_APP = ("Didi", "Rappi")
MARGENES_SUPUESTOS = (0.4, 0.5, 0.6)
_MESES = {m: i for i, m in enumerate(["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
                                      "septiembre", "octubre", "noviembre", "diciembre"], start=1)}
_DIAS = {d: i for i, d in enumerate(DIAS_SEMANA)}


class ErrorAnalisis(ValueError):
    """El análisis no se puede hacer con los datos o parámetros dados (mensaje para el dueño)."""


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------
def _consulta(sql: str, ruta_db: str, registro: list[str] | None = None) -> pd.DataFrame:
    r = ejecutar_select(sql, ruta_db, max_filas=50000)
    if not r.ok:
        raise ErrorAnalisis(f"No pude leer los datos: {r.error}")
    if registro is not None:
        registro.append(" ".join(sql.split()))
    return pd.DataFrame(r.filas, columns=r.columnas)


def _lista_sql(nombres: list[str]) -> str:
    return ", ".join("'" + n.replace("'", "''") + "'" for n in nombres)


def _en(columna: str, nombres: list[str]) -> str:
    return f"{columna} IN ({_lista_sql(nombres)})" if nombres else "FALSE"


def _filtro_dias(dias: int | None, tabla: str = "ordenes", alias: str = "") -> str:
    columna = f"{alias}.fecha" if alias else "fecha"
    return f"{columna} > (SELECT MAX(fecha) FROM {tabla}) - INTERVAL {int(dias)} DAY" if dias else "TRUE"


def _r(x, d: int = 2):
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else round(float(x), d)


def cargar_costos(ruta: Path | None = None) -> dict:
    """Comisiones, margen de pan y costos por producto (con la marca de si son supuestos).

    JAIBO_COSTOS fija otro archivo (la evaluación usa la plantilla para que sea reproducible)."""
    plantilla = obtener_config().dir_conocimiento / "jaibo" / "costos.ejemplo.yaml"
    ruta = ruta or (Path(os.environ["JAIBO_COSTOS"]) if os.getenv("JAIBO_COSTOS") else
                    RUTA_COSTOS if RUTA_COSTOS.exists() else plantilla)
    try:
        if os.getenv("JAIBO_COSTOS_YAML") and not os.getenv("JAIBO_COSTOS"):  # en la nube llegan como secreto
            crudo, ruta = yaml.safe_load(os.environ["JAIBO_COSTOS_YAML"]) or {}, RUTA_COSTOS
        else:
            crudo = yaml.safe_load(Path(ruta).read_text(encoding="utf-8")) or {}
    except OSError:
        crudo = {}

    def par(v, defecto):
        if isinstance(v, dict):
            return float(v.get("porcentaje", defecto)), bool(v.get("supuesto", False))
        return (float(v), False) if v is not None else (defecto, True)

    comisiones = {c: par(v, 0.25) for c, v in (crudo.get("comisiones") or {}).items()}
    for c in CANALES_APP:
        comisiones.setdefault(c, (0.25, True))
    compras = crudo.get("compras") or {}
    panes = {}
    for clave, defecto in (("pan_normal", "Telera"), ("pan_mega", "Telera Doble")):
        c = compras.get(clave) or {}
        panes[clave] = {"buscar": c.get("buscar") or defecto,
                        "precio_por_pieza": float(c["precio_por_pieza"]) if c.get("precio_por_pieza") is not None else None,
                        "supuesto": bool(c.get("supuesto", True))}
    return {"comisiones": comisiones, "margen_pan": par(crudo.get("margen_seguridad_pan"), 0.10),
            "costos_producto": {p: float(c) for p, c in (crudo.get("costos_producto") or {}).items() if c is not None},
            "compras": {"codigo_postal": str(compras.get("codigo_postal") or "24180"), **panes},
            "ingredientes": crudo.get("ingredientes") or {},
            "fuente": "datos del dueño" if Path(ruta) == RUTA_COSTOS else "plantilla con supuestos"}


def productos_de(ruta_db: str) -> list[str]:
    return list(_consulta("SELECT DISTINCT producto FROM ventas ORDER BY producto", ruta_db)["producto"])


def productos_de_grupo(grupo: str, productos: list[str]) -> list[str]:
    for g in grupos_del_negocio("jaibo"):
        if g["grupo"] == grupo:
            return [p for p in productos if any(_coincide_patron(p, pat) for pat in g.get("patrones", []))]
    return []


def resolver_producto(nombre: str, productos: list[str]) -> str | None:
    """Nombre exacto del menú (sin distinguir mayúsculas ni acentos)."""
    n = normalizar(nombre)
    exactos = [p for p in productos if normalizar(p) == n]
    if exactos:
        return exactos[0]
    parecidos = [p for p in productos if n and (n in normalizar(p) or normalizar(p) in n)]
    return parecidos[0] if len(parecidos) == 1 else None


_MESES_CORTOS = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
_DIAS_BONITOS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]


def _dia_corto(d: date) -> str:
    return f"{_DIAS_BONITOS[d.weekday()]} {d.day} {_MESES_CORTOS[d.month - 1]}"


def fechas_de_pregunta(pregunta: str, hoy: date) -> list[date]:
    """Fechas futuras que menciona la pregunta («mañana», «el sábado», «esta semana», «20 de noviembre»)."""
    t = normalizar(pregunta)
    fechas = [date(int(a), int(m), int(d)) for a, m, d in re.findall(r"\b(\d{4})-(\d{2})-(\d{2})\b", pregunta)]
    for d, mes in re.findall(r"\b(\d{1,2}) de (" + "|".join(_MESES) + r")\b", t):
        f = date(hoy.year, _MESES[mes], int(d))
        fechas.append(f if f >= hoy else date(hoy.year + 1, _MESES[mes], int(d)))
    if fechas:
        return sorted(set(fechas))
    if re.search(r"\bpasado manana\b", t):
        return [hoy + timedelta(days=2)]
    if "fin de semana" in t:
        inicio = hoy if (hoy.weekday() >= 5 and re.search(r"\beste fin\b", t)) else hoy + timedelta(days=1)
        return [inicio + timedelta(days=i) for i in range(7) if (inicio + timedelta(days=i)).weekday() >= 5][:2]
    if re.search(r"\b(semana|proximos 7 dias|siguientes 7 dias)\b", t):
        return [hoy + timedelta(days=i) for i in range(1, 8)]
    dias = [i for nombre, i in _DIAS.items() if re.search(rf"\b{nombre}\b", t)]
    if dias:
        salida = []
        for i in dias:
            delta = (i - hoy.weekday()) % 7
            salida.append(hoy + timedelta(days=delta or (0 if re.search(r"\bhoy\b", t) else 7)))
        return sorted(salida)
    if re.search(r"\bmanana\b", t) and not re.search(r"\b(en|por|de|la|esta) manana\b", t):
        return [hoy + timedelta(days=1)]
    if re.search(r"\bhoy\b", t):
        return [hoy]
    return []


def _resultado(titulo, columnas, filas, explicacion, supuestos, apoyo, parametros, registro, grafica=None) -> dict:
    return {"titulo": titulo, "columnas": columnas, "filas": filas, "n_filas": len(filas), "grafica": grafica,
            "explicacion": explicacion, "supuestos": supuestos,
            "apoyo": [{**a, "n_filas": len(a["filas"])} for a in apoyo],
            "parametros": parametros, "sql_ejecutadas": registro}


# ---------------------------------------------------------------------------
# 1) Pronóstico de pan con error medido
# ---------------------------------------------------------------------------
def pronosticar_pan(ruta_db: str, fechas: list | None = None, semanas: int = 8, margen: float | None = None,
                    hoy: date | None = None) -> dict:
    """Panes normales y Mega a comprar para cada fecha, con el error que habría tenido el método."""
    registro: list[str] = []
    hoy = hoy or date.today()
    semanas = max(4, min(int(semanas or 8), 12))
    costos = cargar_costos()
    margen, margen_supuesto = (float(margen), False) if margen is not None else costos["margen_pan"]
    productos = productos_de(ruta_db)
    normal, mega = productos_de_grupo("pan normal", productos), productos_de_grupo("pan mega", productos)
    if not normal and not mega:
        raise ErrorAnalisis("No encontré tortas en el menú para calcular el pan.")
    serie = _consulta(f"""
        WITH d AS (SELECT DISTINCT fecha FROM ordenes)
        SELECT d.fecha,
               COALESCE(SUM(v.cantidad) FILTER (WHERE {_en('v.producto', normal)}), 0) AS normal,
               COALESCE(SUM(v.cantidad) FILTER (WHERE {_en('v.producto', mega)}), 0) AS mega
        FROM d LEFT JOIN ventas v ON v.fecha = d.fecha
        GROUP BY d.fecha ORDER BY d.fecha""", ruta_db, registro)
    if serie.empty:
        raise ErrorAnalisis("No hay ventas en la copia del POS.")
    serie["fecha"] = pd.to_datetime(serie["fecha"]).dt.date
    serie[["normal", "mega"]] = serie[["normal", "mega"]].astype(float)
    serie["dow"] = [f.weekday() for f in serie["fecha"]]
    serie["quincena"] = [es_quincena(f) for f in serie["fecha"]]
    ultimo = serie["fecha"].max()
    corte = ultimo + timedelta(days=1)

    def estimar(hasta: date, objetivo: date):
        mismos = serie[(serie["fecha"] < hasta) & (serie["fecha"] >= hasta - timedelta(days=7 * semanas))
                       & (serie["dow"] == objetivo.weekday())]
        return None if mismos.empty else (mismos["normal"].mean(), mismos["mega"].mean(), len(mismos))

    def factor_quincena(hasta: date) -> float:
        rec = serie[(serie["fecha"] < hasta) & (serie["fecha"] >= hasta - timedelta(weeks=26))]
        if len(rec) < 40:
            return 1.0
        total = rec["normal"] + rec["mega"]
        ratio = total / total.groupby(rec["dow"]).transform("mean").replace(0, float("nan"))
        q, nq = ratio[rec["quincena"]].mean(), ratio[~rec["quincena"]].mean()
        f = q / nq if nq and not math.isnan(q) else 1.0
        return min(max(f, 0.85), 1.25) if abs(f - 1) >= 0.05 else 1.0

    avisos = []
    if (hoy - ultimo).days > 2:
        avisos.append(f"La copia del POS llega al {ultimo.isoformat()}: actualízala para usar las ventas más recientes.")
    objetivos = []
    for f in (fechas or [])[:14]:
        try:
            objetivos.append(f if isinstance(f, date) else date.fromisoformat(str(f)))
        except ValueError:
            continue
    objetivos = sorted(set(objetivos)) or [hoy + timedelta(days=1)]
    fq = factor_quincena(corte)
    filas, cerrados = [], []
    for obj in objetivos:
        est = estimar(min(obj, corte), obj)
        if est is None:
            cerrados.append(obj)
            continue
        k = fq if es_quincena(obj) else 1.0
        fn, fm = est[0] * k, est[1] * k
        filas.append([obj.isoformat(), DIAS_SEMANA[obj.weekday()], _r(fn, 1), _r(fm, 1),
                      math.ceil(fn * (1 + margen) - 1e-9), math.ceil(fm * (1 + margen) - 1e-9), est[2],
                      "sí" if es_quincena(obj) else "no", _dia_corto(obj)])
    for c in cerrados:
        avisos.append(f"El negocio no abrió ningún {DIAS_SEMANA[c.weekday()]} en las últimas {semanas} semanas; "
                      f"no se pronostica el {c.isoformat()}.")
    if not filas:  # se pronostica el siguiente día que sí abre
        for i in range(1, 8):
            obj = max(objetivos) + timedelta(days=i)
            est = estimar(corte, obj)
            if est:
                k = fq if es_quincena(obj) else 1.0
                fn, fm = est[0] * k, est[1] * k
                filas.append([obj.isoformat(), DIAS_SEMANA[obj.weekday()], _r(fn, 1), _r(fm, 1),
                              math.ceil(fn * (1 + margen) - 1e-9), math.ceil(fm * (1 + margen) - 1e-9), est[2],
                              "sí" if es_quincena(obj) else "no", _dia_corto(obj)])
                avisos.append(f"Se pronosticó el siguiente día que suele abrir: {DIAS_SEMANA[obj.weekday()]} {obj.isoformat()}.")
                break

    # Prueba hacia atrás: el mismo método en cada día abierto de las últimas 8 semanas, solo con datos previos
    inicio_bt = ultimo - timedelta(days=7 * 8 - 1)
    fq_bt = factor_quincena(inicio_bt)
    bt = []
    for fila in serie[serie["fecha"] >= inicio_bt].itertuples():
        est = estimar(fila.fecha, fila.fecha)
        if est is None or est[2] < 2:
            continue
        k = fq_bt if fila.quincena else 1.0
        previo = serie[serie["fecha"] == fila.fecha - timedelta(days=7)]
        bt.append({"real_n": fila.normal, "real_m": fila.mega, "f_n": est[0] * k, "f_m": est[1] * k,
                   "base_n": previo["normal"].iloc[0] if len(previo) else None,
                   "base_m": previo["mega"].iloc[0] if len(previo) else None})
    bt = pd.DataFrame(bt)
    apoyo = []
    if len(bt):
        base = bt.dropna(subset=["base_n"])
        apoyo.append({
            "proposito": f"qué tan bien habría funcionado este método en las últimas 8 semanas ({len(bt)} días abiertos)",
            "columnas": ["medida", "pan_normal", "pan_mega"],
            "filas": [["error promedio del pronóstico (piezas por día)", _r((bt.real_n - bt.f_n).abs().mean(), 1),
                       _r((bt.real_m - bt.f_m).abs().mean(), 1)],
                      ["error si se copia el mismo día de la semana pasada (piezas por día)",
                       _r((base.real_n - base.base_n).abs().mean(), 1) if len(base) else None,
                       _r((base.real_m - base.base_m).abs().mean(), 1) if len(base) else None],
                      ["venta promedio por día (piezas)", _r(bt.real_n.mean(), 1), _r(bt.real_m.mean(), 1)]]})
        margenes = sorted({0.0, 0.1, 0.2, 0.3, round(margen, 2)})
        filas_m = []
        for m in margenes:
            cn = (bt.f_n * (1 + m) - 1e-9).apply(math.ceil)
            cm = (bt.f_m * (1 + m) - 1e-9).apply(math.ceil)
            falta = (bt.real_n - cn).clip(lower=0) + (bt.real_m - cm).clip(lower=0)
            sobra = (cn - bt.real_n).clip(lower=0) + (cm - bt.real_m).clip(lower=0)
            filas_m.append([round(m * 100), _r(100 * (falta > 0).mean(), 1), _r(sobra.mean(), 1), _r(falta.mean(), 1)])
        apoyo.append({"proposito": "qué habría pasado con distintos márgenes de seguridad en esas 8 semanas",
                      "columnas": ["margen_de_seguridad_pct", "dias_que_habria_faltado_pan_pct",
                                   "pan_sobrante_promedio_por_dia", "pan_faltante_promedio_por_dia"],
                      "filas": filas_m})
    supuestos = [f"margen de seguridad de {margen:.0%}" + (" (SUPUESTO: falta confirmarlo con el dueño)"
                                                            if margen_supuesto else " (indicado por el dueño)"),
                 "un pan por torta: las «normal» usan pan normal y las «Mega» pan mega"]
    if fq != 1.0:
        supuestos.append(f"en quincena se vende {fq:.2f} veces lo normal (medido en las últimas 26 semanas)")
    explicacion = (f"Pronóstico de pan: promedio de tortas normales y Mega vendidas en los mismos días de la semana "
                   f"de las últimas {semanas} semanas que abrió el negocio, más el margen de seguridad. Para medir qué "
                   "tan confiable es, se repitió el método en cada día abierto de las últimas 8 semanas usando solo "
                   "los datos anteriores a ese día. Supuestos: " + "; ".join(supuestos) + "."
                   + (" Avisos: " + " ".join(avisos) if avisos else ""))
    return _resultado("Pan a comprar", ["fecha", "dia_semana", "pan_normal_esperado", "pan_mega_esperado",
                                         "comprar_pan_normal", "comprar_pan_mega", "dias_comparados", "es_quincena",
                                         "dia_compra"],
                      filas, explicacion, supuestos + avisos, apoyo,
                      {"fechas": [f[0] for f in filas], "semanas": semanas, "margen": margen}, registro,
                      {"tipo": "barras", "x": "dia_compra", "y": ["comprar_pan_normal", "comprar_pan_mega"],
                       "titulo": "Pan a comprar"})


# ---------------------------------------------------------------------------
# 2) Rentabilidad por canal (comisiones y sobreprecio de las apps)
# ---------------------------------------------------------------------------
def rentabilidad_canales(ruta_db: str, dias: int | None = 90, comisiones: dict | None = None,
                         mes: int | None = None, anio: int | None = None) -> dict:
    """Si se da ``mes`` (y opcionalmente ``anio``) se usa ese mes; si no, los últimos ``dias``."""
    registro: list[str] = []
    costos = cargar_costos()
    if mes:
        mes = int(mes)
        if not anio:
            ultimo = _consulta(f"SELECT MAX(anio) AS a FROM ordenes WHERE mes = {mes}", ruta_db, registro)["a"].iloc[0]
            if pd.isna(ultimo):
                raise ErrorAnalisis("No hay ventas en ese mes.")
            anio = int(ultimo)
        periodo = f"anio = {int(anio)} AND mes = {mes}"
    else:
        periodo = None
    com = dict(costos["comisiones"])
    for canal, pct in (comisiones or {}).items():
        nombre = next((c for c in com if c.lower() == str(canal).lower()), str(canal).capitalize())
        pct = float(pct)
        com[nombre] = (pct / 100 if pct > 1 else pct, False)
    filtro = periodo or _filtro_dias(dias)
    filtro_v = periodo or _filtro_dias(dias, 'ventas')
    df = _consulta(f"""
        SELECT canal, COUNT(*) AS ordenes, SUM(monto_total) AS venta, SUM(subtotal) AS subtotal,
               MIN(fecha) AS desde, MAX(fecha) AS hasta
        FROM ordenes WHERE NOT cancelada AND {filtro}
        GROUP BY canal ORDER BY venta DESC""", ruta_db, registro)
    if df.empty:
        raise ErrorAnalisis("No hay órdenes en ese periodo.")
    filas = []
    for r in df.itertuples():
        pct = com.get(r.canal, (0.0, False))[0] if r.canal in com else 0.0
        venta, sub = float(r.venta), float(r.subtotal)
        comision = venta * pct
        neto = venta - comision
        es_app = r.canal in CANALES_APP
        cubre = _r(100 * (1 - sub / venta), 1) if es_app and venta > sub else (0.0 if es_app else None)
        # Comparación justa: los pedidos de app son más grandes, así que se compara contra vender ESOS MISMOS
        # productos al precio de mostrador (suma de renglones), no contra el ticket promedio del mostrador
        vs_mostrador = _r((neto - sub) / r.ordenes) if es_app else None
        filas.append([r.canal, int(r.ordenes), _r(venta), _r(venta / r.ordenes), _r(100 * (venta - sub) / sub, 1) if sub else None,
                      _r(100 * pct, 1), _r(comision), _r(neto), _r(neto / r.ordenes), cubre, vs_mostrador])
    columnas = ["canal", "ordenes", "venta_cobrada", "ticket_promedio", "sobreprecio_vs_mostrador_pct", "comision_pct",
                "comision_estimada", "ingreso_despues_de_comision", "ingreso_por_orden",
                "comision_que_cubre_el_sobreprecio_pct", "gana_o_pierde_por_orden_vs_mostrador"]
    supuestos = []
    for c in CANALES_APP:
        if c in set(df["canal"]):
            pct, sup = com[c]
            supuestos.append(f"comisión de {c} de {pct:.0%}" + (" (SUPUESTO: confírmala en tu contrato con la app)"
                                                                if sup else " (dato del dueño)"))
    if {"Legacy", "Automatas"} & set(df["canal"]):
        supuestos.append("Legacy y Automatas compran a crédito: ese dinero entra cuando paga la empresa")

    # Ganancia bruta solo si hay costos de ingredientes para casi toda la venta
    conocidos = costos["costos_producto"]
    if conocidos:
        lin = _consulta(f"SELECT canal, producto, SUM(cantidad) AS u, SUM(total) AS t FROM ventas "
                        f"WHERE {filtro_v} GROUP BY canal, producto", ruta_db, registro)
        lin["costo"] = [conocidos.get(p) for p in lin["producto"]]
        cubierto = lin.dropna(subset=["costo"])
        cobertura = cubierto.groupby("canal")["t"].sum() / lin.groupby("canal")["t"].sum()
        if len(cobertura) and cobertura.min() >= 0.8:
            costo_canal = (cubierto["u"] * cubierto["costo"]).groupby(cubierto["canal"]).sum() / cobertura
            columnas += ["costo_ingredientes_estimado", "ganancia_bruta_estimada"]
            for f in filas:
                costo = float(costo_canal.get(f[0], 0.0))
                f += [_r(costo), _r(f[columnas.index("ingreso_despues_de_comision")] - costo)]
            supuestos.append("costo de ingredientes con los costos por pieza que dio el dueño")
        else:
            supuestos.append("faltan costos de ingredientes para calcular la ganancia: solo se muestra el ingreso "
                             "después de comisiones")
    else:
        supuestos.append("sin costos de ingredientes no se puede calcular la ganancia: solo el ingreso después de "
                         "comisiones")

    top = _consulta(f"""SELECT canal, producto, SUM(cantidad) AS unidades FROM ventas
                        WHERE {filtro_v} AND categoria <> 'Interno' AND canal IN ('Local', 'Didi', 'Rappi')
                        GROUP BY canal, producto""", ruta_db, registro)
    filas_top = []
    for canal, g in top.groupby("canal"):
        g = g.sort_values("unidades", ascending=False)
        total = g["unidades"].sum()
        for r in g.head(5).itertuples():
            filas_top.append([canal, r.producto, int(r.unidades), _r(100 * r.unidades / total, 1)])
    desde, hasta = str(df["desde"].min()), str(df["hasta"].max())
    explicacion = (f"Ingreso por canal de las órdenes cobradas del {desde} al {hasta}: venta cobrada, sobreprecio de "
                   "las apps contra el precio de mostrador, comisión estimada y lo que queda después de la comisión. "
                   "«Comisión que cubre el sobreprecio» es la comisión máxima con la que un pedido en la app deja lo "
                   "mismo que venderlo a precio de mostrador; si la comisión real es mayor, cada pedido en la app deja "
                   "menos que en mostrador. El ingreso por orden NO se compara directo entre canales porque los pedidos "
                   "de app suelen ser más grandes: la comparación justa es «gana o pierde por orden vs mostrador», lo "
                   "que deja de más (positivo) o de menos (negativo) cada pedido de app comparado con vender esos mismos "
                   "productos en el mostrador. Supuestos: " + "; ".join(supuestos) + ".")
    grafica = {"tipo": "barras", "x": "canal", "y": ["venta_cobrada", "ingreso_despues_de_comision"],
               "titulo": "Lo que cobras y lo que te queda después de comisiones"}
    return _resultado("Rentabilidad por canal", columnas, filas, explicacion, supuestos,
                      [{"proposito": "productos más pedidos en cada canal", "columnas":
                        ["canal", "producto", "unidades", "porcentaje_de_unidades_del_canal"], "filas": filas_top}],
                      {"dias": None if periodo else dias, "mes": mes, "anio": anio, "comisiones": {c: v[0] for c, v in com.items()}},
                      registro, grafica)


# ---------------------------------------------------------------------------
# 3) Promociones: qué se pide junto y simulador de combos
# ---------------------------------------------------------------------------
def _promos_activas(ruta_db: str, registro: list[str]) -> list[set]:
    p = _consulta("SELECT promocion, producto FROM promociones WHERE activa AND producto IS NOT NULL", ruta_db, registro)
    return [set(g["producto"]) for _, g in p.groupby("promocion")]


def combinaciones_frecuentes(ruta_db: str, dias: int | None = 180, top: int = 10, min_ordenes: int = 10) -> dict:
    registro: list[str] = []
    filtro = _filtro_dias(dias, "ventas")
    df = _consulta(f"""
        WITH l AS (SELECT DISTINCT id_orden, producto FROM ventas
                   WHERE categoria <> 'Interno' AND producto <> '--' AND {filtro}),
        n AS (SELECT COUNT(DISTINCT id_orden) AS total FROM l),
        p AS (SELECT producto, COUNT(*) AS ordenes FROM l GROUP BY producto)
        SELECT a.producto AS producto_1, b.producto AS producto_2, COUNT(*) AS juntos,
               MAX(pa.ordenes) AS ordenes_1, MAX(pb.ordenes) AS ordenes_2, MAX(n.total) AS total
        FROM l a JOIN l b ON a.id_orden = b.id_orden AND a.producto < b.producto
        JOIN p pa ON pa.producto = a.producto JOIN p pb ON pb.producto = b.producto CROSS JOIN n
        GROUP BY a.producto, b.producto HAVING COUNT(*) >= {int(min_ordenes)}
        ORDER BY juntos DESC LIMIT 80""", ruta_db, registro)
    if df.empty:
        raise ErrorAnalisis("No hay suficientes órdenes con varios productos en ese periodo.")
    promos = _promos_activas(ruta_db, registro)
    df["afinidad"] = df["juntos"] * df["total"] / (df["ordenes_1"] * df["ordenes_2"])
    df["porcentaje"] = 100 * df["juntos"] / df["total"]
    df["promo"] = ["sí" if any({a, b} <= s for s in promos) else "no" for a, b in zip(df.producto_1, df.producto_2)]
    filas = [[r.producto_1, r.producto_2, int(r.juntos), _r(r.porcentaje, 1), _r(r.afinidad), r.promo,
              f"{r.producto_1} + {r.producto_2}"] for r in df.head(top).itertuples()]
    afines = df[(df["afinidad"] >= 1.2)].sort_values("afinidad", ascending=False).head(8)
    franjas = _consulta(f"""
        WITH d AS (SELECT dia_semana, num_dia_semana, COUNT(DISTINCT fecha) AS dias FROM ordenes
                   WHERE {_filtro_dias(dias)} GROUP BY dia_semana, num_dia_semana)
        SELECT o.dia_semana, o.num_dia_semana,
               CASE WHEN o.hora_del_dia < 12 THEN 'mañana (antes de las 12)'
                    WHEN o.hora_del_dia < 17 THEN 'comida (12 a 17)' ELSE 'tarde (17 en adelante)' END AS franja,
               ROUND(COUNT(*) * 1.0 / MAX(d.dias), 1) AS ordenes_por_dia
        FROM ordenes o JOIN d ON o.num_dia_semana = d.num_dia_semana
        WHERE NOT o.cancelada AND {_filtro_dias(dias, alias='o')}
        GROUP BY o.dia_semana, o.num_dia_semana, franja
        ORDER BY ordenes_por_dia ASC LIMIT 6""", ruta_db, registro)
    explicacion = ("Pares de productos que más se piden en la misma orden "
                   f"{'en los últimos ' + str(dias) + ' días' if dias else ''} (sin cargos internos). «Afinidad» = cuántas "
                   "veces más se piden juntos que si se eligieran al azar: mayor que 1 significa que sí tienden a ir "
                   "juntos. «Ya es promoción» indica si existe una promoción activa con ambos productos. También se "
                   "muestran los días y horarios más flojos, buenos para una promoción que atraiga clientes.")
    return _resultado("Productos que se piden juntos",
                      ["producto_1", "producto_2", "ordenes_juntos", "porcentaje_de_ordenes", "afinidad", "ya_es_promocion",
                       "combinacion"],
                      filas, explicacion, [],
                      [{"proposito": "pares con más afinidad (se piden juntos más de lo normal)",
                        "columnas": ["producto_1", "producto_2", "ordenes_juntos", "afinidad", "ya_es_promocion"],
                        "filas": [[r.producto_1, r.producto_2, int(r.juntos), _r(r.afinidad), r.promo]
                                  for r in afines.itertuples()]},
                       {"proposito": "días y horarios más flojos (promedio de órdenes por día abierto)",
                        "columnas": list(franjas.columns), "filas": franjas.values.tolist()}],
                      {"dias": dias, "min_ordenes": min_ordenes}, registro,
                      {"tipo": "barras_horizontales", "x": "combinacion", "y": ["ordenes_juntos"],
                       "titulo": "Lo que tus clientes más piden junto"})


def _precio_actual(ruta_db: str, productos: list[str], registro: list[str]) -> dict[str, float]:
    df = _consulta(f"""
        SELECT producto, precio_unitario, COUNT(*) AS n, MAX(fecha) AS ultima FROM ventas
        WHERE {_en('producto', productos)} AND precio_unitario > 0
          AND fecha > (SELECT MAX(fecha) FROM ventas) - INTERVAL 60 DAY
        GROUP BY producto, precio_unitario""", ruta_db, registro)
    precios = {p: float(g.sort_values(["n", "ultima"]).iloc[-1]["precio_unitario"]) for p, g in df.groupby("producto")}
    faltan = [p for p in productos if p not in precios]
    if faltan:
        cat = _consulta(f"SELECT producto, precio FROM productos WHERE {_en('producto', faltan)}", ruta_db, registro)
        precios.update({r.producto: float(r.precio) for r in cat.itertuples() if r.precio})
    return precios


def simular_promocion(ruta_db: str, productos: dict[str, int], precio_promocional: float, dias: int | None = 90,
                      margen_bruto: float | None = None) -> dict:
    """¿Cuántos combos más por semana hacen falta para que el descuento no cueste dinero?"""
    registro: list[str] = []
    menu = productos_de(ruta_db)
    combo: dict[str, int] = {}
    for nombre, cantidad in (productos or {}).items():
        exacto = resolver_producto(nombre, menu)
        if not exacto:
            raise ErrorAnalisis(f"No encontré «{nombre}» en el menú.")
        combo[exacto] = combo.get(exacto, 0) + max(1, int(cantidad or 1))
    if not combo or not precio_promocional or float(precio_promocional) <= 0:
        raise ErrorAnalisis("Para simular una promoción necesito los productos del combo y su precio.")
    precio_promocional = float(precio_promocional)
    precios = _precio_actual(ruta_db, list(combo), registro)
    if any(p not in precios for p in combo):
        raise ErrorAnalisis("No encontré el precio actual de " + ", ".join(p for p in combo if p not in precios) + ".")
    precio_normal = sum(precios[p] * q for p, q in combo.items())
    descuento = precio_normal - precio_promocional
    filtro = _filtro_dias(dias, "ventas")
    lin = _consulta(f"""SELECT id_orden, producto, SUM(cantidad) AS c, MIN(fecha) AS f FROM ventas
                        WHERE canal = 'Local' AND {_en('producto', list(combo))} AND {filtro}
                        GROUP BY id_orden, producto""", ruta_db, registro)
    rango = _consulta(f"SELECT MIN(fecha) AS desde, MAX(fecha) AS hasta FROM ventas WHERE {filtro}", ruta_db, registro)
    desde, hasta = pd.to_datetime(rango["desde"].iloc[0]).date(), pd.to_datetime(rango["hasta"].iloc[0]).date()
    semanas = max(1.0, ((hasta - desde).days + 1) / 7)
    tabla = lin.pivot_table(index="id_orden", columns="producto", values="c", aggfunc="sum", fill_value=0)
    combos = 0
    if len(tabla) and all(p in tabla.columns for p in combo):
        combos = int(sum(min(int(fila[p]) // q for p, q in combo.items()) for _, fila in tabla.iterrows()))
    combos_semana = combos / semanas
    con_alguno_semana = len(tabla) / semanas
    regalo_semana = max(descuento, 0) * combos_semana

    costos = cargar_costos()["costos_producto"]
    supuestos = []
    if all(p in costos for p in combo):
        costo_combo = sum(costos[p] * q for p, q in combo.items())
        margenes = [1 - costo_combo / precio_normal]
        supuestos.append("margen con los costos de ingredientes que dio el dueño")
    elif margen_bruto is not None:
        margenes = [float(margen_bruto) / 100 if margen_bruto > 1 else float(margen_bruto)]
        supuestos.append(f"margen bruto de {margenes[0]:.0%} indicado por el dueño")
    else:
        margenes = list(MARGENES_SUPUESTOS)
        supuestos.append("SUPUESTO: se desconoce el costo de ingredientes, así que se prueban márgenes de 40, 50 y 60 %")
    filas = []
    for m in margenes:
        costo = precio_normal * (1 - m)
        gan_normal, gan_promo = precio_normal - costo, precio_promocional - costo
        extra = regalo_semana / gan_promo if gan_promo > 0 else None
        filas.append([round(m * 100), _r(gan_normal), _r(gan_promo), _r(extra, 1),
                      _r(100 * extra / combos_semana, 1) if extra is not None and combos_semana > 0 else None,
                      f"Si ganas {round(m * 100)} %"])
    if descuento <= 0:
        supuestos.append("el precio propuesto no es menor que el precio normal: no es un descuento")
    if any(f[2] is not None and f[2] <= 0 for f in filas):
        supuestos.append("con algún margen el combo se vendería por debajo del costo: cada combo perdería dinero")
    nombre = " + ".join(f"{q} {p}" if q > 1 else p for p, q in combo.items())
    explicacion = (f"Simulación del combo {nombre} a ${precio_promocional:,.2f} (precio normal ${precio_normal:,.2f}). "
                   f"Se usan las órdenes de mostrador del {desde} al {hasta}: los clientes que YA piden esos productos "
                   "juntos también recibirían el descuento, y eso cuesta dinero; la tabla dice cuántos combos ADICIONALES "
                   "por semana hacen falta para recuperarlo según el margen de ganancia. Supuestos: "
                   + "; ".join(supuestos) + ".")
    apoyo = [{"proposito": "datos base del combo", "columnas": ["concepto", "valor"], "filas": [
        ["precio normal del combo", _r(precio_normal)], ["precio con la promoción", _r(precio_promocional)],
        ["descuento por combo", _r(descuento)], ["combos que ya se venden por semana (mostrador)", _r(combos_semana, 1)],
        ["órdenes por semana con alguno de esos productos", _r(con_alguno_semana, 1)],
        ["descuento que se daría por semana a quienes ya lo piden", _r(regalo_semana)]]}]
    return _resultado(f"Simulación: {nombre} a ${precio_promocional:,.0f}",
                      ["margen_bruto_pct", "ganancia_por_combo_precio_normal", "ganancia_por_combo_con_promocion",
                       "combos_extra_por_semana_para_no_perder", "aumento_necesario_pct", "escenario"],
                      filas, explicacion, supuestos, apoyo,
                      {"productos": combo, "precio_promocional": precio_promocional, "dias": dias}, registro,
                      {"tipo": "barras", "x": "escenario", "y": ["combos_extra_por_semana_para_no_perder"],
                       "titulo": "Combos extra por semana para no perder dinero"})


# ---------------------------------------------------------------------------
# 4) Lista de compras: pan pronosticado × precio (Chedraui Ciudad del Carmen o el del dueño)
# ---------------------------------------------------------------------------
def _bebidas_por_acabarse(ruta_db: str, dias_a_cubrir: int, registro: list[str]) -> list[list]:
    """Bebidas cuyo inventario del POS no alcanza para los días a cubrir, con la cantidad sugerida."""
    df = _consulta("""
        WITH f AS (SELECT MAX(fecha) AS m FROM ventas),
        abiertos AS (SELECT COUNT(DISTINCT fecha) AS n FROM ordenes, f WHERE fecha > f.m - INTERVAL 28 DAY),
        v AS (SELECT producto, SUM(cantidad) AS u FROM ventas, f
              WHERE categoria = 'Bebidas' AND fecha > f.m - INTERVAL 28 DAY GROUP BY producto)
        SELECT p.producto, p.stock, v.u * 1.0 / NULLIF(MAX(a.n), 0) AS diario
        FROM productos p JOIN v ON v.producto = p.producto, abiertos a
        WHERE p.activo AND p.stock IS NOT NULL GROUP BY p.producto, p.stock, v.u""", ruta_db, registro)
    filas = []
    for r in df.itertuples():
        if not r.diario or r.diario <= 0:
            continue
        alcanza = float(r.stock) / r.diario
        if alcanza < dias_a_cubrir + 1:
            filas.append([r.producto, int(r.stock), _r(r.diario, 1), _r(max(alcanza, 0), 1),
                          max(0, math.ceil(r.diario * dias_a_cubrir - max(float(r.stock), 0)))])
    return sorted(filas, key=lambda f: f[3])[:8]


def _receta_de(producto: str) -> str | None:
    n = normalizar(producto)
    return next((r for r in ("barda", "pierna", "mixta", "barbacoa") if r in n), None)


def _tortas_por_producto(ruta_db: str, piezas: dict, registro: list[str]) -> dict[str, float]:
    """Reparte las tortas normal y Mega pronosticadas según lo que se vendió de cada una en 8 semanas."""
    productos = productos_de(ruta_db)
    normales, megas = productos_de_grupo("pan normal", productos), productos_de_grupo("pan mega", productos)
    ventas = _consulta(f"""SELECT producto, SUM(cantidad) AS u FROM ventas
                           WHERE {_en('producto', normales + megas)}
                             AND fecha > (SELECT MAX(fecha) FROM ventas) - INTERVAL 56 DAY
                           GROUP BY producto""", ruta_db, registro)
    u = dict(zip(ventas["producto"], ventas["u"].astype(float)))
    salida = {}
    for grupo, clave in ((normales, "pan_normal"), (megas, "pan_mega")):
        total = sum(u.get(x, 0) for x in grupo)
        for x in grupo:
            salida[x] = piezas[clave] * u.get(x, 0) / total if total else 0.0
    return salida


def lista_de_compras(ruta_db: str, fechas: list | None = None, margen: float | None = None, hoy: date | None = None,
                     forzar_precios: bool = False) -> dict:
    """Pan e ingredientes de las tortas para los días pedidos (mañana si no se dice) y cuánto se va a gastar."""
    from ..conectores.precios import TIENDA, ErrorPrecios, precios_insumos

    pron = pronosticar_pan(ruta_db, fechas, margen=margen, hoy=hoy)
    registro = list(pron["sql_ejecutadas"])
    i = {c: k for k, c in enumerate(pron["columnas"])}
    piezas = {"pan_normal": sum(int(f[i["comprar_pan_normal"]]) for f in pron["filas"]),
              "pan_mega": sum(int(f[i["comprar_pan_mega"]]) for f in pron["filas"])}
    extra = {"pan_normal": sum(f[i["comprar_pan_normal"]] - f[i["pan_normal_esperado"]] for f in pron["filas"]),
             "pan_mega": sum(f[i["comprar_pan_mega"]] - f[i["pan_mega_esperado"]] for f in pron["filas"])}
    costos = cargar_costos()
    compras, ingr = costos["compras"], costos["ingredientes"]
    productos_ingr = ingr.get("productos") or {}
    recetas = ingr.get("recetas") or {}
    factor_mega = float(ingr.get("factor_mega") or 1.35)

    # gramos de cada ingrediente según las tortas que se esperan de cada tipo
    gramos: dict[str, float] = {}
    if recetas:
        megas = set(productos_de_grupo("pan mega", productos_de(ruta_db)))
        for producto, tortas in _tortas_por_producto(ruta_db, piezas, registro).items():
            receta = recetas.get(_receta_de(producto) or "", {})
            for clave, g in receta.items():
                gramos[clave] = gramos.get(clave, 0) + tortas * float(g) * (factor_mega if producto in megas else 1)

    por_buscar = {k: compras[k]["buscar"] for k in ("pan_normal", "pan_mega") if compras[k]["precio_por_pieza"] is None}
    por_buscar.update({k: productos_ingr[k]["chedraui"] for k in gramos if (productos_ingr.get(k) or {}).get("chedraui")})
    info, avisos = None, []
    if por_buscar:
        try:
            info = precios_insumos(por_buscar, compras["codigo_postal"], forzar=forzar_precios)
            if info.get("aviso"):
                avisos.append(info["aviso"])
        except ErrorPrecios as e:
            avisos.append(f"No pude consultar los precios de {TIENDA} ({e}).")
    consultado = (info or {}).get("consultado", "")[:10]
    tienda = ((info or {}).get("productos") or {})

    def fuente(p: dict) -> str:
        return (f"{TIENDA} · {p['producto']}" + ("" if p.get("regional", True) else " (precio general en línea)")
                + f" · {consultado}")

    filas, precio_de = [], {}
    for clave, nombre in (("pan_normal", "Pan normal (telera)"), ("pan_mega", "Pan Mega (telera doble)")):
        manual, producto = compras[clave]["precio_por_pieza"], tienda.get(clave) or {}
        if manual is not None:
            precio, origen = manual, "precio que indicó el dueño"
        elif producto.get("precio"):
            precio, origen = producto["precio"], fuente(producto)
        else:
            precio, origen = None, "sin precio (no se encontró en la tienda)"
        precio_de[clave] = precio
        filas.append([nombre, piezas[clave], "piezas", precio, _r(piezas[clave] * precio) if precio else None, origen])
    gasto_pan = sum(f[4] for f in filas if f[4] is not None)

    for clave, g in sorted(gramos.items(), key=lambda kv: -kv[1]):
        kg = g / 1000
        nombre = (productos_ingr.get(clave) or {}).get("nombre", clave.replace("_", " ").capitalize())
        p = tienda.get(clave) or {}
        if p.get("unidad") == "paquete" and p.get("presentacion_kg"):
            paquetes = max(1, math.ceil(kg / p["presentacion_kg"] - 1e-9))
            filas.append([nombre, paquetes, f"paquetes de {round(p['presentacion_kg'] * 1000)} g", p["precio"],
                          _r(paquetes * p["precio"]), fuente(p)])
        elif p.get("unidad") == "kg":
            kg = _r(kg, 2)  # el costo se calcula con los mismos kilos que se muestran
            filas.append([nombre, kg, "kg", p["precio"], _r(kg * p["precio"]), fuente(p)])
        else:
            filas.append([nombre, _r(kg, 2), "kg", None, None, "sin precio (no se encontró en la tienda)"])
    total = sum(f[4] for f in filas if f[4] is not None)

    por_dia = []
    for f in pron["filas"]:
        n, m = int(f[i["comprar_pan_normal"]]), int(f[i["comprar_pan_mega"]])
        costo = (n * (precio_de["pan_normal"] or 0) + m * (precio_de["pan_mega"] or 0)) if any(precio_de.values()) else None
        por_dia.append([f[i["dia_compra"]], n, m, _r(costo)])
    costo_margen = sum(extra[k] * (precio_de[k] or 0) for k in extra)
    dias = max(1, len(pron["filas"]))
    bebidas = _bebidas_por_acabarse(ruta_db, max(dias, 3), registro)
    supuestos = [s for s in pron["supuestos"] if "SUPUESTO" in s or "pan por torta" in s]
    if any(compras[k]["supuesto"] and compras[k]["precio_por_pieza"] is None for k in ("pan_normal", "pan_mega")):
        supuestos.append(f"se toma «{compras['pan_normal']['buscar']}» como pan normal y «{compras['pan_mega']['buscar']}» "
                         "como pan Mega (SUPUESTO: confírmalo o pon el precio de tu panadero en costos.yaml)")
    if gramos:
        supuestos.append("ingredientes según las porciones por torta de costos.yaml (Mega = "
                         f"{factor_mega:g} veces la normal)" + (" (SUPUESTO: porciones estimadas, ajústalas)"
                                                               if ingr.get("supuesto", True) else ""))
    if info:
        supuestos.append(f"precios de la tienda en línea de {TIENDA} (CP {compras['codigo_postal']}); en tienda o con tus "
                         "proveedores pueden variar")
    apoyo = [{"proposito": "resumen de la compra", "columnas": ["concepto", "valor"],
              "filas": [["gasto estimado total", _r(total)], ["gasto en pan", _r(gasto_pan)],
                        ["gasto en ingredientes", _r(total - gasto_pan)],
                        ["piezas de pan en total", piezas["pan_normal"] + piezas["pan_mega"]],
                        ["lo que cuesta el margen de seguridad del pan", _r(costo_margen)],
                        ["días que cubre la compra", dias]]},
             {"proposito": "pan a comprar por día", "columnas": ["dia", "pan_normal", "pan_mega", "costo_estimado"],
              "filas": por_dia}]
    if bebidas:
        apoyo.append({"proposito": f"bebidas que no alcanzan para {max(dias, 3)} días según el inventario del POS",
                      "columnas": ["bebida", "en_inventario", "venta_diaria", "dias_que_alcanza", "comprar"],
                      "filas": bebidas})
    explicacion = (f"Lista de compras para {dias} día(s): el pan sale del pronóstico de tortas (promedio del mismo día de "
                   "la semana más el margen de seguridad); los ingredientes, de repartir esas tortas entre barda, pierna, "
                   "mixta y barbacoa según lo que se vendió en 8 semanas y multiplicar por los gramos de cada receta; lo "
                   "que se vende en paquete se redondea a paquetes completos. "
                   + ("Las bebidas se comparan contra lo que se vende al día en las últimas 4 semanas. " if bebidas else "")
                   + "Supuestos: " + "; ".join(supuestos) + "." + (" Avisos: " + " ".join(avisos) if avisos else ""))
    return _resultado("Lista de compras",
                      ["insumo", "cantidad", "unidad", "precio_unitario", "costo_estimado", "precio_de"],
                      filas, explicacion, supuestos + avisos, apoyo + pron["apoyo"][:1],
                      {"fechas": pron["parametros"]["fechas"], "margen": pron["parametros"]["margen"],
                       "precios": {k: precio_de[k] for k in precio_de}}, registro,
                      {"tipo": "barras_horizontales", "x": "insumo", "y": ["costo_estimado"],
                       "titulo": "En qué se va el dinero de la compra"})
