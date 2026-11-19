"""Asesor de negocio de Tortas Jaibo: herramientas deterministas, validación de parámetros y ruta en el grafo."""

import json
import sys
from datetime import date
from pathlib import Path

import pytest

from datavoz.agentes.asesor_negocio import elegir
from datavoz.basedatos import escribir_tablas
from datavoz.conectores import jaibo
from datavoz.herramientas import negocio_jaibo as nj

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from generar_datos_jaibo import generar  # noqa: E402

HOY = date(2026, 5, 1)   # viernes; los datos sintéticos llegan al 30 de abril


def _base(tmp_path_factory, nombre, quitar_lunes=False):
    crudo = generar(inicio=date(2026, 1, 5), fin=date(2026, 4, 30))
    crudo = {k: crudo[k] for k in jaibo.VISTAS}
    if quitar_lunes:  # el negocio deja de abrir los lunes
        v = crudo["ventas"]
        lunes = v[[f.weekday() == 0 for f in v["fecha_hora"]]]["id"]
        crudo["ventas"] = v[~v["id"].isin(lunes)]
        crudo["detalle_ventas"] = crudo["detalle_ventas"][~crudo["detalle_ventas"]["id_venta"].isin(lunes)]
    ruta = tmp_path_factory.mktemp(nombre) / "jaibo.duckdb"
    escribir_tablas(ruta, jaibo.transformar(crudo), reemplazar_archivo=True)
    return str(ruta)


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    return _base(tmp_path_factory, "jaibo")


@pytest.fixture(scope="module")
def db_sin_lunes(tmp_path_factory):
    return _base(tmp_path_factory, "jaibo_sin_lunes", quitar_lunes=True)


# --------------------------------------------------------------------- fechas
@pytest.mark.parametrize("pregunta, esperadas", [
    ("¿Cuánto pan compro para mañana?", ["2026-11-19"]),
    ("¿y para el sábado?", ["2026-11-21"]),
    ("pan para el fin de semana", ["2026-11-21", "2026-11-22"]),
    ("¿cuánto pan para el 24 de noviembre?", ["2026-11-24"]),
    ("pan para esta semana", [f"2026-11-{d}" for d in range(19, 26)]),
    ("¿Cuánto pan se usa en la mañana?", []),          # «en la mañana» no es «mañana»
])
def test_fechas_de_pregunta(pregunta, esperadas):
    assert [f.isoformat() for f in nj.fechas_de_pregunta(pregunta, date(2026, 11, 18))] == esperadas


# ---------------------------------------------------------------- pronóstico
def test_pronostico_de_pan_con_error_medido(db):
    r = nj.pronosticar_pan(db, ["2026-05-02", "2026-05-03"], hoy=HOY)
    assert [f[0] for f in r["filas"]] == ["2026-05-02", "2026-05-03"]
    for f in r["filas"]:
        esperado_n, esperado_m, comprar_n, comprar_m = f[2], f[3], f[4], f[5]
        assert comprar_n >= esperado_n and comprar_m >= esperado_m and f[6] >= 4
    precision, margenes = r["apoyo"]
    assert precision["filas"][0][0].startswith("error promedio") and precision["filas"][0][1] > 0
    faltan = [f[1] for f in margenes["filas"]]
    sobran = [f[2] for f in margenes["filas"]]
    assert faltan == sorted(faltan, reverse=True) and sobran == sorted(sobran)   # más margen: menos faltantes
    assert any("SUPUESTO" in s for s in r["supuestos"])


def test_pronostico_salta_el_dia_que_no_abre(db_sin_lunes):
    r = nj.pronosticar_pan(db_sin_lunes, ["2026-05-04"], hoy=HOY)   # lunes
    assert r["filas"][0][1] == "martes"
    assert any("no abrió ningún lunes" in s for s in r["supuestos"])


def test_margen_indicado_por_el_dueno(db):
    r = nj.pronosticar_pan(db, ["2026-05-02"], margen=0.3, hoy=HOY)
    assert r["parametros"]["margen"] == 0.3 and not any("SUPUESTO" in s for s in r["supuestos"][:1])


# ------------------------------------------------------------- rentabilidad
def test_rentabilidad_por_canal(db):
    r = nj.rentabilidad_canales(db, dias=None)
    c = r["columnas"]
    filas = {f[0]: dict(zip(c, f)) for f in r["filas"]}
    rappi, local = filas["Rappi"], filas["Local"]
    assert 9 <= rappi["sobreprecio_vs_mostrador_pct"] <= 14          # el generador sube 12 % en Rappi
    assert 8 <= rappi["comision_que_cubre_el_sobreprecio_pct"] <= 12   # 1 - 1/1.12 ≈ 10.7 %
    assert rappi["comision_pct"] == 25.0 and local["comision_pct"] == 0.0
    assert local["comision_que_cubre_el_sobreprecio_pct"] is None
    assert abs(rappi["ingreso_despues_de_comision"] - rappi["venta_cobrada"] * 0.75) < 0.05
    # con 25 % de comisión y ~12 % de sobreprecio, cada pedido de Rappi deja menos que en mostrador
    assert rappi["gana_o_pierde_por_orden_vs_mostrador"] < 0 and local["gana_o_pierde_por_orden_vs_mostrador"] is None
    assert r["apoyo"][0]["filas"]


