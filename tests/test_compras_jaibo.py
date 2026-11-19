"""Lista de compras de Tortas Jaibo y precios de referencia de Chedraui (sin red: la tienda se simula)."""

import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from datavoz.agentes.asesor_negocio import elegir
from datavoz.basedatos import escribir_tablas
from datavoz.conectores import jaibo, precios
from datavoz.herramientas import negocio_jaibo as nj

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from generar_datos_jaibo import generar  # noqa: E402

HOY = date(2026, 5, 1)


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    crudo = generar(inicio=date(2026, 1, 5), fin=date(2026, 4, 30))
    ruta = tmp_path_factory.mktemp("compras") / "jaibo.duckdb"
    escribir_tablas(ruta, jaibo.transformar({k: crudo[k] for k in jaibo.VISTAS}), reemplazar_archivo=True)
    return str(ruta)


@pytest.fixture
def sin_red(monkeypatch, tmp_path):
    """Precios guardados en una carpeta temporal y la tienda «en línea» simulada."""
    monkeypatch.setattr(precios, "RUTA_PRECIOS", tmp_path / "precios.json")
    llamadas = []

    def tienda(nombres, codigo_postal="24180"):
        llamadas.append((tuple(nombres), codigo_postal))
        tabla = {"Telera": {"precio": 2.0, "unidad": "pieza"}, "Telera Doble": {"precio": 4.5, "unidad": "pieza"},
                 "Tomate Saladet por kg": {"precio": 40.0, "unidad": "kg"},
                 "Queso Fresco Zwan 360g": {"precio": 61.0, "unidad": "paquete", "presentacion_kg": 0.36}}
        return {n: {"producto": n, "sku": "1", "url": "", "disponible": True, "regional": True, **tabla[n]}
                if n in tabla else None for n in nombres}
    monkeypatch.setattr(precios, "precios_chedraui", tienda)
    return llamadas


def _costos(tmp_path, monkeypatch, normal=None, mega=None, ingredientes=""):
    ruta = tmp_path / "costos.yaml"
    ruta.write_text(
        "compras:\n  codigo_postal: '24180'\n"
        f"  pan_normal: {{buscar: Telera, precio_por_pieza: {normal if normal is not None else 'null'}}}\n"
        f"  pan_mega: {{buscar: Telera Doble, precio_por_pieza: {mega if mega is not None else 'null'}}}\n"
        + ingredientes,
        encoding="utf-8")
    monkeypatch.setenv("JAIBO_COSTOS", str(ruta))


def test_lista_de_compras_con_precios_de_la_tienda(db, sin_red, tmp_path, monkeypatch):
    _costos(tmp_path, monkeypatch)
    r = nj.lista_de_compras(db, ["2026-05-02", "2026-05-03"], hoy=HOY)
    filas = {f[0]: f for f in r["filas"]}
    normal, mega = filas["Pan normal (telera)"], filas["Pan Mega (telera doble)"]
    assert normal[3] == 2.0 and mega[3] == 4.5 and normal[2] == "piezas"
    assert normal[4] == normal[1] * 2.0 and mega[4] == mega[1] * 4.5
    resumen = dict(r["apoyo"][0]["filas"])
    assert resumen["gasto estimado total"] == pytest.approx(normal[4] + mega[4])
    assert resumen["días que cubre la compra"] == 2 and "Chedraui" in normal[5]
    assert any("Telera" in s and "SUPUESTO" in s for s in r["supuestos"])
    assert r["grafica"]["x"] == "insumo" and len(sin_red) == 1


def test_el_precio_del_dueno_manda_y_no_consulta_la_tienda(db, sin_red, tmp_path, monkeypatch):
    _costos(tmp_path, monkeypatch, normal=3.0, mega=6.0)
    r = nj.lista_de_compras(db, ["2026-05-02"], hoy=HOY)
    assert [f[3] for f in r["filas"]] == [3.0, 6.0] and all(f[5] == "precio que indicó el dueño" for f in r["filas"])
    assert sin_red == []  # no hizo falta salir a internet


