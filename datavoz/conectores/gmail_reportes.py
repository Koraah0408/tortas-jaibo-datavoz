"""Reportes diarios de ventas de Tortas Jaibo que se envían por Gmail.

El POS manda cada noche un correo «Reporte Financiero: DD/MM/AAAA al DD/MM/AAAA» con el PDF Reporte_Ventas.pdf
(ingresos, egresos, fondo de caja, métodos de pago, crédito y órdenes). Este módulo:

  * se conecta a Gmail con permiso de SOLO LECTURA (``gmail.readonly``) que el dueño autoriza una vez,
  * busca esos correos, descarga el PDF y lee sus cifras,
  * guarda los PDF en ``data/jaibo/reportes/`` y las cifras en ``data/jaibo/reportes.json`` (fuera de git),
  * y agrega la tabla ``reportes_diarios`` a la copia local para que los agentes respondan preguntas sobre ellos.

Autorizar (una sola vez):  python -m datavoz.conectores.gmail_reportes --autorizar   (ver docs/jaibo/GMAIL.md)
Descargar reportes:        python -m datavoz.conectores.gmail_reportes --sincronizar
"""

from __future__ import annotations

import base64
import io
import json
import os
import re
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from ..config import RAIZ

DIR_JAIBO = RAIZ / "data" / "jaibo"
DIR_REPORTES = DIR_JAIBO / "reportes"
RUTA_DATOS = DIR_JAIBO / "reportes.json"
RUTA_CLIENTE = DIR_JAIBO / "gmail_cliente.json"     # credencial OAuth (aplicación de escritorio) de Google Cloud
RUTA_TOKEN = DIR_JAIBO / "gmail_token.json"         # permiso del dueño (se crea con --autorizar)
ALCANCES = ["https://www.googleapis.com/auth/gmail.readonly"]
CONSULTA = 'subject:"Reporte Financiero" has:attachment filename:pdf'
COLUMNAS = ["fecha", "ingresos_brutos", "ingresos_netos", "egresos", "deuda_pagada", "fondo_inicial", "efectivo",
            "tarjeta", "transferencia", "didi", "rappi", "credito", "credito_otorgado", "total_apps", "total_ordenes",
            "ticket_promedio"]


