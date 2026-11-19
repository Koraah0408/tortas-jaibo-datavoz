"""Tortas Jaibo: transformación de la copia del POS, RAG por negocio y grupos de productos (sin red)."""

import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from datavoz.conectores import jaibo
from datavoz.rag import buscar_grupos

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from generar_datos_jaibo import generar  # noqa: E402

DATOS_PERSONALES = {"notas", "nombre_empleado", "telefono", "id_empleado"}


@pytest.fixture(scope="module")
def crudo():
    """Dos semanas sintéticas con el menú real (mismas columnas que las vistas de solo lectura)."""
    return generar(inicio=date(2026, 3, 2), fin=date(2026, 3, 15))


@pytest.fixture(scope="module")
def tablas(crudo):
    return jaibo.transformar({k: crudo[k] for k in jaibo.VISTAS})


def _crudo_minimo():
    utc = timezone.utc
    return {
        "productos": pd.DataFrame({"id": [1, 2], "nombre": ["Barda Normal", "Coca Cola 600 ml"],
                                   "precio": [95, 30], "categoria": ["Barda", "Bebidas"], "stock": [None, 12],
                                   "es_personalizable": [True, False], "permite_guisos_extra": [True, False],
                                   "esta_activo": [True, True]}),
        "ventas": pd.DataFrame({
            # 02:30 UTC del 2 de marzo = 20:30 del 1 de marzo en Monterrey (UTC-6)
            "id": [10, 11], "fecha_hora": [datetime(2026, 3, 2, 2, 30, tzinfo=utc), datetime(2026, 3, 2, 15, 0, tzinfo=utc)],
            "monto_total": [110.0, 30.0], "metodo_pago": ["Efectivo", "Tarjeta"], "canal_venta": ["Local", "Didi"],
            "tipo_orden": ["Comer aquí", "Para llevar"], "iva": [0, 0], "total_con_iva": [110.0, 30.0],
            "estado": ["Completada", "Cancelada"], "numero_orden_dia": [1, 2]}),
        "detalle_ventas": pd.DataFrame({"id_venta": [10, 10, 11], "id_producto": [1, 2, 2], "cantidad": [1, 1, 1],
                                        "precio_unitario": [95, 30, 30]}),
        "ingredientes": pd.DataFrame({"id": [1], "nombre": ["Aguacate"], "precio_adicional": [15], "categoria": ["Extra"]}),
        "producto_ingredientes": pd.DataFrame({"id_producto": [1], "id_ingrediente": [1], "grupo": ["Extras"],
                                               "tipo_grupo": ["opcional"]}),
        "promociones": pd.DataFrame({"id": [1], "nombre": ["Torta + refresco"], "precio_promocional": [110],
                                     "esta_activa": [True]}),
        "detalle_promociones": pd.DataFrame({"id_promocion": [1, 1], "id_producto": [1, 2]}),
    }


def test_transformar_convierte_hora_local_cancelaciones_y_descuentos():
    t = jaibo.transformar(_crudo_minimo())
    o = t["ordenes"].set_index("id_orden")
    assert str(o.loc[10, "fecha"]) == "2026-03-01" and o.loc[10, "hora"] == "20:30"
    assert o.loc[10, "dia_semana"] == "domingo" and o.loc[10, "hora_del_dia"] == 20
    assert not o.loc[10, "cancelada"] and o.loc[11, "cancelada"]
    assert o.loc[10, "subtotal"] == 125.0 and o.loc[10, "descuento"] == 15.0   # promoción torta + refresco
    # las órdenes canceladas no cuentan como venta
    assert set(t["ventas"]["id_orden"]) == {10}
    assert t["ventas"]["total"].sum() == 125.0
    assert set(t["promociones"]["producto"]) == {"Barda Normal", "Coca Cola 600 ml"}
    assert t["producto_ingredientes"].iloc[0]["ingrediente"] == "Aguacate"


def test_transformar_datos_sinteticos_cuadran(crudo, tablas):
    assert set(tablas) == {"ventas", "ordenes", "productos", "ingredientes", "producto_ingredientes", "promociones"}
    o, v = tablas["ordenes"], tablas["ventas"]
    assert len(o) == len(crudo["ventas"])
    assert o["cancelada"].sum() == (crudo["ventas"]["estado"] != "Completada").sum()
    assert not v["id_orden"].isin(o.loc[o["cancelada"], "id_orden"]).any()
    por_orden = v.groupby("id_orden")["total"].sum().round(2)
    completas = o.loc[~o["cancelada"]].set_index("id_orden")["subtotal"]
    assert (por_orden.reindex(completas.index).fillna(0) - completas).abs().max() < 0.01
    assert (o["descuento"] >= 0).all() and (o["extras"] >= 0).all()
    assert ((o["subtotal"] - o["descuento"] + o["extras"]) - o["monto_total"]).abs().max() < 0.01
    # en las apps el total cobrado supera la suma de renglones (precios más altos)
    apps = o[o["canal"].isin(["Didi", "Rappi"]) & ~o["cancelada"]]
    assert (apps["extras"] > 0).mean() > 0.9
    assert v["hora_del_dia"].between(6, 23).all()
    assert set(o["tipo_orden"]) <= {"Para Llevar", "Para Aquí"}
    assert set(v["categoria"]) <= {"Principal", "Desayuno", "Del Dia", "Bebidas", "Interno"}


