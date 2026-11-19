"""Revisión semántica del SQL (la hace el Orquestador al supervisar al Analista).

Además de los errores de ejecución, detecta consultas que corren bien pero responden mal por
errores de lógica que observamos en la evaluación. Si encuentra uno, el Orquestador regresa la
consulta al Analista con la explicación (cuenta como un reintento).
"""

from __future__ import annotations

import re

import sqlglot
from sqlglot import exp


def revisar_semantica(sql: str | None, tablas: list[str] | None = None) -> str | None:
    """Devuelve una explicación del problema o None si no se detectó ninguno.

    ``tablas``: tablas de la base activa (algunas reglas dependen del negocio, p. ej. si existe ``ordenes``)."""
    if not sql:
        return None
    s = re.sub(r"\s+", " ", sql.lower())

    # 1) Días sin existencias contados uniendo inventario con ventas por fecha (siempre da 0)
    une_por_fecha = re.search(r"\w+\.fecha\s*=\s*\w+\.fecha", s) or re.search(r"using\s*\([^)]*\bfecha\b", s)
    if "inventario_diario" in s and "sin_existencia" in s and re.search(r"\bventas\b", s) and une_por_fecha:
        return ("La consulta cuenta días sin existencias uniendo inventario_diario con ventas por fecha. Los días "
                "agotados no tienen ventas, así que esa unión siempre da 0. Cuenta los días sin existencias en "
                "inventario_diario directamente (COUNT(*) FILTER (WHERE sin_existencia)) en una consulta aparte "
                "o en una subconsulta sin unir por fecha.")

    # 2) Promedio por día de un producto/categoría dividiendo entre los días CON ventas
    divide = re.search(r"/\s*(nullif\s*\(\s*)?(count\s*\(\s*distinct|\w*dias\w*|\w+\.\w*dias\w*)", s)
    if divide and _cuenta_dias_con_filtro(sql, s):
        return ("La consulta calcula un promedio por día dividiendo entre los días en que se vendió ese producto "
                "(COUNT(DISTINCT fecha) después de filtrar productos). Un producto no se vende todos los días, así que "
                "el promedio queda inflado. Conserva el mismo filtro de productos, pero divide entre los días del "
                "periodo contados SIN filtrar productos: por ejemplo con una subconsulta o CTE que cuente "
                "COUNT(DISTINCT fecha) sobre todas las ventas u órdenes del periodo (y por día de la semana si se "
                "agrupa así), o con fecha_fin - fecha_inicio + 1 en una promoción.")

    # 3) Tortas Jaibo: dinero o ticket sacado de los renglones (ventas.total) en vez de las órdenes. Con la tabla
    #    ordenes aplica a cualquier agrupación (día, mes, canal…); sin saber las tablas, solo agrupando por canal.
    if _dinero_desde_renglones(sql, solo_por_canal=not (tablas and "ordenes" in tablas)):
        return ("La consulta calcula el dinero cobrado o el ticket promedio con ventas.total. Esa columna es el precio "
                "de cada renglón: no incluye extras, sobreprecio de las apps ni descuentos, y AVG(total) es el promedio "
                "por renglón, no por orden. Para dinero cobrado, órdenes y ticket promedio usa la tabla ordenes: "
                "SUM(monto_total), COUNT(*) y AVG(monto_total) con WHERE NOT cancelada (tiene las mismas columnas de "
                "calendario y canal). ventas.total solo sirve para comparar productos o categorías.")

    # 4) Tortas Jaibo: valores de estado que no existen ('Rehecho', '%rehacer%'…): siempre da 0
    if tablas and "ordenes" in tablas and _estado_inexistente(s):
        return ("La consulta busca palabras como 'rehacer' o 'corregido' dentro de la columna estado, pero estado solo "
                "vale 'Completada' o 'Cancelada por Modificación'. Los pedidos que se corrigieron o se tuvieron que "
                "rehacer son las órdenes canceladas por modificación: cuéntalos con COUNT(*) FROM ordenes WHERE "
                "cancelada (sin NOT cancelada).")
    return None


