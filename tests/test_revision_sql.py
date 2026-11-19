"""Revisión semántica del SQL que hace el Orquestador."""

import pytest

from datavoz.agentes.revision_sql import revisar_semantica

MALAS = [
    "SELECT v.producto, SUM(v.cantidad), COUNT(i.fecha) FILTER (WHERE i.sin_existencia) FROM ventas v "
    "LEFT JOIN inventario_diario i ON v.producto = i.producto AND v.fecha = i.fecha WHERE v.mes = 12 GROUP BY 1",
    "SELECT producto, COUNT(*) FILTER (WHERE sin_existencia) FROM ventas JOIN inventario_diario USING (producto, fecha) GROUP BY 1",
    "WITH d AS (SELECT SUM(cantidad) AS u, COUNT(DISTINCT fecha) AS dias FROM ventas WHERE producto = 'Arroz 1 kg') "
    "SELECT u / dias FROM d",
]
BUENAS = [
    "SELECT COUNT(*) FILTER (WHERE sin_existencia) FROM inventario_diario WHERE producto = 'Refresco 3 L sabor uva' AND mes = 12",
    "SELECT es_fin_de_semana, SUM(total) / COUNT(DISTINCT fecha) FROM ventas GROUP BY 1",   # toda la tienda vende diario
    "SELECT producto, COUNT(DISTINCT fecha) AS dias_con_venta FROM ventas WHERE producto ILIKE '%uva%' GROUP BY 1",
    # correcto: los días se cuentan en un CTE aparte, sin filtrar productos (antes se marcaba por error)
    "WITH dias AS (SELECT num_dia_semana, COUNT(DISTINCT fecha) AS total_dias FROM ordenes GROUP BY 1), "
    "t AS (SELECT num_dia_semana, SUM(cantidad) AS tortas FROM ventas WHERE producto IN ('Barda Mega', 'Barda Normal') "
    "GROUP BY 1) SELECT t.num_dia_semana, t.tortas * 1.0 / d.total_dias FROM t JOIN dias d USING (num_dia_semana)",
]
BUENAS += [
    "SELECT canal, SUM(monto_total), AVG(monto_total) FROM ordenes WHERE NOT cancelada GROUP BY canal",
    "SELECT canal, SUM(total) FROM ventas WHERE producto = 'Mega barda' GROUP BY canal",  # un producto: correcto
]
MALAS += [
    "SELECT canal, ROUND(SUM(total), 2), ROUND(AVG(total), 2) FROM ventas WHERE canal IN ('Local', 'Rappi') GROUP BY canal",
    "SELECT dia_semana, SUM(cantidad) / COUNT(DISTINCT fecha) FROM ventas WHERE producto IN ('Barda Mega') GROUP BY 1",
    "SELECT SUM(v.cantidad) / COUNT(DISTINCT v.fecha) FROM ventas v JOIN productos p "
    "ON v.producto = p.producto AND p.categoria = 'Bebidas'",
]


JAIBO = ["ventas", "ordenes", "productos", "promociones"]
ABARROTES = ["ventas", "productos", "inventario_diario", "promociones"]


def test_dinero_desde_renglones_solo_se_marca_en_jaibo():
    sql = "SELECT dia_semana, ROUND(SUM(total), 2) AS ventas FROM ventas GROUP BY dia_semana ORDER BY ventas DESC"
    assert revisar_semantica(sql, JAIBO)            # en Jaibo el dinero cobrado está en ordenes.monto_total
    assert revisar_semantica(sql, ABARROTES) is None  # en la tienda ventas.total es la métrica correcta
    assert revisar_semantica("SELECT producto, SUM(total) FROM ventas GROUP BY producto", JAIBO) is None
    # excluir cargos internos no es filtrar productos: sigue siendo dinero cobrado sacado de los renglones
    assert revisar_semantica("SELECT dia_semana, SUM(total) FROM ventas WHERE categoria <> 'Interno' "
                             "GROUP BY dia_semana", JAIBO)
    assert revisar_semantica("SELECT SUM(total) FROM ventas WHERE categoria = 'Bebidas'", JAIBO) is None


@pytest.mark.parametrize("sql", MALAS)
def test_detecta_errores_de_logica(sql):
    assert revisar_semantica(sql)


@pytest.mark.parametrize("sql", BUENAS)
def test_no_marca_consultas_correctas(sql):
    assert revisar_semantica(sql) is None
