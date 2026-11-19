"""Herramienta ``exportar_reporte``: PDF con las preguntas, gráficas y conclusiones de la sesión."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

import matplotlib
from fpdf import FPDF

from ..config import obtener_config
from ..utilidades import formato_numero
from .generar_grafica import grafica_png

_FUENTES = Path(matplotlib.get_data_path()) / "fonts" / "ttf"
AZUL = (11, 31, 58)
GRIS = (100, 110, 120)


def _sin_markdown(texto: str) -> str:
    texto = re.sub(r"\*\*([^*]+)\*\*", r"\1", texto or "")
    return re.sub(r"(?<!\w)_([^_]+)_(?!\w)", r"\1", texto)


class _PDF(FPDF):
    def header(self):
        if self.page_no() == 1:
            return
        self.set_font("dv", "", 8)
        self.set_text_color(*GRIS)
        self.cell(0, 6, "DataVoz · Reporte de la sesión", align="R")
        self.ln(8)

    def footer(self):
        self.set_y(-12)
        self.set_font("dv", "", 8)
        self.set_text_color(*GRIS)
        self.cell(0, 6, f"Generado por DataVoz (prototipo académico, datos sintéticos) · Página {self.page_no()}",
                  align="C")


def _tabla(pdf: FPDF, columnas: list[str], filas: list[list], max_filas: int = 10) -> None:
    if not columnas or not filas:
        return
    pdf.set_font("dv", "", 7.5)
    ancho = (pdf.w - pdf.l_margin - pdf.r_margin) / len(columnas)
    pdf.set_fill_color(230, 236, 246)
    for c in columnas:
        pdf.cell(ancho, 5, str(c)[:28], border=1, fill=True)
    pdf.ln()
    for fila in filas[:max_filas]:
        for v in fila:
            texto = formato_numero(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else str(v)
            pdf.cell(ancho, 5, texto[:30], border=1)
        pdf.ln()
    if len(filas) > max_filas:
        pdf.set_text_color(*GRIS)
        pdf.cell(0, 5, f"... y {len(filas) - max_filas} filas más")
        pdf.set_text_color(0, 0, 0)
        pdf.ln()


def exportar_reporte(historial: list[dict], resumen_datos: dict | None = None, alertas: list[dict] | None = None,
                     ruta_salida: str | Path | None = None, titulo: str = "Reporte de análisis de ventas") -> str:
    """Genera el PDF y devuelve su ruta.

    ``historial``: lista de turnos con claves pregunta, respuesta, sql, resultado
    ({columnas, filas}) y grafica ({spec}).
    """
    cfg = obtener_config()
    if ruta_salida is None:
        cfg.dir_reportes.mkdir(parents=True, exist_ok=True)
        ruta_salida = cfg.dir_reportes / f"reporte_datavoz_{datetime.now():%Y%m%d_%H%M%S}.pdf"
    ruta_salida = Path(ruta_salida)
    ruta_salida.parent.mkdir(parents=True, exist_ok=True)

    pdf = _PDF(format="Letter")
    pdf.add_font("dv", "", str(_FUENTES / "DejaVuSans.ttf"))
    pdf.add_font("dv", "B", str(_FUENTES / "DejaVuSans-Bold.ttf"))
    pdf.add_font("dvmono", "", str(_FUENTES / "DejaVuSansMono.ttf"))
    pdf.set_auto_page_break(True, margin=16)
    pdf.add_page()

    pdf.set_font("dv", "B", 18)
    pdf.set_text_color(*AZUL)
    pdf.cell(0, 10, "DataVoz · Háblale a tus datos", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("dv", "", 12)
    pdf.set_text_color(*GRIS)
    pdf.cell(0, 7, f"{titulo} · {datetime.now():%d/%m/%Y %H:%M}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    if resumen_datos and "error" not in resumen_datos:
        pdf.set_text_color(0, 0, 0)
        pdf.set_font("dv", "B", 12)
        pdf.cell(0, 8, "Datos analizados", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("dv", "", 10)
        pdf.multi_cell(0, 5.5, f"Periodo: {resumen_datos.get('desde')} a {resumen_datos.get('hasta')} · "
                               f"{formato_numero(resumen_datos.get('renglones'))} renglones de venta · "
                               f"{resumen_datos.get('productos')} productos · ventas totales "
                               f"${formato_numero(resumen_datos.get('total'))}.")
        pdf.ln(2)

    if alertas:
        pdf.set_font("dv", "B", 12)
        pdf.cell(0, 8, "Alertas automáticas", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("dv", "", 9.5)
        for a in alertas:
            pdf.multi_cell(0, 5, f"• {a['mensaje']}", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)

    turnos = [t for t in historial if t.get("respuesta")]
    if not turnos:
        pdf.set_font("dv", "", 10)
        pdf.multi_cell(0, 6, "Todavía no hay preguntas en esta sesión.")
    for i, t in enumerate(turnos, start=1):
        if pdf.get_y() > pdf.h - 80:
            pdf.add_page()
        pdf.set_text_color(*AZUL)
        pdf.set_font("dv", "B", 11.5)
        pdf.multi_cell(0, 6.5, f"{i}. {t.get('pregunta', '')}", new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(0, 0, 0)
        pdf.set_font("dv", "", 10)
        pdf.multi_cell(0, 5.5, _sin_markdown(t["respuesta"]), new_x="LMARGIN", new_y="NEXT")
        resultado = t.get("resultado") or {}
        spec = (t.get("grafica") or {}).get("spec") or {}
        png = grafica_png(resultado.get("columnas") or [], resultado.get("filas") or [], spec) if spec else None
        if png:
            import io
            pdf.ln(1)
            pdf.image(io.BytesIO(png), w=165, x=(pdf.w - 165) / 2)
        elif resultado.get("filas"):
            pdf.ln(1)
            _tabla(pdf, resultado["columnas"], resultado["filas"])
        if t.get("sql"):
            pdf.set_font("dvmono", "", 7)
            pdf.set_text_color(*GRIS)
            pdf.multi_cell(0, 3.6, "SQL: " + " ".join(t["sql"].split()), new_x="LMARGIN", new_y="NEXT")
            pdf.set_text_color(0, 0, 0)
        pdf.ln(4)

    pdf.output(str(ruta_salida))
    return str(ruta_salida)
