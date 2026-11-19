"""Reporte de ventas de un día o periodo (con PDF) hecho con la copia del POS, sin Gmail."""

import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from datavoz.agentes import orquestador
from datavoz.agentes.asesor_negocio import elegir
from datavoz.basedatos import escribir_tablas
from datavoz.conectores import jaibo
from datavoz.herramientas import HERRAMIENTAS_NEGOCIO
from datavoz.herramientas import reporte_ventas as rv
from datavoz.herramientas.negocio_jaibo import ErrorAnalisis

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from generar_datos_jaibo import generar  # noqa: E402

ULTIMO, HOY = date(2026, 4, 30), date(2026, 5, 1)


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    crudo = generar(inicio=date(2026, 3, 1), fin=ULTIMO)
    ruta = tmp_path_factory.mktemp("reporte") / "jaibo.duckdb"
    escribir_tablas(ruta, jaibo.transformar({k: crudo[k] for k in jaibo.VISTAS}), reemplazar_archivo=True)
    return str(ruta)


@pytest.fixture
def carpeta(monkeypatch, tmp_path):
    monkeypatch.setattr(rv, "obtener_config", lambda: SimpleNamespace(dir_reportes=tmp_path))
    return tmp_path


@pytest.mark.parametrize("pregunta, esperado", [
    ("reporte de ventas del 18", (date(2026, 4, 18), date(2026, 4, 18))),
    ("dame el pdf del 18 de marzo", (date(2026, 3, 18), date(2026, 3, 18))),
    ("reporte de ayer", (date(2026, 4, 30), date(2026, 4, 30))),
    ("reporte del 10 al 15 de abril", (date(2026, 4, 10), date(2026, 4, 15))),
    ("resumen de la semana", (date(2026, 4, 24), date(2026, 4, 30))),
    ("reporte de marzo", (date(2026, 3, 1), date(2026, 3, 31))),
    ("dame el reporte", (ULTIMO, ULTIMO)),
])
def test_el_periodo_sale_de_la_pregunta(pregunta, esperado):
    assert rv.periodo_de_pregunta(pregunta, ULTIMO, HOY) == esperado


def test_un_dia_posterior_al_ultimo_dato_es_del_mes_anterior():
    assert rv.periodo_de_pregunta("reporte del 25", date(2026, 11, 18)) == (date(2026, 10, 25), date(2026, 10, 25))


def test_reporte_del_dia_con_pdf(db, carpeta):
    r = HERRAMIENTAS_NEGOCIO["reporte_de_ventas"].invoke({"ruta_db": db, "desde": "2026-04-18"})
    resumen = dict(r["apoyo"][0]["filas"])
    assert resumen["órdenes"] > 0 and resumen["ventas cobradas"] > 0
    assert sum(f[2] for f in r["filas"]) == pytest.approx(resumen["ventas cobradas"], abs=0.05)  # pagos = total
    pdf = Path(r["pdf"])
    assert pdf.parent == carpeta and pdf.name == "reporte_ventas_20260418.pdf"
    assert pdf.read_bytes().startswith(b"%PDF")


def test_un_dia_sin_ventas_avisa(db, carpeta):
    with pytest.raises(ErrorAnalisis):
        rv.reporte_de_ventas(db, "2025-01-01")


def test_el_asesor_calcula_el_periodo_sin_llm():
    assert elegir("reporte_ventas", "reporte de ventas del 18", {}, [], HOY, ULTIMO) == (
        "reporte_de_ventas", {"desde": "2026-04-18", "hasta": "2026-04-18"})


def _orquestar(pregunta: str, dominio: str = "jaibo") -> dict:
    return orquestador.orquestar.__wrapped__({"pregunta": pregunta, "datos": {"dominio": dominio}}) \
        if hasattr(orquestador.orquestar, "__wrapped__") else orquestador.orquestar(
            {"pregunta": pregunta, "datos": {"dominio": dominio}})


def test_reporte_del_18_es_de_ventas_y_no_de_la_conversacion():
    r = _orquestar("Hazme un PDF del reporte de ventas del 18")
    assert r["intencion"] == "consulta_datos" and r["analisis"] == "reporte_ventas"
    assert _orquestar("Genera el reporte PDF de la sesión")["intencion"] == "reporte"
    assert _orquestar("genera un reporte pdf", dominio="abarrotes")["intencion"] == "reporte"