class ErrorGmail(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Lectura del PDF (función pura: se prueba sin Gmail)
# ---------------------------------------------------------------------------
def texto_pdf(contenido: bytes) -> str:
    from pypdf import PdfReader
    return "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(contenido)).pages)


def _monto(texto: str, etiqueta: str) -> float | None:
    m = re.search(re.escape(etiqueta) + r"\s*:?\s*(-?)\$\s*(-?[\d,]+(?:\.\d+)?)", texto)
    if not m:
        return None
    valor = float(m.group(2).replace(",", ""))
    return -abs(valor) if m.group(1) or valor < 0 else valor


def parsear_reporte(texto: str) -> dict:
    """Cifras del «Reporte Financiero de Ventas» (un día o un periodo)."""
    periodo = re.search(r"Periodo del (\d{2}/\d{2}/\d{4}) al (\d{2}/\d{2}/\d{4})", texto)
    if not periodo:
        raise ErrorGmail("El PDF no parece un reporte financiero de Tortas Jaibo (no trae el periodo).")
    desde, hasta = (datetime.strptime(x, "%d/%m/%Y").date() for x in periodo.groups())
    metodos = {}
    for nombre, canal, monto in re.findall(r"^([A-Za-zÁÉÍÓÚáéíóúñÑ ]+?) \(([^)]+)\) \$\s*([\d,]+\.\d{2})\s*$", texto, re.M):
        if nombre.strip().lower().startswith("total"):  # «Total Ingresado …» son sumas, no métodos de pago
            continue
        metodos[f"{nombre.strip()} ({canal})"] = float(monto.replace(",", ""))

    def suma(*palabras: str) -> float:
        return round(sum(v for k, v in metodos.items() if any(p in k.lower() for p in palabras)
                         and "otorgado" not in k.lower() and "pagada" not in k.lower()), 2)

    ordenes = re.search(r"Total de Órdenes:\s*(\d+)", texto)
    credito_otorgado = sum(float(x.replace(",", "")) for x in re.findall(r"Crédito Otorgado \([^)]*\):\s*\$\s*([\d,]+\.\d{2})", texto))
    egresos = _monto(texto, "Total Egresos")
    return {"desde": desde.isoformat(), "hasta": hasta.isoformat(), "fecha": hasta.isoformat(),
            "ingresos_brutos": _monto(texto, "Ingresos Brutos (Ventas Reales)"),
            "ingresos_netos": _monto(texto, "Ingresos Netos"),
            "egresos": abs(egresos) if egresos is not None else None,
            "deuda_pagada": _monto(texto, "Ingresos Adicionales (Deuda Pagada)"),
            "fondo_inicial": _monto(texto, "Fondo Inicial Registrado"),
            "efectivo": suma("efectivo (local)"), "tarjeta": suma("tarjeta"), "transferencia": suma("transferencia"),
            "didi": suma("didi"), "rappi": suma("rappi"), "credito": suma("crédito empleado", "crédito automatas", "crédito y"),
            "credito_otorgado": round(credito_otorgado, 2),
            "total_apps": _monto(texto, "Total Ingresado por Apps"),
            "total_ordenes": int(ordenes.group(1)) if ordenes else None,
            "ticket_promedio": _monto(texto, "Ticket Promedio (Bruto)"),
            "metodos": metodos}


# ---------------------------------------------------------------------------
# Almacén local
# ---------------------------------------------------------------------------
def guardados() -> dict:
    try:
        return json.loads(RUTA_DATOS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"reportes": {}}


def guardar_reporte(contenido_pdf: bytes, id_mensaje: str, enviado: str, almacen: dict | None = None) -> dict:
    """Lee un PDF, lo guarda y registra sus cifras. Si hay varios envíos del mismo día, gana el más reciente."""
    almacen = almacen if almacen is not None else guardados()
    datos = parsear_reporte(texto_pdf(contenido_pdf))
    clave = f"{datos['desde']}_{datos['hasta']}"
    previo = almacen["reportes"].get(clave)
    if previo and previo.get("enviado", "") > enviado:
        return previo
    DIR_REPORTES.mkdir(parents=True, exist_ok=True)
    archivo = DIR_REPORTES / f"Reporte_Ventas_{clave}.pdf"
    archivo.write_bytes(contenido_pdf)
    registro = {**datos, "id_mensaje": id_mensaje, "enviado": enviado, "archivo": str(archivo.relative_to(RAIZ))}
    almacen["reportes"][clave] = registro
    return registro


def escribir_almacen(almacen: dict) -> None:
    almacen["actualizado"] = datetime.now().isoformat(timespec="seconds")
    RUTA_DATOS.parent.mkdir(parents=True, exist_ok=True)
    RUTA_DATOS.write_text(json.dumps(almacen, ensure_ascii=False, indent=1), encoding="utf-8")


def tabla_reportes(almacen: dict | None = None) -> pd.DataFrame:
    """Un renglón por día (solo reportes de un día) con las cifras principales."""
    almacen = almacen if almacen is not None else guardados()
    filas = [r for r in almacen.get("reportes", {}).values() if r.get("desde") == r.get("hasta")]
    if not filas:
        return pd.DataFrame(columns=COLUMNAS)
    df = pd.DataFrame(filas)[COLUMNAS]
    df["fecha"] = pd.to_datetime(df["fecha"]).dt.date
    return df.sort_values("fecha").reset_index(drop=True)


def agregar_a_la_copia(ruta_db: str | Path) -> int:
    """Escribe/actualiza la tabla reportes_diarios en la copia local que consultan los agentes."""
    from ..basedatos import escribir_tablas
    df = tabla_reportes()
    if df.empty or not Path(ruta_db).exists():
        return 0
    escribir_tablas(ruta_db, {"reportes_diarios": df})
    return len(df)


# ---------------------------------------------------------------------------
# Gmail (solo lectura)
# ---------------------------------------------------------------------------
def configurado() -> bool:
    return RUTA_TOKEN.exists() or bool(os.getenv("GMAIL_TOKEN_JSON"))


def _credenciales():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    if os.getenv("GMAIL_TOKEN_JSON"):          # en la nube el permiso viaja como secreto
        cred = Credentials.from_authorized_user_info(json.loads(os.environ["GMAIL_TOKEN_JSON"]), ALCANCES)
    elif RUTA_TOKEN.exists():
        cred = Credentials.from_authorized_user_file(str(RUTA_TOKEN), ALCANCES)
    else:
        raise ErrorGmail("Gmail no está conectado: corre «python -m datavoz.conectores.gmail_reportes --autorizar».")
    if not cred.valid:
        if cred.expired and cred.refresh_token:
            cred.refresh(Request())
            if RUTA_TOKEN.exists():
                RUTA_TOKEN.write_text(cred.to_json(), encoding="utf-8")
        else:
            raise ErrorGmail("El permiso de Gmail venció: vuelve a autorizar con --autorizar.")
    return cred


def autorizar() -> Path:
    """Abre el navegador para que el dueño dé permiso de solo lectura y guarda el permiso en data/jaibo/."""
    from google_auth_oauthlib.flow import InstalledAppFlow
    if not RUTA_CLIENTE.exists():
        raise ErrorGmail(f"Falta {RUTA_CLIENTE.relative_to(RAIZ)}: descárgalo de Google Cloud (docs/jaibo/GMAIL.md).")
    cred = InstalledAppFlow.from_client_secrets_file(str(RUTA_CLIENTE), ALCANCES).run_local_server(port=0)
    RUTA_TOKEN.parent.mkdir(parents=True, exist_ok=True)
    RUTA_TOKEN.write_text(cred.to_json(), encoding="utf-8")
    return RUTA_TOKEN


def sincronizar(maximo: int = 400, ruta_db: str | Path | None = None) -> dict:
    """Descarga los reportes que aún no están guardados. Devuelve cuántos nuevos y cuántos hay en total."""
    from googleapiclient.discovery import build
    try:
        servicio = build("gmail", "v1", credentials=_credenciales(), cache_discovery=False)
        almacen = guardados()
        vistos = {r.get("id_mensaje") for r in almacen["reportes"].values()}
        ids, pagina = [], None
        while len(ids) < maximo:
            r = servicio.users().messages().list(userId="me", q=CONSULTA, pageToken=pagina, maxResults=100).execute()
            ids += [m["id"] for m in r.get("messages", [])]
            pagina = r.get("nextPageToken")
            if not pagina:
                break
        nuevos = errores = 0
        for id_mensaje in ids[:maximo]:
            if id_mensaje in vistos:
                continue
            msj = servicio.users().messages().get(userId="me", id=id_mensaje).execute()
            enviado = datetime.fromtimestamp(int(msj["internalDate"]) / 1000).isoformat(timespec="seconds")
            for parte in (msj.get("payload") or {}).get("parts") or []:
                if parte.get("filename", "").lower().endswith(".pdf") and parte.get("body", {}).get("attachmentId"):
                    adj = servicio.users().messages().attachments().get(
                        userId="me", messageId=id_mensaje, id=parte["body"]["attachmentId"]).execute()
                    try:
                        guardar_reporte(base64.urlsafe_b64decode(adj["data"]), id_mensaje, enviado, almacen)
                        nuevos += 1
                    except ErrorGmail:
                        errores += 1
        escribir_almacen(almacen)
    except ErrorGmail:
        raise
    except Exception as e:  # red, permiso revocado, cuota de la API…
        raise ErrorGmail(f"No pude leer Gmail ({type(e).__name__}: {str(e)[:120]})") from e
    if ruta_db:
        agregar_a_la_copia(ruta_db)
    return {"nuevos": nuevos, "errores": errores, "total": len(tabla_reportes(almacen))}


def _main() -> int:
    import argparse
    import sys
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser(description="Reportes diarios de Tortas Jaibo desde Gmail (solo lectura)")
    p.add_argument("--autorizar", action="store_true", help="da permiso de solo lectura a Gmail (una vez)")
    p.add_argument("--sincronizar", action="store_true", help="descarga los reportes nuevos")
    a = p.parse_args()
    try:
        if a.autorizar:
            print("Permiso guardado en", autorizar())
        if a.sincronizar:
            from . import jaibo
            r = sincronizar(ruta_db=jaibo.RUTA_DB)
            print(f"Reportes nuevos: {r['nuevos']} · en total: {r['total']} días")
        if not (a.autorizar or a.sincronizar):
            p.print_help()
    except ErrorGmail as e:
        print("Error:", e)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