def test_los_precios_se_guardan_una_semana(sin_red):
    insumos = {"pan_normal": "Telera", "pan_mega": "Telera Doble"}
    precios.precios_insumos(insumos)
    precios.precios_insumos(insumos)
    assert len(sin_red) == 1                       # la segunda vez usa lo guardado
    precios.precios_insumos(insumos, forzar=True)
    assert len(sin_red) == 2
    viejo = json.loads(precios.RUTA_PRECIOS.read_text(encoding="utf-8"))
    viejo["consultado"] = (datetime.now() - timedelta(days=8)).isoformat(timespec="seconds")
    precios.RUTA_PRECIOS.write_text(json.dumps(viejo), encoding="utf-8")
    precios.precios_insumos(insumos)
    assert len(sin_red) == 3                       # a los 7 días se vuelve a consultar


def test_si_la_tienda_no_responde_usa_lo_guardado(sin_red, monkeypatch):
    insumos = {"pan_normal": "Telera"}
    precios.precios_insumos(insumos)

    def caida(*a, **k):
        raise precios.ErrorPrecios("sin conexión")
    monkeypatch.setattr(precios, "precios_chedraui", caida)
    r = precios.precios_insumos(insumos, forzar=True)
    assert r["productos"]["pan_normal"]["precio"] == 2.0 and "precios guardados" in r["aviso"]


def test_sin_tienda_ni_precios_guardados_la_lista_avisa(db, tmp_path, monkeypatch):
    monkeypatch.setattr(precios, "RUTA_PRECIOS", tmp_path / "no_existe.json")
    monkeypatch.setattr(precios, "precios_chedraui", lambda *a, **k: (_ for _ in ()).throw(precios.ErrorPrecios("caída")))
    _costos(tmp_path, monkeypatch)
    r = nj.lista_de_compras(db, ["2026-05-02"], hoy=HOY)
    assert all(f[3] is None for f in r["filas"]) and any("No pude consultar" in s for s in r["supuestos"])


def test_el_asesor_elige_la_lista_de_compras_con_las_fechas_de_la_pregunta():
    h, p = elegir("compras", "¿Cuánto me voy a gastar en pan esta semana?", {}, ["Mega barda"], date(2026, 11, 18))
    assert h == "lista_de_compras" and len(p["fechas"]) == 7 and p["margen"] is None


INGREDIENTES = """ingredientes:
  factor_mega: 1.5
  supuesto: false
  productos:
    tomate: {nombre: Tomate, chedraui: "Tomate Saladet por kg"}
    queso_fresco: {nombre: Queso fresco, chedraui: "Queso Fresco Zwan 360g"}
  recetas:
    barda: {tomate: 40, queso_fresco: 25}
    pierna: {tomate: 40}
    mixta: {tomate: 40, queso_fresco: 25}
    barbacoa: {}
"""


def test_ingredientes_por_receta_a_granel_y_en_paquetes(db, sin_red, tmp_path, monkeypatch):
    _costos(tmp_path, monkeypatch, ingredientes=INGREDIENTES)
    r = nj.lista_de_compras(db, ["2026-05-02"], hoy=HOY)
    filas = {f[0]: f for f in r["filas"]}
    tomate, queso = filas["Tomate"], filas["Queso fresco"]
    assert tomate[2] == "kg" and tomate[4] == pytest.approx(tomate[1] * 40.0, abs=0.05)
    assert queso[2] == "paquetes de 360 g" and isinstance(queso[1], int) and queso[4] == queso[1] * 61.0
    tortas = filas["Pan normal (telera)"][1] + filas["Pan Mega (telera doble)"][1]
    assert tomate[1] <= 0.06 * tortas  # como máximo 40 g × 1.5 por torta
    resumen = dict(r["apoyo"][0]["filas"])
    assert resumen["gasto en ingredientes"] == pytest.approx(tomate[4] + queso[4], abs=0.02)
    assert not any("porciones estimadas" in s for s in r["supuestos"])  # el dueño las tomó como reales


def test_presentacion_del_paquete_sale_del_nombre():
    assert precios.presentacion_kg("Queso Fresco Zwan 360g") == 0.36
    assert precios.presentacion_kg("Media Crema Alpura 250ml") == 0.25
    assert precios.presentacion_kg("Telera") is None
