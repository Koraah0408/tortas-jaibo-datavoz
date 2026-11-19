"""Acceso a DuckDB: creación de la base y ejecución de consultas de solo lectura."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import duckdb
import pandas as pd

from .config import obtener_config
from .seguridad import limpiar_sql, validar_sql
from .utilidades import a_json_serializable

_bloqueo_escritura = threading.Lock()


@dataclass
class ResultadoSQL:
    sql: str
    columnas: list[str] = field(default_factory=list)
    filas: list[list] = field(default_factory=list)
    n_filas: int = 0
    truncado: bool = False
    duracion_s: float = 0.0
    error: str | None = None
    ejecutada: bool = False  # True si la consulta llegó a ejecutarse en DuckDB

    @property
    def ok(self) -> bool:
        return self.error is None

    @property
    def vacio(self) -> bool:
        """Sin filas, o una sola fila con puros NULL (p. ej. SUM sin coincidencias)."""
        if self.n_filas == 0:
            return True
        return self.n_filas == 1 and all(v is None for v in self.filas[0])

    def a_dataframe(self) -> pd.DataFrame:
        return pd.DataFrame(self.filas, columns=self.columnas)

    def a_dict(self) -> dict:
        return {"sql": self.sql, "columnas": self.columnas, "filas": self.filas, "n_filas": self.n_filas,
                "truncado": self.truncado, "duracion_s": round(self.duracion_s, 4), "error": self.error,
                "ejecutada": self.ejecutada}

    @classmethod
    def desde_dict(cls, d: dict) -> "ResultadoSQL":
        return cls(**{k: d.get(k) for k in ("sql", "columnas", "filas", "n_filas", "truncado",
                                              "duracion_s", "error", "ejecutada") if k in d})


def conectar_lectura(ruta_db: str | Path) -> duckdb.DuckDBPyConnection:
    """Conexión de SOLO LECTURA y sin acceso a archivos externos ni extensiones."""
    return duckdb.connect(str(ruta_db), read_only=True,
                          config={"enable_external_access": False, "autoinstall_known_extensions": False,
                                  "autoload_known_extensions": False})


def tablas_y_columnas(ruta_db: str | Path) -> dict[str, list[tuple[str, str]]]:
    """Devuelve {tabla: [(columna, tipo), ...]} de la base."""
    with conectar_lectura(ruta_db) as con:
        filas = con.execute(
            "SELECT table_name, column_name, data_type FROM information_schema.columns "
            "WHERE table_schema = 'main' ORDER BY table_name, ordinal_position").fetchall()
    esquema: dict[str, list[tuple[str, str]]] = {}
    for tabla, col, tipo in filas:
        esquema.setdefault(tabla, []).append((col, tipo))
    return esquema


def describir_esquema(ruta_db: str | Path) -> str:
    """Esquema compacto para los prompts: tabla(columna TIPO, ...) y número de filas."""
    esquema = tablas_y_columnas(ruta_db)
    lineas = []
    with conectar_lectura(ruta_db) as con:
        for tabla, cols in esquema.items():
            n = con.execute(f'SELECT COUNT(*) FROM "{tabla}"').fetchone()[0]
            columnas = ", ".join(f"{c} {t}" for c, t in cols)
            lineas.append(f"- {tabla} ({n:,} filas): {columnas}")
    return "\n".join(lineas)


def ejecutar_select(sql: str, ruta_db: str | Path | None = None, timeout_s: float | None = None,
                    max_filas: int | None = None) -> ResultadoSQL:
    """Valida y ejecuta una consulta SELECT con límite de tiempo y de filas.

    Nunca lanza excepción: los errores se devuelven en ``ResultadoSQL.error``
    para que el Orquestador decida si reintentar.
    """
    cfg = obtener_config()
    ruta_db = ruta_db or cfg.ruta_db
    timeout_s = timeout_s or cfg.timeout_sql
    max_filas = max_filas or cfg.max_filas
    sql = limpiar_sql(sql)
    try:
        tablas = set(tablas_y_columnas(ruta_db))
    except Exception as e:  # base inexistente o bloqueada
        return ResultadoSQL(sql=sql, error=f"No se pudo abrir la base de datos: {e}")

    validacion = validar_sql(sql, tablas)
    if not validacion.valido:
        return ResultadoSQL(sql=sql, error=f"Consulta rechazada por seguridad: {validacion.motivo}")

    inicio = time.perf_counter()
    con = conectar_lectura(ruta_db)
    temporizador = threading.Timer(timeout_s, con.interrupt)
    temporizador.start()
    try:
        cursor = con.execute(validacion.sql)
        columnas = [d[0] for d in cursor.description] if cursor.description else []
        filas = cursor.fetchmany(max_filas + 1)
        truncado = len(filas) > max_filas
        filas = [[a_json_serializable(v) for v in f] for f in filas[:max_filas]]
        return ResultadoSQL(sql=validacion.sql, columnas=columnas, filas=filas, n_filas=len(filas),
                            truncado=truncado, duracion_s=time.perf_counter() - inicio, ejecutada=True)
    except duckdb.InterruptException:
        return ResultadoSQL(sql=validacion.sql, error=f"La consulta tardó más de {timeout_s:.0f} s y se canceló.",
                            duracion_s=time.perf_counter() - inicio, ejecutada=True)
    except duckdb.Error as e:
        mensaje = str(e).split("\n")[0]
        detalle = [ln for ln in str(e).split("\n")[1:] if ln.strip().startswith(("Candidate", "Did you mean", "LINE"))]
        return ResultadoSQL(sql=validacion.sql, error=" ".join([mensaje, *detalle])[:600],
                            duracion_s=time.perf_counter() - inicio, ejecutada=True)
    finally:
        temporizador.cancel()
        con.close()


def escribir_tablas(ruta_db: str | Path, tablas: dict[str, pd.DataFrame], reemplazar_archivo: bool = False) -> None:
    """Escribe DataFrames como tablas (CREATE OR REPLACE). Única operación de escritura del sistema."""
    ruta_db = Path(ruta_db)
    ruta_db.parent.mkdir(parents=True, exist_ok=True)
    with _bloqueo_escritura:
        if reemplazar_archivo and ruta_db.exists():
            ruta_db.unlink()
            wal = ruta_db.with_suffix(ruta_db.suffix + ".wal")
            if wal.exists():
                wal.unlink()
        con = duckdb.connect(str(ruta_db))
        try:
            for nombre, df in tablas.items():
                con.register("_tmp_df", df)
                con.execute(f'CREATE OR REPLACE TABLE "{nombre}" AS SELECT * FROM _tmp_df')
                con.unregister("_tmp_df")
            con.execute("CHECKPOINT")
        finally:
            con.close()


def resumen_ventas(ruta_db: str | Path) -> dict:
    """Datos básicos para la interfaz y la memoria (periodo, renglones, total)."""
    try:
        with conectar_lectura(ruta_db) as con:
            fila = con.execute(
                "SELECT MIN(fecha), MAX(fecha), COUNT(*), COUNT(DISTINCT producto), ROUND(SUM(total), 2) FROM ventas"
            ).fetchone()
        return {"desde": str(fila[0]), "hasta": str(fila[1]), "renglones": int(fila[2]),
                "productos": int(fila[3]), "total": float(fila[4] or 0)}
    except Exception as e:
        return {"error": str(e)}