def test_comision_indicada_por_el_dueno(db):
    r = nj.rentabilidad_canales(db, comisiones={"rappi": 30})
    rappi = next(f for f in r["filas"] if f[0] == "Rappi")
    assert rappi[r["columnas"].index("comision_pct")] == 30.0
    assert any("Rappi de 30% (dato del dueño)" in s for s in r["supuestos"])


# ------------------------------------------------------------ promociones
def test_combinaciones_frecuentes(db):
    r = nj.combinaciones_frecuentes(db, dias=None)
    assert r["filas"]
    for p1, p2, juntos, pct, afinidad, promo, combinacion in r["filas"]:
        assert "Cargo Extra" not in (p1, p2) and juntos >= 10 and afinidad > 0 and promo in ("sí", "no")
        assert combinacion == f"{p1} + {p2}"
    assert r["grafica"]["x"] == "combinacion"
    assert r["apoyo"][1]["columnas"][-1] == "ordenes_por_dia"


def test_simular_promocion(db):
    r = nj.simular_promocion(db, {"mega barda": 1, "Horchata": 1}, 125)
    base = dict(r["apoyo"][0]["filas"])
    assert base["precio normal del combo"] == 140.0 and base["descuento por combo"] == 15.0
    assert [f[0] for f in r["filas"]] == [40, 50, 60]
    extra = [f[3] for f in r["filas"]]
    assert extra == sorted(extra, reverse=True)   # con más margen hacen falta menos combos extra


@pytest.mark.parametrize("productos, precio", [({"Pizza hawaiana": 1}, 100), ({"Mega barda": 1}, 0)])
def test_simular_promocion_rechaza_datos_invalidos(db, productos, precio):
    with pytest.raises(nj.ErrorAnalisis):
        nj.simular_promocion(db, productos, precio)


# ------------------------------------------------- validación de parámetros
MENU = ["Mega barda", "Horchata", "Barda normal", "Coca cola", "Coca cola cherry", "Tacos de barbacoa"]


def test_las_fechas_se_calculan_con_reglas_y_no_con_el_llm():
    h, p = elegir("pronostico_pan", "¿Cuánto pan para el sábado?",
                  {"herramienta": "pronosticar_pan", "parametros": {"fechas": ["2026-11-20"]}}, MENU, date(2026, 11, 18))
    assert h == "pronosticar_pan" and p["fechas"] == ["2026-11-21"]


def test_herramienta_fuera_del_analisis_se_corrige():
    h, _ = elegir("rentabilidad_canales", "¿Me conviene Rappi?", {"herramienta": "simular_promocion"}, MENU, date(2026, 11, 18))
    assert h == "rentabilidad_canales"


def test_simulacion_sin_llm_usa_la_pregunta():
    h, p = elegir("promociones", "¿Conviene un combo de 2 Coca cola y Mega barda a $150?", {}, MENU, date(2026, 11, 18))
    assert h == "simular_promocion" and p["productos"] == {"Mega barda": 1, "Coca cola": 2} and p["precio_promocional"] == 150


def test_producto_inventado_por_el_llm_no_se_usa():
    h, p = elegir("promociones", "¿Qué combo me recomiendas?",
                  {"herramienta": "simular_promocion",
                   "parametros": {"productos": [{"producto": "Torta cubana", "cantidad": 1}], "precio_promocional": 99}},
                  MENU, date(2026, 11, 18))
    assert h == "combinaciones_frecuentes"


def test_comision_inventada_por_el_llm_no_se_usa():
    # el dueño no dijo ninguna comisión: el 30 % que "rellena" el modelo no puede pasar como dato del dueño
    _, p = elegir("rentabilidad_canales", "¿Me conviene vender en Didi y Rappi o en mostrador?",
                  {"herramienta": "rentabilidad_canales", "parametros": {"comisiones": {"Didi": 0.3, "Rappi": 0.3}}},
                  MENU, date(2026, 11, 18))
    assert p["comisiones"] is None
    _, p = elegir("pronostico_pan", "¿Cuánto pan compro mañana?", {"parametros": {"margen": 0.2}}, MENU, date(2026, 11, 18))
    assert p["margen"] is None


