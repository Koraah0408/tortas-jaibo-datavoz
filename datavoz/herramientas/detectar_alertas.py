"""Herramienta ``detectar_alertas`` (nivel ideal): avisos automáticos para el dueño.

Reglas deterministas sobre la base activa:
  * Productos cuyas ventas semanales bajaron varias semanas seguidas.
  * Productos de alta venta con días sin existencias en las últimas 4 semanas.
"""

from __future__ import annotations

from pathlib import Path

from ..basedatos import conectar_lectura, tablas_y_columnas


def detectar_alertas(ruta_db: str | Path, semanas_bajando: int = 3, max_alertas: int = 8) -> list[dict]:
    alertas: list[dict] = []
    tablas = tablas_y_columnas(ruta_db)
    with conectar_lectura(ruta_db) as con:
        # 1) Tendencia a la baja: últimas N+1 semanas completas, ventas estrictamente decrecientes
        filas = con.execute(f"""
            WITH ult AS (SELECT MAX(fecha) AS f FROM ventas),
            sem AS (
              SELECT producto, date_trunc('week', fecha) AS sem_ini, SUM(cantidad) AS unidades
              FROM ventas, ult
              WHERE fecha > ult.f - INTERVAL {7 * (semanas_bajando + 2)} DAY
                AND date_trunc('week', fecha) + INTERVAL 6 DAY <= ult.f   -- solo semanas completas
              GROUP BY producto, sem_ini
            ),
            semanas AS (SELECT DISTINCT sem_ini FROM sem ORDER BY sem_ini DESC LIMIT {semanas_bajando + 1}),
            completo AS (
              SELECT p.producto, s.sem_ini, COALESCE(x.unidades, 0) AS unidades
              FROM (SELECT DISTINCT producto FROM sem) p CROSS JOIN semanas s
              LEFT JOIN sem x ON x.producto = p.producto AND x.sem_ini = s.sem_ini
            )
            SELECT producto, list(unidades ORDER BY sem_ini) AS serie
            FROM completo GROUP BY producto
        """).fetchall()
        for producto, serie in filas:
            if len(serie) >= semanas_bajando + 1 and serie[0] >= 4 and all(b < a for a, b in zip(serie, serie[1:])):
                caida = round(100 * (serie[0] - serie[-1]) / serie[0])
                alertas.append({"tipo": "tendencia_baja", "producto": producto,
                                "mensaje": f"{producto} lleva {semanas_bajando} semanas bajando "
                                           f"({serie[0]} → {serie[-1]} unidades por semana, −{caida} %).",
                                "serie": serie})
        # 2) Faltantes recientes en productos de alta venta
        if "inventario_diario" in tablas:
            filas = con.execute("""
                WITH ult AS (SELECT MAX(fecha) AS f FROM inventario_diario),
                top AS (SELECT producto FROM ventas GROUP BY producto ORDER BY SUM(cantidad) DESC LIMIT 40)
                SELECT i.producto, COUNT(*) AS dias
                FROM inventario_diario i, ult
                WHERE i.sin_existencia AND i.fecha > ult.f - INTERVAL 28 DAY AND i.producto IN (SELECT producto FROM top)
                GROUP BY i.producto HAVING COUNT(*) >= 2 ORDER BY dias DESC
            """).fetchall()
            for producto, dias in filas:
                alertas.append({"tipo": "faltante", "producto": producto,
                                "mensaje": f"{producto} estuvo {dias} días sin existencias en las últimas 4 semanas."})
        # 3) Caída fuerte de un producto: promedio de las 2 últimas semanas contra las 6 anteriores
        ya = {a["producto"] for a in alertas}
        filas = con.execute("""
            WITH ult AS (SELECT MAX(fecha) AS f FROM ventas)
            SELECT producto,
                   SUM(cantidad) FILTER (WHERE fecha > ult.f - INTERVAL 14 DAY) / 2.0 AS recientes,
                   SUM(cantidad) FILTER (WHERE fecha <= ult.f - INTERVAL 14 DAY AND fecha > ult.f - INTERVAL 56 DAY) / 6.0 AS antes
            FROM ventas, ult WHERE fecha > ult.f - INTERVAL 56 DAY
            GROUP BY producto HAVING antes >= 10 AND COALESCE(recientes, 0) <= antes * 0.7
            ORDER BY COALESCE(recientes, 0) / antes LIMIT 5
        """).fetchall()
        for producto, recientes, antes in filas:
            if producto in ya:
                continue
            recientes = recientes or 0
            alertas.append({"tipo": "caida_producto", "producto": producto,
                            "mensaje": f"{producto} bajó {round(100 * (1 - recientes / antes))} %: {recientes:.0f} por semana "
                                       f"en las últimas 2 semanas contra {antes:.0f} antes."})
        # 4) Negocios con órdenes (Tortas Jaibo): venta de la semana, canales y pedidos corregidos
        if "ordenes" in tablas:
            fila = con.execute("""
                WITH ult AS (SELECT MAX(fecha) AS f FROM ordenes)
                SELECT SUM(monto_total) FILTER (WHERE NOT cancelada AND fecha > ult.f - INTERVAL 7 DAY),
                       SUM(monto_total) FILTER (WHERE NOT cancelada AND fecha <= ult.f - INTERVAL 7 DAY
                                                AND fecha > ult.f - INTERVAL 14 DAY),
                       COUNT(*) FILTER (WHERE cancelada AND fecha > ult.f - INTERVAL 7 DAY),
                       COUNT(*) FILTER (WHERE cancelada AND fecha > ult.f - INTERVAL 63 DAY) / 9.0
                FROM ordenes, ult WHERE fecha > ult.f - INTERVAL 63 DAY
            """).fetchone()
            semana, anterior, corregidas, corregidas_prom = fila
            if semana is not None and anterior and semana < anterior * 0.85:
                alertas.insert(0, {"tipo": "venta_semana",
                                   "mensaje": f"Esta semana cobraste {round(100 * (1 - semana / anterior))} % menos que la "
                                              f"anterior (${semana:,.0f} contra ${anterior:,.0f})."})
            if corregidas and corregidas >= 3 and corregidas >= 2 * (corregidas_prom or 0):
                alertas.append({"tipo": "pedidos_corregidos",
                                "mensaje": f"Esta semana se corrigieron {corregidas} pedidos, el doble o más de lo normal "
                                           f"({corregidas_prom:.1f} por semana): revisa cómo se están capturando."})
            for canal, recientes, antes in con.execute("""
                WITH ult AS (SELECT MAX(fecha) AS f FROM ordenes)
                SELECT canal, COUNT(*) FILTER (WHERE fecha > ult.f - INTERVAL 14 DAY) / 2.0,
                       COUNT(*) FILTER (WHERE fecha <= ult.f - INTERVAL 14 DAY AND fecha > ult.f - INTERVAL 56 DAY) / 6.0
                FROM ordenes, ult WHERE NOT cancelada AND fecha > ult.f - INTERVAL 56 DAY
                GROUP BY canal HAVING COUNT(*) FILTER (WHERE fecha <= ult.f - INTERVAL 14 DAY
                                                       AND fecha > ult.f - INTERVAL 56 DAY) / 6.0 >= 8
            """).fetchall():
                if recientes <= antes * 0.7:
                    alertas.append({"tipo": "caida_canal", "producto": canal,
                                    "mensaje": f"Las órdenes por {canal} bajaron {round(100 * (1 - recientes / antes))} %: "
                                               f"{recientes:.0f} por semana contra {antes:.0f} antes."})
        # 5) Bebidas por acabarse (el POS guarda la existencia actual de las bebidas)
        if "productos" in tablas and any(c == "stock" for c, _ in tablas["productos"]):
            for producto, stock in con.execute("""
                SELECT producto, stock FROM productos
                WHERE stock IS NOT NULL AND stock <= 5 AND COALESCE(activo, TRUE) ORDER BY stock LIMIT 5
            """).fetchall():
                alertas.append({"tipo": "existencia_baja", "producto": producto,
                                "mensaje": f"Quedan {stock} de {producto}: conviene resurtir."})
    return alertas[:max_alertas]
