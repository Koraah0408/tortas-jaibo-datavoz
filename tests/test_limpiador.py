"""Herramienta limpiar_datos contra los errores inyectados a propósito (respuesta conocida)."""

import pandas as pd

from datavoz.config import RAIZ
from datavoz.herramientas.limpiar_datos import (columnas_faltantes, limpiar_datos, mapear_columnas_heuristico,
                                                parsear_fecha, parsear_numero)
from metricas import evaluar_limpieza


def test_detecta_al_menos_90_por_ciento_de_errores(base_ejemplo):
    catalogo = pd.read_csv(RAIZ / "data" / "catalogo_productos.csv")
    r = limpiar_datos(RAIZ / "data" / "ventas_sucias.csv", catalogo=catalogo)
    m = evaluar_limpieza(r.problemas, RAIZ / "data" / "errores_inyectados.json")
    assert m["tasa_deteccion"] >= 90
    assert m["tasa_correccion"] >= 85
    assert m["falsos_positivos"] == 0


def test_datos_limpios_tienen_tipos_correctos(base_ejemplo):
    catalogo = pd.read_csv(RAIZ / "data" / "catalogo_productos.csv")
    df = limpiar_datos(RAIZ / "data" / "ventas_sucias.csv", catalogo=catalogo).datos
    assert (df["cantidad"] > 0).all()
    assert df["producto"].isin(catalogo["producto"]).all()
    assert ((df["total"] - df["cantidad"] * df["precio_unitario"]).abs() < 0.06).all()
    assert df["fecha"].notna().all()


def test_mapeo_heuristico_detecta_columnas_faltantes():
    mapeo = mapear_columnas_heuristico(["Día de venta", "Artículo vendido", "Pzas", "Precio c/u", "Cobrado"])
    assert "fecha" in columnas_faltantes(mapeo) and "producto" in columnas_faltantes(mapeo)
    assert mapeo["Pzas"] == "cantidad"


def test_parsers():
    assert str(parsear_fecha("15/03/2025")) == "2025-03-15"
    assert str(parsear_fecha("15 de marzo de 2025")) == "2025-03-15"
    assert str(parsear_fecha("5-mar-2025")) == "2025-03-05"
    assert parsear_numero("$1,234.50 MXN") == 1234.5
    assert parsear_numero("25,50") == 25.5
    assert parsear_numero("25.50 pesos") == 25.5