_ESTADOS_JAIBO = ("completada", "cancelada por modificacion", "cancelada por modificación")


def _estado_inexistente(s: str) -> bool:
    """¿La consulta compara estado con un valor que no existe en el POS de Tortas Jaibo?"""
    for operador, valor in re.findall(r"\bestado\s*(=|<>|!=|not\s+i?like|i?like)\s*'([^']*)'", s):
        if "like" in operador:
            patron = "^" + re.escape(valor).replace("%", ".*").replace("_", ".") + "$"
            if not any(re.search(patron, e) for e in _ESTADOS_JAIBO):
                return True
        elif valor not in _ESTADOS_JAIBO:
            return True
    return False


def _dinero_desde_renglones(sql: str, solo_por_canal: bool = True) -> bool:
    """SELECT sobre ventas que suma o promedia total sin filtrar ni agrupar por producto o categoría."""
    try:
        arbol = sqlglot.parse_one(sql, read="duckdb")
    except sqlglot.errors.ParseError:
        return False
    for select in arbol.find_all(exp.Select):
        def propio(nodo, select=select):
            return nodo.find_ancestor(exp.Select) is select
        tablas = {t.name.lower() for t in select.find_all(exp.Table) if propio(t)}
        agrupa = select.args.get("group")
        if "ventas" not in tablas:
            continue
        columnas_grupo = {c.name.lower() for c in agrupa.find_all(exp.Column)} if agrupa else set()
        if solo_por_canal and "canal" not in columnas_grupo:
            continue
        if columnas_grupo & {"producto", "categoria"}:
            continue  # comparar productos o categorías con ventas.total sí es correcto
        usa_total = any(propio(f) and any(c.name.lower() == "total" for c in f.find_all(exp.Column))
                        for f in select.find_all(exp.Sum, exp.Avg))
        donde = select.args.get("where")
        # solo cuenta un filtro POSITIVO de productos (=, IN, LIKE); excluir 'Interno' con <> no lo es
        filtra = donde is not None and any(
            c.name.lower() in ("producto", "categoria") and isinstance(c.parent, (exp.EQ, exp.In, exp.Like, exp.ILike))
            and not c.find_ancestor(exp.Not) for c in donde.find_all(exp.Column))
        if usa_total and not filtra:
            return True
    return False


_CUENTA_DIAS = re.compile(r"count\s*\(\s*distinct\s+(\w+\.)?fecha\s*\)")
_FILTRO_PRODUCTO = re.compile(r"\b(producto|categoria)\s*(=|in\b|ilike|like)")


def _cuenta_dias_con_filtro(sql: str, s: str) -> bool:
    """¿Algún SELECT cuenta COUNT(DISTINCT fecha) y en ese MISMO SELECT filtra productos o categorías?

    Contar los días en un CTE o subconsulta aparte, sin filtrar productos, es lo correcto y no se marca.
    Si sqlglot no puede analizar la consulta, se usa la regla por texto (más estricta).
    """
    try:
        arbol = sqlglot.parse_one(sql, read="duckdb")
    except sqlglot.errors.ParseError:
        return bool(_CUENTA_DIAS.search(s) and _FILTRO_PRODUCTO.search(s))
    for select in arbol.find_all(exp.Select):
        def propio(nodo, select=select):  # pertenece a este SELECT y no a uno anidado
            return nodo.find_ancestor(exp.Select) is select
        cuenta = any(propio(c) and isinstance(c.this, exp.Distinct) and
                     any(col.name.lower() == "fecha" for col in c.this.find_all(exp.Column))
                     for c in select.find_all(exp.Count))
        if not cuenta:
            continue
        condiciones = [select.args.get("where")] + [j.args.get("on") for j in select.args.get("joins") or []]
        for cond in filter(None, condiciones):
            if any(propio(col) and col.name.lower() in ("producto", "categoria") for col in cond.find_all(exp.Column)):
                return True
    return False