def test_generador_rechaza_postgres_que_no_es_local():
    from generar_datos_jaibo import cargar_postgres
    with pytest.raises(SystemExit, match="Rechazado"):
        cargar_postgres({}, "postgresql://postgres:x@aws-0-us-east-2.pooler.supabase.com:5432/postgres")


def test_copia_no_incluye_datos_personales(crudo, tablas):
    assert not {"empleados", "creditos_empleados", "pagos_deuda"} & set(tablas)
    for nombre, df in tablas.items():
        assert not DATOS_PERSONALES & set(df.columns), nombre
    # aunque la vista trajera la columna de notas, la transformación no la copia
    con_notas = {k: crudo[k] for k in jaibo.VISTAS}
    assert "notas" in crudo["detalle_ventas"].columns
    con_notas["detalle_ventas"] = crudo["detalle_ventas"]
    assert "notas" not in jaibo.transformar(con_notas)["ventas"].columns


def test_sincronizar_con_datos_dados_escribe_copia_y_resumen(tmp_path, monkeypatch, tablas, crudo):
    monkeypatch.setattr(jaibo, "DIR_JAIBO", tmp_path)
    monkeypatch.setattr(jaibo, "RUTA_DB", tmp_path / "jaibo.duckdb")
    monkeypatch.setattr(jaibo, "RUTA_ESTADO", tmp_path / "sincronizacion.json")
    r = jaibo.sincronizar(crudo={k: crudo[k] for k in jaibo.VISTAS})
    assert (tmp_path / "jaibo.duckdb").exists() and jaibo.estado()["ordenes"] == r["ordenes"] == len(tablas["ordenes"])
    assert r["origen"] == "datos proporcionados"


def test_sin_configuracion_no_intenta_conectarse(monkeypatch):
    for v in ("JAIBO_PG_HOST", "JAIBO_PG_USUARIO", "JAIBO_PG_CONTRASENA"):
        monkeypatch.delenv(v, raising=False)
    assert jaibo.configuracion() is None
    with pytest.raises(jaibo.ErrorConexionJaibo):
        jaibo.sincronizar(forzar=True)


@pytest.mark.parametrize("pregunta, grupo, n", [
    ("¿Cuántas tortas vendo cada día?", "tortas", 8),
    ("¿Cuánto pan mega necesito el sábado?", "pan mega", 4),
    ("¿Cuántos panes normales uso?", "pan normal", 4),
    ("¿Cuántas tortas de barbacoa vendo?", "tortas de barbacoa", 2),
    ("¿Cuántos kilos de barbacoa salen el domingo?", "barbacoa por peso", 1),
])
def test_grupos_de_productos(tablas, pregunta, grupo, n):
    productos = sorted(tablas["ventas"]["producto"].unique())
    grupos = buscar_grupos(pregunta, productos, "jaibo")
    assert [g["grupo"] for g in grupos] == [grupo]   # el más específico, sin grupos de más
    assert len(grupos[0]["productos"]) == n and all(p in productos for p in grupos[0]["productos"])


@pytest.mark.parametrize("pregunta", ["¿Cuántas Mega barda vendí?", "¿Cuántos tacos de barbacoa vendí el sábado?"])
def test_producto_concreto_gana_al_grupo(tablas, pregunta):
    productos = sorted(tablas["ventas"]["producto"].unique())
    assert buscar_grupos(pregunta, productos, "jaibo") == []


def test_grupo_especifico_gana_al_general(tablas):
    productos = sorted(tablas["ventas"]["producto"].unique())
    nombres = [g["grupo"] for g in buscar_grupos("¿Cuánto pan mega compro?", productos, "jaibo")]
    assert "pan mega" in nombres and "pan (todos)" not in nombres


def test_grupos_no_se_mezclan_entre_negocios(tablas):
    productos = sorted(tablas["ventas"]["producto"].unique())
    assert buscar_grupos("¿Cuántas tortas vendo?", productos, "abarrotes") == []


def test_rag_filtra_por_negocio(tmp_path):
    # índice propio en una carpeta temporal: reconstruir el índice compartido (.chroma) mientras corre la app o una
    # evaluación borraría la colección que esos procesos están usando
    from datavoz.rag import BaseConocimiento, cargar_documentos
    base = BaseConocimiento(tmp_path / "chroma")
    base.indexar(cargar_documentos())
    jaibo_docs = base.buscar("¿cuánto pan comprar para mañana?", ["diccionario", "regla"], k=4, dominio="jaibo")
    abarrotes = base.buscar("¿cuánto pan comprar para mañana?", ["diccionario", "regla"], k=4, dominio="abarrotes")
    assert jaibo_docs and abarrotes
    assert any("pan" in d["titulo"].lower() for d in jaibo_docs)
    assert not {d["titulo"] for d in jaibo_docs} & {d["titulo"] for d in abarrotes}
