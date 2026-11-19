"""Precios de referencia de insumos en Chedraui Ciudad del Carmen (catálogo público de su tienda en línea).

Cómo se obtiene el precio de la sucursal de la zona:
  1. Búsqueda pública del catálogo (``/api/catalog_system/pub/products/search``) → SKU del producto.
  2. Simulación de carrito (``/api/checkout/pub/orderForms/simulation``) con el código postal de Ciudad del
     Carmen → precio de la tienda de esa zona (puede ser distinto del precio general en línea).

No se envía ningún dato del negocio: solo el nombre del producto y el código postal. Los precios se guardan en
``data/jaibo/precios.json`` y se vuelven a consultar a los 7 días (o cuando el dueño lo pide). Son una REFERENCIA:
el precio en la tienda física o con el panadero puede ser otro, y el dueño puede fijar el suyo en costos.yaml.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

from ..config import RAIZ
from ..utilidades import normalizar

BASE = "https://www.chedraui.com.mx"
RUTA_PRECIOS = RAIZ / "data" / "jaibo" / "precios.json"
DIAS_VIGENCIA = 7
TIENDA = "Chedraui Ciudad del Carmen"
_CABECERAS = {"User-Agent": "Mozilla/5.0 (compatible; DataVoz/1.0; prototipo academico)",
              "Accept": "application/json", "Content-Type": "application/json"}


class ErrorPrecios(RuntimeError):
    pass


def _pedir(url: str, cuerpo: dict | None = None):
    datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
    req = urllib.request.Request(url, data=datos, headers=_CABECERAS, method="POST" if cuerpo is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read())
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        raise ErrorPrecios(f"no respondió la tienda en línea ({type(e).__name__})") from e


def buscar_producto(nombre: str) -> dict | None:
    """Producto del catálogo cuyo nombre coincide con ``nombre`` (exacto, o el primero que empieza igual)."""
    # el filtro de seguridad de la tienda rechaza el espacio codificado como «+»: se usa %20
    # el filtro también rechaza comillas y apóstrofos («Hellmann's»): se buscan sin ellos
    termino = re.sub(r"[\"'´`’]", "", nombre)
    resultados = _pedir(f"{BASE}/api/catalog_system/pub/products/search?"
                        + urllib.parse.urlencode({"ft": termino, "_from": 0, "_to": 19}, quote_via=urllib.parse.quote))
    candidatos = [(p, p["items"][0]) for p in resultados if p.get("items")]
    buscado = normalizar(termino)
    normalizar_sin = lambda t: normalizar(re.sub(r"[\"'´`’]", "", t))  # noqa: E731
    elegido = (next(((p, i) for p, i in candidatos if normalizar_sin(p["productName"]) == buscado), None)
               or next(((p, i) for p, i in candidatos if normalizar_sin(p["productName"]).startswith(buscado)), None))
    if elegido:
        p, item = elegido
        oferta = ((item.get("sellers") or [{}])[0].get("commertialOffer") or {})
        return {"producto": p["productName"], "sku": item["itemId"], "url": f"{BASE}/{p.get('linkText', '')}/p",
                "unidad_medida": item.get("measurementUnit") or "un", "multiplicador": float(item.get("unitMultiplier") or 1),
                "precio_en_linea": float(oferta.get("Price") or 0) or None}
    return None


def presentacion_kg(nombre: str) -> float | None:
    """Peso del paquete según su nombre: «Queso Fresco Zwan 360g» → 0.36; «Media Crema 250ml» → 0.25."""
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*(kg|g|gr|ml|l|lt)\b", nombre.lower())
    if not m:
        return None
    n = float(m.group(1).replace(",", "."))
    return n if m.group(2) in ("kg", "l", "lt") else n / 1000


def precios_chedraui(nombres: list[str], codigo_postal: str = "24180") -> dict[str, dict | None]:
    """Precio por pieza en la sucursal que surte ese código postal, para cada nombre buscado."""
    encontrados = {}
    for n in nombres:  # un producto que falle no debe tumbar a los demás
        try:
            encontrados[n] = buscar_producto(n)
        except ErrorPrecios:
            encontrados[n] = None
    skus = [p["sku"] for p in encontrados.values() if p]
    if not skus:
        return {n: None for n in nombres}
    sim = _pedir(f"{BASE}/api/checkout/pub/orderForms/simulation?sc=1",
                 {"items": [{"id": s, "quantity": 1, "seller": "1"} for s in skus],
                  "postalCode": str(codigo_postal), "country": "MEX"})
    por_sku = {it["id"]: it for it in sim.get("items") or []}
    salida = {}
    for nombre, p in encontrados.items():
        it = por_sku.get(p["sku"]) if p else None
        regional = bool(it and it.get("sellingPrice"))
        if not regional and not (p and p.get("precio_en_linea")):
            salida[nombre] = None
            continue
        if regional:
            cobro = it["sellingPrice"] / 100
        else:  # la sucursal no lo tiene en este momento: precio general en línea (ya viene por kg si es a granel)
            cobro = p["precio_en_linea"] * (p["multiplicador"] if p["unidad_medida"] == "kg" else 1)
        if p["unidad_medida"] == "kg":  # se vende a granel: el cobro es por «multiplicador» kg (p. ej. 0.15 kg)
            unidad, precio, presentacion = "kg", round(cobro / p["multiplicador"], 2), None
        else:
            presentacion = presentacion_kg(p["producto"])
            unidad, precio = ("paquete" if presentacion else "pieza"), round(cobro, 2)
        salida[nombre] = {**p, "precio": precio, "unidad": unidad, "presentacion_kg": presentacion,
                          "precio_kg": round(precio / presentacion, 2) if presentacion else (precio if unidad == "kg" else None),
                          "regional": regional, "disponible": bool(it and it.get("availability") == "available")}
    return salida


def leer_guardados() -> dict:
    try:
        return json.loads(RUTA_PRECIOS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def precios_insumos(insumos: dict[str, str], codigo_postal: str = "24180", forzar: bool = False) -> dict:
    """``insumos``: {clave: nombre a buscar}. Usa lo guardado si tiene menos de 7 días y busca lo mismo.

    Si la tienda no responde, devuelve lo guardado (aunque sea viejo) con un aviso; sin nada guardado, falla.
    """
    guardado = leer_guardados()
    edad = ((datetime.now() - datetime.fromisoformat(guardado["consultado"])).days
            if guardado.get("consultado") else None)
    mismos = all((guardado.get("productos") or {}).get(k, {}).get("buscado") == v for k, v in insumos.items())
    if (not forzar and guardado and edad is not None and edad < DIAS_VIGENCIA and mismos
            and guardado.get("codigo_postal") == str(codigo_postal)):
        return guardado
    try:
        consulta = precios_chedraui(sorted(set(insumos.values())), codigo_postal)
    except ErrorPrecios as e:
        if guardado.get("productos"):
            return {**guardado, "aviso": f"No se pudo consultar {TIENDA} ({e}); se usan los precios guardados."}
        raise
    resultado = {"consultado": datetime.now().isoformat(timespec="seconds"), "codigo_postal": str(codigo_postal),
                 "tienda": TIENDA, "productos": {k: {**(consulta.get(v) or {}), "buscado": v} for k, v in insumos.items()}}
    RUTA_PRECIOS.parent.mkdir(parents=True, exist_ok=True)
    RUTA_PRECIOS.write_text(json.dumps(resultado, ensure_ascii=False, indent=1), encoding="utf-8")
    return resultado
