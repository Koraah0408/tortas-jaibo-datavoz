"""Lector de los reportes diarios que el POS manda por Gmail (sin Gmail: texto de ejemplo con cifras inventadas)."""

import pytest

from datavoz.basedatos import ejecutar_select
from datavoz.conectores import gmail_reportes as g

TEXTO = """Reporte Financiero de Ventas
Tortas Jaibo
Periodo del 05/03/2026 al 05/03/2026
Ingresos Brutos (Ventas Reales): $1,200.50
Ingresos Adicionales (Deuda Pagada): $100.00
Total Egresos: -$50.00
Ingresos Netos: $1,250.50
Fondo Inicial Registrado: $1000.00
Método de Pago Total
Efectivo (Local) $400.00
Tarjeta (Local) $300.00
Transferencia (Local) $100.00
Didi (App) $150.50
Rappi (App) $50.00
Crédito Empleado (Legacy) $200.00
Crédito Otorgado (Legacy): $200.00
Deuda Pagada (Legacy): $100.00
Total Ingresado en Efectivo (Ventas) $400.00
Total Ingresado por Apps $200.50
Total Ingresado (Tarjeta/Transferencia) $400.00
Total de Órdenes: 9
Ticket Promedio (Bruto): $133.39"""


def test_lee_las_cifras_del_reporte():
    r = g.parsear_reporte(TEXTO)
    assert r["fecha"] == "2026-03-05" and r["ingresos_brutos"] == 1200.5 and r["ingresos_netos"] == 1250.5
    assert r["egresos"] == 50.0 and r["fondo_inicial"] == 1000.0 and r["deuda_pagada"] == 100.0
    assert (r["efectivo"], r["tarjeta"], r["transferencia"], r["didi"], r["rappi"], r["credito"]) == \
        (400.0, 300.0, 100.0, 150.5, 50.0, 200.0)
    assert r["total_ordenes"] == 9 and r["ticket_promedio"] == 133.39 and r["total_apps"] == 200.5
    assert not any(k.startswith("Total") for k in r["metodos"])   # los totales no son métodos de pago


def test_rechaza_un_pdf_que_no_es_reporte():
    with pytest.raises(g.ErrorGmail):
        g.parsear_reporte("Factura de luz")


@pytest.fixture
def almacen_temporal(tmp_path, monkeypatch):
    monkeypatch.setattr(g, "DIR_REPORTES", tmp_path / "reportes")
    monkeypatch.setattr(g, "RUTA_DATOS", tmp_path / "reportes.json")
    monkeypatch.setattr(g, "RAIZ", tmp_path)
    monkeypatch.setattr(g, "texto_pdf", lambda contenido: contenido.decode("utf-8"))
    return tmp_path


def test_varios_envios_del_mismo_dia_gana_el_mas_reciente(almacen_temporal):
    almacen = {"reportes": {}}
    g.guardar_reporte(TEXTO.encode(), "a", "2026-03-05T20:00:00", almacen)
    corregido = TEXTO.replace("$1,200.50", "$1,300.00")
    g.guardar_reporte(corregido.encode(), "b", "2026-03-05T20:05:00", almacen)
    g.guardar_reporte(TEXTO.encode(), "c", "2026-03-05T19:00:00", almacen)   # uno más viejo no reemplaza
    assert len(almacen["reportes"]) == 1
    assert list(almacen["reportes"].values())[0]["ingresos_brutos"] == 1300.0
    assert (almacen_temporal / "reportes").exists()


def test_la_tabla_llega_a_la_copia_que_consultan_los_agentes(almacen_temporal, tmp_path):
    almacen = {"reportes": {}}
    g.guardar_reporte(TEXTO.encode(), "a", "2026-03-05T20:00:00", almacen)
    g.escribir_almacen(almacen)
    ruta = tmp_path / "copia.duckdb"
    from datavoz.basedatos import escribir_tablas
    import pandas as pd
    escribir_tablas(ruta, {"ventas": pd.DataFrame({"producto": ["Barda normal"], "cantidad": [1]})})
    assert g.agregar_a_la_copia(ruta) == 1
    r = ejecutar_select("SELECT ingresos_brutos, total_ordenes FROM reportes_diarios", str(ruta))
    assert r.ok and r.filas == [[1200.5, 9]]


def test_sin_permiso_no_intenta_conectarse(monkeypatch, tmp_path):
    monkeypatch.setattr(g, "RUTA_TOKEN", tmp_path / "no_existe.json")
    monkeypatch.delenv("GMAIL_TOKEN_JSON", raising=False)
    assert not g.configurado()
    with pytest.raises(g.ErrorGmail):
        g.sincronizar()
