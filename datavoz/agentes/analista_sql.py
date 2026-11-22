"""Agente Analista SQL: pregunta → SQL (con RAG) → ejecución de solo lectura."""

from __future__ import annotations

from ..basedatos import describir_esquema, ejecutar_select
from ..seguridad import neutralizar
from ..config import obtener_config
from ..herramientas import buscar_diccionario_tool, ejecutar_sql_tool
from ..llm import ErrorLLM, invocar_llm
from ..rag import buscar_categorias, buscar_grupos, buscar_productos
from . import prompts
from .base import EstadoDataVoz, contexto_para_prompt, nodo
from .revision_sql import revisar_semantica

_cache_productos: dict[str, list[str]] = {}
_cache_categorias: dict[str, list[str]] = {}
_cache_esquema: dict[str, str] = {}


def productos_de(ruta_db: str) -> list[str]:
    if ruta_db not in _cache_productos:
        r = ejecutar_select("SELECT DISTINCT producto FROM ventas ORDER BY producto", ruta_db, max_filas=5000)
        _cache_productos[ruta_db] = [f[0] for f in r.filas] if r.ok else []
    return _cache_productos[ruta_db]


def categorias_de(ruta_db: str) -> list[str]:
    if ruta_db not in _cache_categorias:
        r = ejecutar_select("SELECT DISTINCT categoria FROM ventas ORDER BY categoria", ruta_db, max_filas=200)
        _cache_categorias[ruta_db] = [f[0] for f in r.filas if f[0]] if r.ok else []
    return _cache_categorias[ruta_db]


def esquema_de(ruta_db: str) -> str:
    if ruta_db not in _cache_esquema:
        _cache_esquema[ruta_db] = describir_esquema(ruta_db)
    return _cache_esquema[ruta_db]


def olvidar_cache(ruta_db: str | None = None) -> None:
    if ruta_db is None:
        _cache_productos.clear()
        _cache_categorias.clear()
        _cache_esquema.clear()
    else:
        _cache_productos.pop(ruta_db, None)
        _cache_categorias.pop(ruta_db, None)
        _cache_esquema.pop(ruta_db, None)


def recuperar_contexto(pregunta: str, ruta_db: str, dominio: str = "abarrotes") -> dict:
    """RAG del negocio activo: diccionario y reglas, ejemplos pregunta–SQL y productos mencionados."""
    documentos = buscar_diccionario_tool.invoke({"consulta": pregunta, "tipos": ["diccionario", "regla"], "k": 4,
                                                 "dominio": dominio})
    ejemplos = buscar_diccionario_tool.invoke({"consulta": pregunta, "tipos": ["ejemplo"], "k": 3, "dominio": dominio})
    categorias = categorias_de(ruta_db)
    grupos = buscar_grupos(pregunta, productos_de(ruta_db), dominio)
    en_grupos = {p for g in grupos for p in g["productos"]}
    productos = [p for p in buscar_productos(pregunta, productos_de(ruta_db), categorias=categorias)
                 if p not in en_grupos]
    return {"documentos": documentos, "ejemplos": ejemplos, "productos": productos,
            "categorias": buscar_categorias(pregunta, categorias), "grupos": grupos,
            "todas_las_categorias": categorias}


def _fecha_de_hoy() -> str:
    from .orquestador import fecha_de_hoy  # importación tardía: orquestador también importa de aquí
    return fecha_de_hoy()


def construir_prompt_usuario(estado: EstadoDataVoz, rag: dict, ruta_db: str) -> str:
    datos = estado.get("datos") or {}
    resumen = datos.get("resumen") or {}
    pregunta = estado.get("pregunta_completa") or estado.get("pregunta")
    partes = [
        f"Negocio: {datos.get('negocio') or 'pequeño negocio'}.",
        f"Esquema de la base de datos (DuckDB):\n{esquema_de(ruta_db)}",
        f"Periodo disponible: del {resumen.get('desde')} al {resumen.get('hasta')}. {_fecha_de_hoy()}",
        "Diccionario de datos y reglas del negocio relevantes (RAG):\n" +
        "\n\n".join(d["texto"] for d in rag["documentos"]),
        "Ejemplos validados de pregunta → SQL (RAG):\n" + "\n\n".join(e["texto"] for e in rag["ejemplos"]),
        "Valores que existen en la columna categoria (no uses otros): " +
        (", ".join(f"'{c}'" for c in rag.get("todas_las_categorias") or []) or "(sin categorías)"),
        "Categorías que menciona la pregunta (valor exacto de la columna categoria): " +
        (", ".join(rag.get("categorias") or []) or "ninguna"),
        "Grupos de productos del negocio que menciona la pregunta (usa producto IN con estos nombres exactos): " +
        ("; ".join(f"{g['grupo']} = " + ", ".join(f"'{p}'" for p in g["productos"]) +
                   (f" ({g['nota']})" if g.get("nota") else "") for g in rag.get("grupos") or []) or "ninguno"),
        "Productos que podría mencionar la pregunta (nombres exactos; úsalos solo si la pregunta habla de ese "
        "producto en particular, no si habla de una categoría): " + ("<datos>" + ", ".join(str(neutralizar(p)) for p in rag["productos"]) + "</datos>" if rag["productos"]
         else "ninguno identificado"),
        f"Contexto de la conversación: {contexto_para_prompt(estado.get('contexto') or {})}",
    ]
    ultimo_sql = (estado.get("contexto") or {}).get("ultimo_sql")
    if estado.get("es_seguimiento") and ultimo_sql:
        partes.append(f"Consulta de la pregunta anterior (puedes adaptarla):\n{ultimo_sql}")
    intentos = estado.get("intentos_sql") or []
    if intentos:
        lineas = [f"Intento {i}: {it.get('sql') or '(vacío)'}\n  Problema: {it.get('problema')}"
                  for i, it in enumerate(intentos, 1)]
        partes.append("INTENTOS ANTERIORES QUE FALLARON (no repitas el error):\n" + "\n".join(lineas))
        if estado.get("retroalimentacion"):
            partes.append(f"Indicación del Orquestador: {estado['retroalimentacion']}")
    partes.append(f"Pregunta del usuario: {pregunta}")
    return "\n\n".join(partes)


