"""Preparación de la base de datos de ejemplo y carga de archivos del usuario."""

from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path

import pandas as pd

from .basedatos import escribir_tablas, resumen_ventas
from .config import RAIZ, obtener_config
from .herramientas.limpiar_datos import ResultadoLimpieza, limpiar_datos

DIR_DATOS = RAIZ / "data"
ARCHIVOS_EJEMPLO = ["ventas_2025.csv", "catalogo_productos.csv", "inventario_diario.csv", "promociones.csv"]


def _generar_csv_si_faltan() -> None:
    if all((DIR_DATOS / a).exists() for a in ARCHIVOS_EJEMPLO):
        return
    spec = importlib.util.spec_from_file_location("generar_datos", RAIZ / "scripts" / "generar_datos.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    import sys
    argv = sys.argv
    sys.argv = ["generar_datos.py"]
    try:
        modulo.main()
    finally:
        sys.argv = argv


def catalogo_ejemplo() -> pd.DataFrame:
    _generar_csv_si_faltan()
    return pd.read_csv(DIR_DATOS / "catalogo_productos.csv")


def construir_base_ejemplo(ruta_db: str | Path | None = None, forzar: bool = False) -> dict:
    """Crea data/datavoz.duckdb con las 4 tablas de la tienda sintética y el índice RAG."""
    from .rag import asegurar_indice

    cfg = obtener_config()
    ruta_db = Path(ruta_db or cfg.ruta_db)
    catalogo = catalogo_ejemplo()
    if ruta_db.exists() and not forzar:
        asegurar_indice(catalogo)
        return resumen_ventas(ruta_db)

    limpieza = limpiar_datos(DIR_DATOS / "ventas_2025.csv", catalogo=catalogo)
    ventas = limpieza.datos.drop(columns=["fila_origen"])

    productos = catalogo.copy()
    productos["margen_unitario"] = (productos["precio_lista"] - productos["costo_unitario"]).round(2)
    productos["margen_pct"] = (100 * productos["margen_unitario"] / productos["precio_lista"]).round(1)

    inventario = pd.read_csv(DIR_DATOS / "inventario_diario.csv", parse_dates=["fecha"])
    inventario["fecha"] = inventario["fecha"].dt.date
    inventario["sin_existencia"] = inventario["sin_existencia"].astype(bool)
    inventario["anio"] = pd.to_datetime(inventario["fecha"]).dt.year
    inventario["mes"] = pd.to_datetime(inventario["fecha"]).dt.month

    promociones = pd.read_csv(DIR_DATOS / "promociones.csv", parse_dates=["fecha_inicio", "fecha_fin"])
    promociones["dias_duracion"] = (promociones["fecha_fin"] - promociones["fecha_inicio"]).dt.days + 1
    promociones["fecha_inicio"] = promociones["fecha_inicio"].dt.date
    promociones["fecha_fin"] = promociones["fecha_fin"].dt.date

    escribir_tablas(ruta_db, {"ventas": ventas, "productos": productos, "inventario_diario": inventario,
                              "promociones": promociones}, reemplazar_archivo=True)
    asegurar_indice(catalogo)
    return resumen_ventas(ruta_db)


def cargar_archivo_usuario(ruta_archivo: str | Path, mapeo: dict | None = None,
                           sesion_id: str | None = None) -> tuple[Path, ResultadoLimpieza]:
    """Limpia un archivo subido por el usuario y lo carga en una base propia de la sesión.

    Solo se crea la tabla ``ventas``; el catálogo de ejemplo se usa como referencia
    para normalizar nombres y completar categorías cuando los productos coinciden.
    """
    cfg = obtener_config()
    catalogo = catalogo_ejemplo()
    limpieza = limpiar_datos(ruta_archivo, mapeo=mapeo, catalogo=catalogo)
    sesion_id = sesion_id or uuid.uuid4().hex[:8]
    ruta_db = cfg.dir_sesiones / f"sesion_{sesion_id}.duckdb"
    escribir_tablas(ruta_db, {"ventas": limpieza.datos.drop(columns=["fila_origen"])}, reemplazar_archivo=True)
    return ruta_db, limpieza
