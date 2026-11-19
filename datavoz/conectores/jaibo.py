"""Conector de SOLO LECTURA al POS anterior de Tortas Jaibo (Postgres en Supabase).

Diseño para no afectar la venta en producción:
  * Usa el usuario ``datavoz_lector`` (ver docs/jaibo/supabase_usuario_lectura.sql): solo puede
    leer las vistas del esquema ``datavoz`` (sin empleados, créditos ni notas), con máximo 2
    conexiones y consultas de máximo 20 s.
  * Cada sincronización abre UNA conexión, lee las vistas en una transacción de solo lectura y
    la cierra. Los agentes NUNCA consultan producción: trabajan sobre la copia local
    ``data/jaibo/jaibo.duckdb``, que se reemplaza completa en cada sincronización.
  * Hay un intervalo mínimo entre sincronizaciones (``JAIBO_SINCRONIZAR_CADA_MIN``).

Variables de entorno (.env): JAIBO_PG_HOST, JAIBO_PG_PORT, JAIBO_PG_DB, JAIBO_PG_USUARIO,
JAIBO_PG_CONTRASENA, JAIBO_PG_SSLMODE, JAIBO_SINCRONIZAR_CADA_MIN.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from ..basedatos import escribir_tablas
from ..config import RAIZ
from ..herramientas.limpiar_datos import DIAS_SEMANA, NOMBRES_MES, es_quincena

DIR_JAIBO = RAIZ / "data" / "jaibo"
RUTA_DB = DIR_JAIBO / "jaibo.duckdb"
RUTA_ESTADO = DIR_JAIBO / "sincronizacion.json"
ZONA = ZoneInfo("America/Monterrey")
VISTAS = ["ventas", "detalle_ventas", "productos", "ingredientes", "producto_ingredientes",
          "promociones", "detalle_promociones"]


class ErrorConexionJaibo(RuntimeError):
    pass


@dataclass
class ConfigJaibo:
    host: str
    usuario: str
    contrasena: str
    puerto: int = 5432
    base: str = "postgres"
    sslmode: str = "require"
    esquema: str = "datavoz"
    cada_min: float = 30.0


def configuracion() -> ConfigJaibo | None:
    """Lee la conexión del .env; None si no está configurada."""
    host, usuario, clave = (os.getenv("JAIBO_PG_HOST"), os.getenv("JAIBO_PG_USUARIO"),
                            os.getenv("JAIBO_PG_CONTRASENA"))
    if not (host and usuario and clave):
        return None
    return ConfigJaibo(host=host, usuario=usuario, contrasena=clave, puerto=int(os.getenv("JAIBO_PG_PORT", "5432")),
                       base=os.getenv("JAIBO_PG_DB", "postgres"), sslmode=os.getenv("JAIBO_PG_SSLMODE", "require"),
                       cada_min=float(os.getenv("JAIBO_SINCRONIZAR_CADA_MIN", "30")))


def estado() -> dict:
    """Resultado de la última sincronización (o {} si nunca se ha hecho)."""
    try:
        return json.loads(RUTA_ESTADO.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


# ---------------------------------------------------------------------------
# Descarga (solo lectura)
# ---------------------------------------------------------------------------
def descargar(cfg: ConfigJaibo) -> dict[str, pd.DataFrame]:
    import psycopg

    try:
        con = psycopg.connect(host=cfg.host, port=cfg.puerto, dbname=cfg.base, user=cfg.usuario,
                              password=cfg.contrasena, sslmode=cfg.sslmode, connect_timeout=15,
                              application_name="DataVoz (solo lectura)",
                              options="-c default_transaction_read_only=on -c statement_timeout=20000")
    except psycopg.Error as e:
        raise ErrorConexionJaibo(f"No se pudo conectar a la base de Tortas Jaibo: {str(e).splitlines()[0]}") from e
    crudo = {}
    try:
        with con.transaction():
            con.execute("SET TRANSACTION READ ONLY")
            for vista in VISTAS:
                cur = con.execute(f'SELECT * FROM "{cfg.esquema}"."{vista}"')
                columnas = [d.name for d in cur.description]
                crudo[vista] = pd.DataFrame(cur.fetchall(), columns=columnas)
    except psycopg.Error as e:
        raise ErrorConexionJaibo(f"Error al leer las vistas de solo lectura: {str(e).splitlines()[0]}") from e
    finally:
        con.close()
    return crudo


# ---------------------------------------------------------------------------
# Transformación al modelo de análisis de DataVoz
# ---------------------------------------------------------------------------
def _calendario(df: pd.DataFrame, columna_fecha: str = "fecha", columna_hora: str = "hora") -> pd.DataFrame:
    fechas = pd.to_datetime(df[columna_fecha])
    df["anio"] = fechas.dt.year.astype("int64")
    df["mes"] = fechas.dt.month.astype("int64")
    df["nombre_mes"] = [NOMBRES_MES[m - 1] for m in fechas.dt.month]
    df["dia"] = fechas.dt.day.astype("int64")
    df["dia_semana"] = [DIAS_SEMANA[d] for d in fechas.dt.day_of_week]
    df["num_dia_semana"] = (fechas.dt.day_of_week + 1).astype("int64")
    df["semana"] = fechas.dt.isocalendar().week.astype("int64").values
    df["trimestre"] = fechas.dt.quarter.astype("int64")
    df["hora_del_dia"] = [int(h[:2]) for h in df[columna_hora]]
    df["es_fin_de_semana"] = fechas.dt.day_of_week >= 5
    df["es_quincena"] = [es_quincena(d) for d in fechas.dt.date]
    return df


def _num(serie: pd.Series) -> pd.Series:
    return pd.to_numeric(serie, errors="coerce").astype(float).fillna(0.0)


def transformar(crudo: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """Convierte las vistas del POS en las tablas que usan los agentes (función pura, se prueba sin red)."""
    prod = crudo["productos"].copy()
    productos = pd.DataFrame({
        "id_producto": prod["id"].astype("int64"), "producto": prod["nombre"].astype(str).str.strip(),
        "categoria": prod["categoria"].fillna("Sin categoría").astype(str), "precio": _num(prod["precio"]).round(2),
        "stock": pd.to_numeric(prod["stock"], errors="coerce").astype("Int64"),
        "activo": prod["esta_activo"].fillna(True).astype(bool),
        "es_personalizable": prod["es_personalizable"].fillna(False).astype(bool),
        "permite_guisos_extra": prod["permite_guisos_extra"].fillna(False).astype(bool)})

    v = crudo["ventas"].copy()
    momento = pd.to_datetime(v["fecha_hora"], utc=True).dt.tz_convert(ZONA)
    ordenes = pd.DataFrame({
        "id_orden": v["id"].astype("int64"), "fecha": momento.dt.date, "hora": momento.dt.strftime("%H:%M"),
        "numero_orden_dia": pd.to_numeric(v["numero_orden_dia"], errors="coerce").astype("Int64"),
        "canal": v["canal_venta"].fillna("Sin canal").astype(str), "tipo_orden": v["tipo_orden"].fillna("").astype(str),
        "metodo_pago": v["metodo_pago"].fillna("").astype(str), "monto_total": _num(v["monto_total"]).round(2),
        "iva": _num(v["iva"]).round(2), "total_con_iva": _num(v["total_con_iva"]).round(2),
        "estado": v["estado"].fillna("").astype(str)})
    ordenes["cancelada"] = ~ordenes["estado"].str.lower().str.startswith("complet")

    det = crudo["detalle_ventas"].copy()
    det["cantidad"] = _num(det["cantidad"])
    det["precio_unitario"] = _num(det["precio_unitario"]).round(2)
    det = det.merge(productos[["id_producto", "producto", "categoria"]], left_on="id_producto", right_on="id_producto",
                    how="left")
    det["producto"] = det["producto"].fillna("Producto desconocido")
    det["categoria"] = det["categoria"].fillna("Sin categoría")
    det = det.merge(ordenes, left_on="id_venta", right_on="id_orden", how="inner")
    subtotal = (det.assign(t=det["cantidad"] * det["precio_unitario"]).groupby("id_orden")["t"].sum())
    ordenes["subtotal"] = ordenes["id_orden"].map(subtotal).fillna(0.0).round(2)
    # monto_total - subtotal: negativo = descuento por promoción; positivo = guisos/ingredientes extra o
    # sobreprecio de las apps (en Didi y Rappi el total suele superar la suma de renglones)
    ordenes["descuento"] = (ordenes["subtotal"] - ordenes["monto_total"]).clip(lower=0).round(2)
    ordenes["extras"] = (ordenes["monto_total"] - ordenes["subtotal"]).clip(lower=0).round(2)
    ordenes["renglones"] = ordenes["id_orden"].map(det.groupby("id_orden").size()).fillna(0).astype("int64")
    ordenes = _calendario(ordenes)

    vendidas = det[~det["cancelada"]].copy()
    vendidas = vendidas.sort_values(["fecha", "hora", "id_orden"], kind="stable").reset_index(drop=True)
    ventas = pd.DataFrame({
        "id_venta": np.arange(1, len(vendidas) + 1), "fecha": vendidas["fecha"], "hora": vendidas["hora"],
        "ticket": vendidas["id_orden"].astype(str), "id_orden": vendidas["id_orden"].astype("int64"),
        "producto": vendidas["producto"], "categoria": vendidas["categoria"],
        "cantidad": vendidas["cantidad"].round(3), "precio_unitario": vendidas["precio_unitario"],
        "total": (vendidas["cantidad"] * vendidas["precio_unitario"]).round(2),
        "canal": vendidas["canal"], "tipo_orden": vendidas["tipo_orden"], "metodo_pago": vendidas["metodo_pago"]})
    if (ventas["cantidad"] % 1 == 0).all():
        ventas["cantidad"] = ventas["cantidad"].astype("int64")
    ventas = _calendario(ventas)

    ing = crudo["ingredientes"].copy()
    ingredientes = pd.DataFrame({"id_ingrediente": ing["id"].astype("int64"), "ingrediente": ing["nombre"].astype(str),
                                 "precio_adicional": _num(ing["precio_adicional"]).round(2),
                                 "categoria": ing["categoria"].fillna("").astype(str)})
    pi = crudo["producto_ingredientes"].merge(productos[["id_producto", "producto"]], on="id_producto", how="left")
    pi = pi.merge(ingredientes, on="id_ingrediente", how="left")
    producto_ingredientes = pd.DataFrame({"producto": pi["producto"], "ingrediente": pi["ingrediente"],
                                          "grupo": pi["grupo"].fillna(""), "tipo_grupo": pi["tipo_grupo"].fillna(""),
                                          "precio_adicional": pi["precio_adicional"]})

    pr = crudo["promociones"].merge(crudo["detalle_promociones"], left_on="id", right_on="id_promocion", how="left")
    pr = pr.merge(productos[["id_producto", "producto"]], on="id_producto", how="left")
    promociones = pd.DataFrame({"promocion": pr["nombre"].astype(str), "precio_promocional": _num(pr["precio_promocional"]),
                                "activa": pr["esta_activa"].fillna(True).astype(bool), "producto": pr["producto"]})

    return {"ventas": ventas, "ordenes": ordenes, "productos": productos, "ingredientes": ingredientes,
            "producto_ingredientes": producto_ingredientes, "promociones": promociones}


# ---------------------------------------------------------------------------
# Sincronización
# ---------------------------------------------------------------------------
def sincronizar(forzar: bool = False, crudo: dict[str, pd.DataFrame] | None = None) -> dict:
    """Descarga las vistas, actualiza la copia local y devuelve un resumen.

    ``crudo`` permite pasar las tablas ya descargadas (pruebas). Si no se fuerza y la última
    sincronización fue hace menos de ``cada_min`` minutos, no vuelve a consultar producción.
    """
    cfg = configuracion()
    previo = estado()
    if crudo is None:
        if cfg is None:
            raise ErrorConexionJaibo("La conexión a Tortas Jaibo no está configurada (JAIBO_PG_* en .env).")
        if not forzar and previo.get("ultima") and RUTA_DB.exists():
            transcurrido = (datetime.now() - datetime.fromisoformat(previo["ultima"])).total_seconds() / 60
            if transcurrido < cfg.cada_min:
                return {**previo, "omitida": True, "minutos_desde_la_ultima": round(transcurrido, 1)}
    inicio = time.perf_counter()
    descargado = crudo is None
    crudo = descargar(cfg) if descargado else crudo
    tablas = transformar(crudo)
    DIR_JAIBO.mkdir(parents=True, exist_ok=True)
    temporal = RUTA_DB.with_name("jaibo_nueva.duckdb")
    escribir_tablas(temporal, tablas, reemplazar_archivo=True)
    for intento in range(10):  # en Windows el archivo puede estar abierto un instante por una consulta
        try:
            os.replace(temporal, RUTA_DB)
            break
        except PermissionError:
            time.sleep(0.3)
    else:
        raise ErrorConexionJaibo("No se pudo reemplazar la copia local (está en uso). Intenta de nuevo.")
    ordenes = tablas["ordenes"]
    resumen = {"ultima": datetime.now().isoformat(timespec="seconds"),
               "ordenes": int(len(ordenes)), "ordenes_canceladas": int(ordenes["cancelada"].sum()),
               "renglones": int(len(tablas["ventas"])), "productos": int(len(tablas["productos"])),
               "desde": str(ordenes["fecha"].min()) if len(ordenes) else None,
               "hasta": str(ordenes["fecha"].max()) if len(ordenes) else None,
               "duracion_s": round(time.perf_counter() - inicio, 2),
               "origen": f"{cfg.usuario.split('.')[0]}@{cfg.host}" if descargado else "datos proporcionados"}
    RUTA_ESTADO.write_text(json.dumps(resumen, ensure_ascii=False, indent=1), encoding="utf-8")
    try:  # los reportes diarios de Gmail no vienen del POS: se vuelven a agregar a la copia nueva
        from .gmail_reportes import agregar_a_la_copia
        agregar_a_la_copia(RUTA_DB)
    except Exception:
        pass
    return resumen


# ---------------------------------------------------------------------------
# Verificación de permisos (solo consultas de lectura al catálogo de Postgres)
# ---------------------------------------------------------------------------
_SQL_PERMISOS_PUBLIC = """
SELECT c.relname,
       has_table_privilege(c.oid, 'SELECT') AS puede_leer,
       has_table_privilege(c.oid, 'INSERT,UPDATE,DELETE,TRUNCATE') AS puede_escribir
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p', 'v', 'm')
ORDER BY c.relname
"""
_SQL_ESCRITURA_DATAVOZ = """
SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = %s AND has_table_privilege(c.oid, 'INSERT,UPDATE,DELETE,TRUNCATE')
"""


def verificar_permisos(cfg: ConfigJaibo | None = None) -> list[tuple[bool, str]]:
    """Comprueba que el usuario configurado SOLO puede leer las vistas permitidas.

    No intenta escribir nada: pregunta al catálogo de Postgres qué privilegios tiene. Devuelve
    una lista de (ok, descripción).
    """
    import psycopg

    cfg = cfg or configuracion()
    if cfg is None:
        raise ErrorConexionJaibo("La conexión a Tortas Jaibo no está configurada (JAIBO_PG_* en .env).")
    try:
        con = psycopg.connect(host=cfg.host, port=cfg.puerto, dbname=cfg.base, user=cfg.usuario,
                              password=cfg.contrasena, sslmode=cfg.sslmode, connect_timeout=15,
                              application_name="DataVoz (verificación)",
                              options="-c default_transaction_read_only=on -c statement_timeout=20000")
    except psycopg.Error as e:
        raise ErrorConexionJaibo(f"No se pudo conectar a la base de Tortas Jaibo: {str(e).splitlines()[0]}") from e
    checks: list[tuple[bool, str]] = []
    try:
        # Ajustes del ROL (no de esta conexión): así protege también a cualquier otro programa que lo use
        usuario, superusuario, privilegios, limite, ajustes = con.execute(
            "SELECT rolname, rolsuper, rolcreaterole OR rolcreatedb OR rolbypassrls OR rolreplication, "
            "rolconnlimit, COALESCE(rolconfig, '{}') FROM pg_roles WHERE rolname = current_user").fetchone()
        ajustes = dict(a.split("=", 1) for a in ajustes)
        checks.append((not superusuario and not privilegios,
                       f"conectado como «{usuario}», sin privilegios de administrador" if not superusuario and not privilegios
                       else f"«{usuario}» tiene privilegios de administrador"))
        checks.append((ajustes.get("default_transaction_read_only") == "on",
                       "el rol es de solo lectura (default_transaction_read_only = on)"
                       if ajustes.get("default_transaction_read_only") == "on"
                       else "el rol NO tiene default_transaction_read_only = on"))
        checks.append((0 < limite <= 5 and bool(ajustes.get("statement_timeout")),
                       f"límites del rol: {limite} conexiones, consultas de máximo {ajustes.get('statement_timeout', '∞')}"))
        for vista in VISTAS:
            try:
                n = con.execute(f'SELECT COUNT(*) FROM "{cfg.esquema}"."{vista}"').fetchone()[0]
                checks.append((True, f"lee {cfg.esquema}.{vista} ({n:,} filas)"))
            except psycopg.Error as e:
                con.rollback()
                checks.append((False, f"no puede leer {cfg.esquema}.{vista}: {str(e).splitlines()[0]}"))
        escribibles = [r[0] for r in con.execute(_SQL_ESCRITURA_DATAVOZ, (cfg.esquema,)).fetchall()]
        checks.append((not escribibles, "sin permiso de escritura en las vistas" if not escribibles
                       else f"PUEDE ESCRIBIR en {cfg.esquema}: {', '.join(escribibles)}"))
        public = con.execute(_SQL_PERMISOS_PUBLIC).fetchall()
        lee = [r[0] for r in public if r[1]]
        escribe = [r[0] for r in public if r[2]]
        checks.append((not lee, "sin acceso a las tablas originales (public)" if not lee
                       else f"PUEDE LEER tablas de public: {', '.join(lee)}"))
        checks.append((not escribe, "sin permiso de escritura en public" if not escribe
                       else f"PUEDE ESCRIBIR en public: {', '.join(escribe)}"))
        crear = con.execute("SELECT has_schema_privilege('public', 'CREATE')").fetchone()[0]
        checks.append((not crear, "no puede crear tablas en public" if not crear else "PUEDE CREAR tablas en public"))
    finally:
        con.close()
    return checks


def _main() -> int:
    import argparse
    import sys

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser(description="Conexión de solo lectura al POS de Tortas Jaibo")
    p.add_argument("--verificar", action="store_true", help="revisa que el usuario solo pueda leer")
    p.add_argument("--sincronizar", action="store_true", help="descarga una copia nueva a data/jaibo/")
    a = p.parse_args()
    if not (a.verificar or a.sincronizar):
        p.print_help()
        return 1
    try:
        if a.verificar:
            checks = verificar_permisos()
            for ok, texto in checks:
                print(("  OK    " if ok else "  FALLA ") + texto)
            if not all(ok for ok, _ in checks):
                print("\nHay permisos de más o faltantes: no uses esta conexión hasta corregirlo.")
                return 2
            print("\nTodo bien: el usuario solo puede leer las vistas de DataVoz.")
        if a.sincronizar:
            r = sincronizar(forzar=True)
            print(f"Copia actualizada: {r['ordenes']:,} órdenes ({r['desde']} a {r['hasta']}) en {r['duracion_s']} s")
    except ErrorConexionJaibo as e:
        print(f"Error: {e}")
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())


# ---------------------------------------------------------------------------
# Demostración sin conexión: ventas SIMULADAS con el menú y la estructura de Jaibo
# ---------------------------------------------------------------------------
RUTA_DEMO = DIR_JAIBO / "demo_sintetica.duckdb"
ORIGEN_DEMO = "Tortas Jaibo · demostración con ventas simuladas"


def asegurar_demo() -> Path:
    """Base de demostración para quien no tiene acceso al POS (p. ej. al clonar el repositorio)."""
    if not RUTA_DEMO.exists():
        import importlib.util
        spec = importlib.util.spec_from_file_location("generar_datos_jaibo", RAIZ / "scripts" / "generar_datos_jaibo.py")
        modulo = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(modulo)
        crudo = modulo.generar()
        DIR_JAIBO.mkdir(parents=True, exist_ok=True)
        escribir_tablas(RUTA_DEMO, transformar({k: crudo[k] for k in VISTAS}), reemplazar_archivo=True)
    return RUTA_DEMO