@nodo("Analista SQL", "generar_y_ejecutar_sql")
def analista_sql(estado: EstadoDataVoz) -> dict:
    datos = estado.get("datos") or {}
    ruta_db = datos.get("ruta_db") or str(obtener_config().ruta_db)
    pregunta = estado.get("pregunta_completa") or estado.get("pregunta") or ""
    intentos = list(estado.get("intentos_sql") or [])
    sql_ejecutadas = list(estado.get("sql_ejecutadas") or [])

    rag = estado.get("contexto_rag") or {}
    if not rag:
        rag = recuperar_contexto(pregunta, ruta_db, datos.get("dominio") or "abarrotes")
    try:
        r = invocar_llm("analista_sql", prompts.ANALISTA_SQL, construir_prompt_usuario(estado, rag, ruta_db))
    except ErrorLLM as e:
        intentos.append({"sql": None, "problema": str(e), "error_llm": str(e)})
        return {"intentos_sql": intentos, "contexto_rag": rag, "resultado": {"error": str(e)},
                "_detalle": {"error_llm": str(e)}}

    sql = (r.get("sql") or "").strip()
    falta = r.get("falta_informacion")
    if not sql:
        intentos.append({"sql": None, "problema": falta or "el modelo no generó SQL", "falta_informacion": falta})
        return {"intentos_sql": intentos, "contexto_rag": rag, "sql": None, "resultado": {"error": "sin SQL"},
                "_detalle": {"falta_informacion": falta}}

    resultado = ejecutar_sql_tool.invoke({"sql": sql, "ruta_db": ruta_db})
    if resultado.get("ejecutada"):
        sql_ejecutadas.append(resultado["sql"])
    problema = resultado.get("error") or ("sin filas" if resultado.get("n_filas", 0) == 0 else None)
    intentos.append({"sql": resultado.get("sql") or sql, "problema": problema, "n_filas": resultado.get("n_filas")})

    apoyo, apoyo_descartado = [], []
    if not resultado.get("error"):
        for c in (r.get("consultas_apoyo") or [])[:2]:
            if not isinstance(c, dict) or not c.get("sql"):
                continue
            motivo = revisar_semantica(c["sql"], datos.get("tablas"))
            if motivo:  # una consulta de apoyo engañosa es peor que ninguna
                apoyo_descartado.append({"proposito": c.get("proposito", ""), "sql": c["sql"],
                                         "motivo": motivo})
                continue
            ra = ejecutar_sql_tool.invoke({"sql": c["sql"], "ruta_db": ruta_db})
            if ra.get("ejecutada"):
                sql_ejecutadas.append(ra["sql"])
            apoyo.append({"proposito": c.get("proposito", ""), **ra})

    return {
        "sql": resultado.get("sql") or sql,
        "explicacion_sql": r.get("explicacion", ""),
        "resultado": resultado,
        "consultas_apoyo": apoyo,
        "intentos_sql": intentos,
        "contexto_rag": rag,
        "sql_ejecutadas": sql_ejecutadas,
        "_detalle": {
            "intento": len(intentos),
            "rag": {"documentos": [d["titulo"] for d in rag.get("documentos", [])],
                    "ejemplos": [e["titulo"] for e in rag.get("ejemplos", [])],
                    "productos": rag.get("productos", []), "categorias": rag.get("categorias", []),
                    "grupos": [g["grupo"] for g in rag.get("grupos") or []]},
            "sql": resultado.get("sql") or sql,
            "explicacion": r.get("explicacion"),
            "error": resultado.get("error"),
            "filas": resultado.get("n_filas"),
            "consultas_apoyo": [{"proposito": a["proposito"], "sql": a.get("sql"), "error": a.get("error"),
                                 "filas": a.get("n_filas")} for a in apoyo],
            "consultas_apoyo_descartadas": apoyo_descartado,
        },
    }
