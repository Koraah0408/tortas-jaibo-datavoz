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
    return alertas[:max_alertas]
