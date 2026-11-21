"""Alertas automáticas (nivel ideal): cada regla avisa cuando debe y calla cuando todo es normal."""

from datetime import date, timedelta

import pandas as pd

from datavoz.basedatos import escribir_tablas
from datavoz.herramientas.detectar_alertas import detectar_alertas

FIN = date(2026, 11, 15)


def _base(tmp_path, cae_producto=False, cae_semana=False, corregidas_extra=0, stock_bajo=False):
    ventas, ordenes = [], []
    for d in range(60):
        f = FIN - timedelta(days=59 - d)
        reciente = (FIN - f).days < 14
        piezas = 1 if (cae_producto and reciente) else 4
        ventas += [{"fecha": f, "producto": "Mega barda", "cantidad": piezas},
                   {"fecha": f, "producto": "Barda normal", "cantidad": 4}]
        monto = 500.0 if (cae_semana and (FIN - f).days < 7) else 1000.0
        ordenes += [{"fecha": f, "canal": "Local", "monto_total": monto, "cancelada": False}] * 3
        if (FIN - f).days < 7 and corregidas_extra:
            ordenes += [{"fecha": f, "canal": "Local", "monto_total": 0.0, "cancelada": True}]
    productos = pd.DataFrame([{"producto": "Coca cola", "stock": 3 if stock_bajo else 40, "activo": True}])
    ruta = tmp_path / "alertas.duckdb"
    escribir_tablas(ruta, {"ventas": pd.DataFrame(ventas), "ordenes": pd.DataFrame(ordenes), "productos": productos},
                    reemplazar_archivo=True)
    return str(ruta)


def test_sin_cambios_no_hay_alertas(tmp_path):
    assert detectar_alertas(_base(tmp_path)) == []


def test_avisa_caida_de_un_producto(tmp_path):
    alertas = detectar_alertas(_base(tmp_path, cae_producto=True))
    assert [a["producto"] for a in alertas if a["tipo"] == "caida_producto"] == ["Mega barda"]


def test_avisa_semana_floja_pedidos_corregidos_y_bebidas_por_acabarse(tmp_path):
    tipos = {a["tipo"] for a in detectar_alertas(_base(tmp_path, cae_semana=True, corregidas_extra=1, stock_bajo=True))}
    assert {"venta_semana", "pedidos_corregidos", "existencia_baja"} <= tipos
