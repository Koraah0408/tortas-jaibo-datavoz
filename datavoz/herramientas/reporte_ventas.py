"""Reporte de ventas de un día o periodo de Tortas Jaibo (con PDF), hecho con la copia del POS.

Es el mismo tipo de reporte que el POS manda cada noche por correo, pero se arma aquí mismo con las ventas que ya
tiene la app: no hace falta conectar Gmail. Incluye lo cobrado, órdenes, ticket, formas de pago, canales,
lo más vendido y las ventas por hora.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from pathlib import Path

import matplotlib
from fpdf import FPDF

from ..config import obtener_config
from ..utilidades import normalizar
from .negocio_jaibo import ErrorAnalisis, _consulta, _r, _resultado

_FUENTES = Path(matplotlib.get_data_path()) / "fonts" / "ttf"
ROJO, CARBON, GRIS, CREMA = (200, 16, 46), (43, 35, 32), (110, 95, 78), (252, 239, 203)
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
         "noviembre", "diciembre"]


def _fecha_texto(d: date) -> str:
    return f"{d.day} de {MESES[d.month - 1]} de {d.year}"


def periodo_texto(desde: date, hasta: date) -> str:
    return _fecha_texto(desde) if desde == hasta else f"del {_fecha_texto(desde)} al {_fecha_texto(hasta)}"


def periodo_de_pregunta(pregunta: str, ultimo: date, hoy: date | None = None) -> tuple[date, date]:
    """Periodo PASADO que pide la pregunta. Sin año, el más reciente con datos; sin fecha, el último día con ventas."""
    hoy = hoy or ultimo
    t = normalizar(pregunta)
    mes_re = "|".join(MESES)

    def dia_mes(d: int, mes: int | None, anio: int | None) -> date:
        if mes is None:  # «del 18»: el 18 más reciente que no sea posterior al último dato
            f = date(ultimo.year, ultimo.month, min(d, 28 if ultimo.month == 2 else 30 if ultimo.month in (4, 6, 9, 11) else 31))
            return f if f <= ultimo else (f.replace(day=1) - timedelta(days=1)).replace(day=min(d, 28))
        f = date(anio or ultimo.year, mes, d)
        return f if anio or f <= ultimo else date(f.year - 1, mes, d)

    m = re.search(rf"\bdel? (\d{{1,2}})(?: de ({mes_re}))? al (\d{{1,2}}) de ({mes_re})(?: (?:de|del) (\d{{4}}))?", t)
    if m:
        anio = int(m.group(5)) if m.group(5) else None
        hasta = dia_mes(int(m.group(3)), MESES.index(m.group(4)) + 1, anio)
        desde = date(hasta.year, MESES.index(m.group(2) or m.group(4)) + 1, int(m.group(1)))
        return min(desde, hasta), max(desde, hasta)
    m = re.search(rf"\b(\d{{1,2}}) de ({mes_re})(?: (?:de|del) (\d{{4}}))?", t)
    if m:
        f = dia_mes(int(m.group(1)), MESES.index(m.group(2)) + 1, int(m.group(3)) if m.group(3) else None)
        return f, f
    if re.search(r"\banteayer\b", t):
        return hoy - timedelta(days=2), hoy - timedelta(days=2)
    if re.search(r"\bayer\b", t):
        return hoy - timedelta(days=1), hoy - timedelta(days=1)
    if re.search(r"\bhoy\b", t):
        return hoy, hoy
    if re.search(r"\bsemana pasada\b", t):
        return ultimo - timedelta(days=13), ultimo - timedelta(days=7)
    if re.search(r"\b(semana|ultimos 7 dias)\b", t):
        return ultimo - timedelta(days=6), ultimo
    if re.search(r"\bmes pasado\b", t):
        fin = ultimo.replace(day=1) - timedelta(days=1)
        return fin.replace(day=1), fin
    m = re.search(rf"\b({mes_re})\b(?: (?:de|del) (\d{{4}}))?", t)
    if m:
        mes = MESES.index(m.group(1)) + 1
        anio = int(m.group(2)) if m.group(2) else (ultimo.year if mes <= ultimo.month else ultimo.year - 1)
        fin = date(anio + (mes == 12), mes % 12 + 1, 1) - timedelta(days=1)
        return date(anio, mes, 1), min(fin, ultimo)
    if re.search(r"\b(este mes|del mes|el mes)\b", t):
        return ultimo.replace(day=1), ultimo
    m = re.search(r"\bdel? (\d{1,2})\b", t)
    if m and 1 <= int(m.group(1)) <= 31:
        f = dia_mes(int(m.group(1)), None, None)
        return f, f
    return ultimo, ultimo


def datos_del_reporte(ruta_db: str, desde: date, hasta: date) -> dict:
    registro: list[str] = []
    filtro = f"fecha BETWEEN DATE '{desde.isoformat()}' AND DATE '{hasta.isoformat()}'"
    res = _consulta(f"""SELECT COUNT(*) FILTER (WHERE NOT cancelada) AS ordenes,
                               COALESCE(SUM(monto_total) FILTER (WHERE NOT cancelada), 0) AS vendido,
                               COUNT(*) FILTER (WHERE cancelada) AS corregidas,
                               COALESCE(SUM(descuento) FILTER (WHERE NOT cancelada), 0) AS descuento,
                               COUNT(DISTINCT fecha) AS dias
                        FROM ordenes WHERE {filtro}""", ruta_db, registro).iloc[0]
    if not res["ordenes"]:
        raise ErrorAnalisis(f"No hay ventas registradas {periodo_texto(desde, hasta)} (¿el negocio no abrió?).")
    pagos = _consulta(f"""SELECT metodo_pago, COUNT(*) AS ordenes, ROUND(SUM(monto_total), 2) AS vendido
                          FROM ordenes WHERE NOT cancelada AND {filtro} GROUP BY metodo_pago ORDER BY vendido DESC""",
                      ruta_db, registro)
    canales = _consulta(f"""SELECT canal, COUNT(*) AS ordenes, ROUND(SUM(monto_total), 2) AS vendido
                            FROM ordenes WHERE NOT cancelada AND {filtro} GROUP BY canal ORDER BY vendido DESC""",
                        ruta_db, registro)
    productos = _consulta(f"""SELECT producto, SUM(cantidad) AS unidades, ROUND(SUM(total), 2) AS venta
                              FROM ventas WHERE categoria <> 'Interno' AND {filtro}
                              GROUP BY producto ORDER BY unidades DESC LIMIT 10""", ruta_db, registro)
    horas = _consulta(f"""SELECT hora_del_dia, COUNT(*) AS ordenes, ROUND(SUM(monto_total), 2) AS vendido
                          FROM ordenes WHERE NOT cancelada AND {filtro} GROUP BY hora_del_dia ORDER BY hora_del_dia""",
                      ruta_db, registro)
    ordenes, vendido = int(res["ordenes"]), float(res["vendido"])
    return {"desde": desde, "hasta": hasta, "ordenes": ordenes, "vendido": round(vendido, 2),
            "ticket": round(vendido / ordenes, 2), "corregidas": int(res["corregidas"]),
            "descuento": round(float(res["descuento"]), 2), "dias": int(res["dias"]),
            "pagos": pagos, "canales": canales, "productos": productos, "horas": horas, "registro": registro}


class _PDF(FPDF):
    titulo = ""

    def header(self):
        self.set_fill_color(*ROJO)
        self.rect(0, 0, 210, 26, "F")
        self.set_text_color(255, 255, 255)
        self.set_font("dv", "B", 16)
        self.set_xy(12, 7)
        self.cell(0, 8, "TORTAS JAIBO · Reporte de ventas")
        self.set_font("dv", "", 9.5)
        self.set_xy(12, 15)
        self.cell(0, 6, self.titulo)
        self.set_y(32)

    def footer(self):
        self.set_y(-12)
        self.set_font("dv", "", 7.5)
        self.set_text_color(*GRIS)
        self.cell(0, 6, f"Hecho con DataVoz a partir de la copia de solo lectura del POS · página {self.page_no()}", align="C")


def _seccion(pdf: FPDF, texto: str) -> None:
    pdf.ln(3)
    pdf.set_font("dv", "B", 11.5)
    pdf.set_text_color(*ROJO)
    pdf.cell(0, 7, texto, new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(*CARBON)


def _tabla(pdf: FPDF, encabezados: list[str], filas: list[list], anchos: list[int], dinero: set[int]) -> None:
    pdf.set_font("dv", "B", 8.5)
    pdf.set_fill_color(*CREMA)
    for h, a in zip(encabezados, anchos):
        pdf.cell(a, 6.5, h, border=0, fill=True)
    pdf.ln()
    pdf.set_font("dv", "", 8.5)
    for f in filas:
        for i, (v, a) in enumerate(zip(f, anchos)):
            texto = f"${v:,.2f}" if i in dinero and isinstance(v, (int, float)) else (
                f"{v:,.0f}" if isinstance(v, (int, float)) else str(v))
            pdf.cell(a, 6, texto, align="R" if isinstance(v, (int, float)) else "L")
        pdf.ln()


def generar_pdf(d: dict, ruta: Path) -> Path:
    pdf = _PDF(format="Letter")
    pdf.add_font("dv", "", str(_FUENTES / "DejaVuSans.ttf"))
    pdf.add_font("dv", "B", str(_FUENTES / "DejaVuSans-Bold.ttf"))
    pdf.titulo = f"Periodo: {periodo_texto(d['desde'], d['hasta'])} · generado el {datetime.now():%d/%m/%Y %H:%M}"
    pdf.set_auto_page_break(True, 16)
    pdf.add_page()
    pdf.set_text_color(*CARBON)
    _seccion(pdf, "Resumen")
    resumen = [("Ventas cobradas", f"${d['vendido']:,.2f}"), ("Órdenes", f"{d['ordenes']:,}"),
               ("Ticket promedio", f"${d['ticket']:,.2f}"), ("Descuentos por promociones", f"${d['descuento']:,.2f}"),
               ("Pedidos corregidos (cancelados por modificación)", f"{d['corregidas']:,}")]
    if d["dias"] > 1:
        resumen.insert(2, ("Días con venta", f"{d['dias']}"))
    pdf.set_font("dv", "", 10)
    for etiqueta, valor in resumen:
        pdf.cell(110, 7, etiqueta)
        pdf.set_font("dv", "B", 10)
        pdf.cell(0, 7, valor, new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("dv", "", 10)
    _seccion(pdf, "Por forma de pago")
    _tabla(pdf, ["Forma de pago", "Órdenes", "Vendido"], d["pagos"].values.tolist(), [90, 40, 50], {2})
    _seccion(pdf, "Por canal")
    _tabla(pdf, ["Canal", "Órdenes", "Vendido"], d["canales"].values.tolist(), [90, 40, 50], {2})
    _seccion(pdf, "Lo más vendido")
    _tabla(pdf, ["Producto", "Piezas", "Venta (precio del renglón)"], d["productos"].values.tolist(), [90, 40, 50], {2})
    _seccion(pdf, "Por hora del día")
    _tabla(pdf, ["Hora", "Órdenes", "Vendido"],
           [[f"{int(h)}:00", o, v] for h, o, v in d["horas"].values.tolist()], [90, 40, 50], {2})
    ruta.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(ruta))
    return ruta


def reporte_de_ventas(ruta_db: str, desde: str | date, hasta: str | date | None = None) -> dict:
    """Herramienta del Asesor: resumen de ventas de un día o periodo + su PDF."""
    desde = desde if isinstance(desde, date) else date.fromisoformat(str(desde))
    hasta = (hasta if isinstance(hasta, date) else date.fromisoformat(str(hasta))) if hasta else desde
    d = datos_del_reporte(ruta_db, desde, hasta)
    nombre = f"reporte_ventas_{desde:%Y%m%d}" + ("" if desde == hasta else f"_{hasta:%Y%m%d}") + ".pdf"
    pdf = generar_pdf(d, obtener_config().dir_reportes / nombre)
    pagos = [[p, int(o), _r(v)] for p, o, v in d["pagos"].values.tolist()]
    apoyo = [{"proposito": "resumen del periodo", "columnas": ["concepto", "valor"],
              "filas": [["ventas cobradas", d["vendido"]], ["órdenes", d["ordenes"]], ["ticket promedio", d["ticket"]],
                        ["descuentos por promociones", d["descuento"]], ["pedidos corregidos", d["corregidas"]],
                        ["días con venta", d["dias"]]]},
             {"proposito": "ventas por canal", "columnas": ["canal", "ordenes", "vendido"],
              "filas": [[c, int(o), _r(v)] for c, o, v in d["canales"].values.tolist()]},
             {"proposito": "lo más vendido", "columnas": ["producto", "piezas", "venta"],
              "filas": [[p, int(u), _r(v)] for p, u, v in d["productos"].values.tolist()]}]
    explicacion = (f"Reporte de ventas {periodo_texto(desde, hasta)} con la copia del POS: ventas cobradas (sin órdenes "
                   "canceladas), órdenes, ticket promedio, formas de pago, canales y lo más vendido. El PDF completo "
                   "también trae las ventas por hora.")
    r = _resultado(f"Reporte de ventas {periodo_texto(desde, hasta)}", ["forma_de_pago", "ordenes", "vendido"], pagos,
                   explicacion, [], apoyo, {"desde": desde.isoformat(), "hasta": hasta.isoformat(), "pdf": str(pdf)},
                   d["registro"], {"tipo": "barras_horizontales", "x": "forma_de_pago", "y": ["vendido"],
                                   "titulo": f"Ventas por forma de pago · {periodo_texto(desde, hasta)}"})
    r["pdf"] = str(pdf)
    return r