def test_comision_en_porcentaje_se_convierte():
    _, p = elegir("rentabilidad_canales", "si Rappi me cobra 30%",
                  {"herramienta": "rentabilidad_canales", "parametros": {"comisiones": {"Rappi": 30}, "dias": 30}},
                  MENU, date(2026, 11, 18))
    assert p == {"dias": 30, "mes": None, "anio": None, "comisiones": {"Rappi": 0.3}}


def test_mes_de_la_pregunta_manda_sobre_los_ultimos_dias():
    _, p = elegir("rentabilidad_canales", "¿Qué tan rentable fue Rappi en octubre de 2026?",
                  {"herramienta": "rentabilidad_canales", "parametros": {"dias": 90}}, MENU, date(2026, 11, 18))
    assert (p["mes"], p["anio"], p["dias"]) == (10, 2026, None)


def test_rentabilidad_de_un_mes_concreto(db):
    r = nj.rentabilidad_canales(db, mes=3)
    assert (r["parametros"]["mes"], r["parametros"]["anio"]) == (3, 2026) and "2026-03-01 al 2026-03-31" in r["explicacion"]


# ----------------------------------------------------------- ruta en el grafo
def _llm_simulado(analisis):
    def responder(rol, sistema, usuario):
        if rol == "orquestador":
            mensaje = usuario.split("Mensaje del usuario:")[-1].strip()
            return json.dumps({"intencion": "consulta_datos", "es_seguimiento": False, "pregunta_completa": mensaje,
                               "contexto": {}, "analisis": analisis, "respuesta_directa": None})
        if rol == "asesor":
            return json.dumps({"herramienta": "pronosticar_pan", "parametros": {"fechas": None}})
        if rol == "analista_sql":
            return json.dumps({"sql": "SELECT COUNT(*) AS renglones FROM ventas", "explicacion": "conteo",
                               "consultas_apoyo": []})
        if rol == "narrador":
            return "Te conviene comprar el pan que indica la tabla.\nRecomendación: revisa la tabla cada mañana."
        return "{}"
    return responder


def test_pregunta_de_decision_va_al_asesor(db):
    from datavoz.llm import establecer_simulador
    from datavoz.sistema import SesionDataVoz
    establecer_simulador(_llm_simulado("pronostico_pan"))
    try:
        r = SesionDataVoz(ruta_db=db, dominio="jaibo", guardar_trazas=False).preguntar("¿Cuánto pan compro mañana?")
    finally:
        establecer_simulador(None)
    agentes = [p["agente"] for p in r["pasos"]]
    assert "Asesor de negocio" in agentes and "Analista SQL" not in agentes
    assert "comprar_pan_normal" in r["resultado"]["columnas"] and r["herramienta_negocio"]["nombre"] == "pronosticar_pan"
    assert r["verificacion"]["ok"] and r["consultas_apoyo"]


def test_en_jaibo_limpieza_sin_archivo_es_una_consulta(db):
    """«¿Cuántos pedidos se corrigieron?» no es limpieza de un archivo: en Jaibo no se sube ninguno."""
    from datavoz.llm import establecer_simulador
    from datavoz.sistema import SesionDataVoz

    def llm(rol, sistema, usuario):
        if rol == "orquestador":
            return json.dumps({"intencion": "limpieza_datos", "pregunta_completa": "¿Cuántos pedidos se corrigieron?",
                               "contexto": {}, "analisis": None, "respuesta_directa": None})
        if rol == "analista_sql":
            return json.dumps({"sql": "SELECT COUNT(*) AS corregidas FROM ordenes WHERE cancelada", "consultas_apoyo": []})
        return "{}" if rol != "narrador" else "Revisa la tabla.\nRecomendación: captura con cuidado."
    establecer_simulador(llm)
    try:
        r = SesionDataVoz(ruta_db=db, dominio="jaibo", guardar_trazas=False).preguntar("¿Cuántos pedidos se corrigieron?")
    finally:
        establecer_simulador(None)
    assert r["intencion"] == "consulta_datos" and r["resultado"]["columnas"] == ["corregidas"]


def test_en_abarrotes_el_analisis_se_ignora(base_ejemplo):
    from datavoz.llm import establecer_simulador
    from datavoz.sistema import SesionDataVoz
    establecer_simulador(_llm_simulado("pronostico_pan"))
    try:
        r = SesionDataVoz(ruta_db=base_ejemplo, guardar_trazas=False).preguntar("¿Cuánto pan compro mañana?")
    finally:
        establecer_simulador(None)
    agentes = [p["agente"] for p in r["pasos"]]
    assert "Analista SQL" in agentes and "Asesor de negocio" not in agentes and r["analisis"] is None
