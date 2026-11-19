"""Sesiones guardadas en disco: memoria de LangGraph en SQLite + catálogo de sesiones.

Cada conversación es un ``thread_id`` del grafo. El *checkpointer* SQLite guarda el estado
completo (historial, resumen de contexto, datos activos y dashboard) al final de cada turno,
así que una sesión se puede cerrar y reabrir después. El catálogo guarda nombre y fechas para
mostrarlas en la interfaz.
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime
from pathlib import Path

from .config import obtener_config

_conexion: sqlite3.Connection | None = None
_checkpointer = None
_bloqueo = threading.Lock()


def ruta_base_sesiones() -> Path:
    cfg = obtener_config()
    cfg.dir_sesiones.mkdir(parents=True, exist_ok=True)
    return cfg.dir_sesiones / "sesiones.sqlite"


def _conectar() -> sqlite3.Connection:
    global _conexion
    if _conexion is None:
        _conexion = sqlite3.connect(str(ruta_base_sesiones()), check_same_thread=False)
        _conexion.execute("""CREATE TABLE IF NOT EXISTS catalogo_sesiones (
                               id TEXT PRIMARY KEY, nombre TEXT, creada TEXT, actualizada TEXT,
                               turnos INTEGER DEFAULT 0, origen_datos TEXT)""")
        _conexion.commit()
    return _conexion


def obtener_checkpointer():
    """Checkpointer SQLite compartido por todas las sesiones del proceso."""
    global _checkpointer
    if _checkpointer is None:
        from langgraph.checkpoint.sqlite import SqliteSaver
        _checkpointer = SqliteSaver(_conectar())
        _checkpointer.setup()
    return _checkpointer


def _ahora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def existe(sesion_id: str) -> bool:
    with _bloqueo:
        return _conectar().execute("SELECT 1 FROM catalogo_sesiones WHERE id = ?", (sesion_id,)).fetchone() is not None


def obtener(sesion_id: str) -> dict | None:
    return next((s for s in listar() if s["id"] == sesion_id), None)


def registrar_turno(sesion_id: str, turnos: int, nombre_sugerido: str = "", origen_datos: str = "") -> None:
    """Crea la entrada del catálogo en el primer turno y la actualiza en los siguientes."""
    nombre = (nombre_sugerido or "Sesión sin título").strip()
    if len(nombre) > 60:
        nombre = nombre[:57].rsplit(" ", 1)[0] + "…"
    with _bloqueo:
        con = _conectar()
        if con.execute("SELECT 1 FROM catalogo_sesiones WHERE id = ?", (sesion_id,)).fetchone():
            con.execute("UPDATE catalogo_sesiones SET actualizada = ?, turnos = ?, origen_datos = ?, "
                        "nombre = CASE WHEN nombre = 'Sesión sin título' THEN ? ELSE nombre END WHERE id = ?",
                        (_ahora(), turnos, origen_datos, nombre, sesion_id))
        else:
            con.execute("INSERT INTO catalogo_sesiones VALUES (?, ?, ?, ?, ?, ?)",
                        (sesion_id, nombre, _ahora(), _ahora(), turnos, origen_datos))
        con.commit()


def listar() -> list[dict]:
    """Sesiones guardadas, de la más reciente a la más antigua."""
    with _bloqueo:
        filas = _conectar().execute(
            "SELECT id, nombre, creada, actualizada, turnos, origen_datos FROM catalogo_sesiones "
            "ORDER BY actualizada DESC").fetchall()
    return [dict(zip(("id", "nombre", "creada", "actualizada", "turnos", "origen_datos"), f)) for f in filas]


def renombrar(sesion_id: str, nombre: str) -> None:
    nombre = nombre.strip()[:80]
    if not nombre:
        return
    with _bloqueo:
        con = _conectar()
        con.execute("UPDATE catalogo_sesiones SET nombre = ? WHERE id = ?", (nombre, sesion_id))
        con.commit()


def eliminar(sesion_id: str) -> None:
    """Borra la sesión: catálogo, memoria del grafo y la base de datos de su archivo subido."""
    obtener_checkpointer().delete_thread(sesion_id)
    with _bloqueo:
        con = _conectar()
        con.execute("DELETE FROM catalogo_sesiones WHERE id = ?", (sesion_id,))
        con.commit()
    cfg = obtener_config()
    for ruta in (cfg.dir_sesiones / f"sesion_{sesion_id}.duckdb", cfg.dir_sesiones / f"sesion_{sesion_id}.duckdb.wal"):
        if ruta.exists():
            ruta.unlink()


def reiniciar_para_pruebas() -> None:
    """Cierra la conexión (las pruebas usan una carpeta temporal)."""
    global _conexion, _checkpointer
    if _conexion is not None:
        _conexion.close()
    _conexion, _checkpointer = None, None
