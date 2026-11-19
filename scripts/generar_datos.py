"""Generador de datos sintéticos de la tienda de abarrotes (DataVoz).

Simula un año completo (2025) de ventas de una tienda de abarrotes familiar con
~150 productos en 10 categorías, siguiendo la estructura del registro real del
cliente (una fila por producto vendido en cada ticket). Incluye patrones
realistas: fines de semana, quincenas, temporada decembrina, verano, Cuaresma,
promociones, tendencias de productos y faltantes de inventario.

Además genera:
  * ``ventas_sucias.csv`` con errores inyectados a propósito y el archivo
    ``errores_inyectados.json`` con la respuesta conocida para evaluar al
    agente Limpiador.
  * ``ventas_formato_distinto.xlsx``: el último trimestre con otros nombres de
    columna y formatos, para probar el mapeo de columnas del Limpiador.

No contiene datos personales: no hay nombres de clientes, teléfonos ni
proveedores. Todo se genera con una semilla fija para que sea reproducible.

Uso:
    python scripts/generar_datos.py            # genera todo en data/
    python scripts/generar_datos.py --semilla 7
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from faker import Faker

RAIZ = Path(__file__).resolve().parents[1]
DIR_DATOS = RAIZ / "data"

ANIO = 2025
LINEAS_POR_DIA_OBJETIVO = 41  # ~15 000 renglones de venta al año

# ---------------------------------------------------------------------------
# Catálogo: (producto, precio de lista, nivel de rotación)
# Rotación: A = alta, B = media, C = baja, D = muy baja
# ---------------------------------------------------------------------------
CATALOGO: dict[str, list[tuple[str, float, str]]] = {
    "Abarrotes": [
        ("Arroz 1 kg", 32, "A"), ("Frijol negro 1 kg", 38, "B"), ("Frijol pinto 1 kg", 40, "B"),
        ("Azúcar estándar 1 kg", 34, "A"), ("Aceite vegetal 1 L", 45, "A"), ("Harina de maíz 1 kg", 24, "B"),
        ("Harina de trigo 1 kg", 28, "C"), ("Sal de mesa 1 kg", 14, "C"), ("Pasta para sopa 200 g", 11, "A"),
        ("Pasta spaghetti 200 g", 12, "B"), ("Café soluble 120 g", 78, "B"), ("Avena 400 g", 26, "C"),
        ("Consomé de pollo 12 cubos", 24, "B"), ("Puré de tomate 210 g", 10, "A"), ("Mayonesa 390 g", 48, "C"),
    ],
    "Bebidas": [
        ("Refresco de cola 600 ml", 20, "A"), ("Refresco de cola 2 L", 38, "A"), ("Refresco de cola 3 L", 48, "B"),
        ("Refresco sabor naranja 2 L", 32, "B"), ("Refresco sabor limón 2 L", 32, "B"), ("Refresco 3 L sabor uva", 42, "C"),
        ("Agua natural 1 L", 13, "A"), ("Garrafón de agua 20 L", 40, "B"), ("Jugo de naranja 1 L", 28, "C"),
        ("Jugo de mango 250 ml", 12, "B"), ("Bebida energética 473 ml", 35, "B"), ("Agua mineral 600 ml", 18, "C"),
        ("Té helado 600 ml", 17, "C"), ("Bebida isotónica 600 ml", 22, "C"), ("Refresco de manzana 600 ml", 18, "B"),
    ],
    "Lácteos y huevo": [
        ("Leche entera 1 L", 28, "A"), ("Leche deslactosada 1 L", 30, "B"), ("Huevo blanco 12 pzas", 42, "A"),
        ("Huevo blanco 30 pzas", 98, "B"), ("Queso fresco 400 g", 65, "B"), ("Queso amarillo rebanado 200 g", 45, "C"),
        ("Crema ácida 200 ml", 24, "B"), ("Yogur bebible fresa 250 g", 14, "B"), ("Yogur natural 1 kg", 42, "C"),
        ("Mantequilla 90 g", 25, "C"), ("Leche en polvo 360 g", 85, "D"), ("Leche condensada 387 g", 32, "C"),
        ("Leche evaporada 360 g", 22, "C"), ("Jamón de pavo 250 g", 48, "B"), ("Salchicha de pavo 500 g", 45, "B"),
    ],
    "Botanas": [
        ("Papas fritas sal 45 g", 19, "A"), ("Papas fritas chile 45 g", 19, "A"), ("Totopos de maíz 200 g", 32, "C"),
        ("Cacahuates japoneses 100 g", 16, "B"), ("Cacahuates salados 100 g", 15, "C"), ("Chicharrón de harina 100 g", 14, "B"),
        ("Palomitas para microondas 3 pzas", 30, "C"), ("Frituras de maíz con queso 60 g", 17, "B"), ("Churritos picantes 60 g", 15, "B"),
        ("Semillas de girasol 50 g", 10, "C"), ("Pistaches 80 g", 35, "D"), ("Mezcla de nueces 100 g", 38, "D"),
        ("Tostadas horneadas 20 pzas", 30, "C"), ("Plátanos fritos 70 g", 16, "C"), ("Botana de habas 100 g", 18, "D"),
    ],
    "Dulces y galletas": [
        ("Galletas de animalitos 500 g", 30, "B"), ("Galletas María 170 g", 14, "B"), ("Galletas con chispas 300 g", 36, "C"),
        ("Galletas saladas 300 g", 30, "B"), ("Chocolate en barra 40 g", 16, "B"), ("Chocolate de mesa 540 g", 62, "D"),
        ("Paleta de caramelo", 3, "A"), ("Chicles de menta 10 pzas", 12, "C"), ("Gomitas 100 g", 18, "C"),
        ("Mazapán", 5, "B"), ("Malvaviscos 250 g", 28, "D"), ("Dulce de tamarindo", 4, "B"),
        ("Caramelos suaves 100 g", 15, "C"), ("Pastelito de chocolate", 18, "B"), ("Polvorones 250 g", 30, "D"),
    ],
    "Limpieza del hogar": [
        ("Detergente en polvo 1 kg", 42, "B"), ("Detergente líquido 1 L", 55, "C"), ("Jabón de barra para ropa 400 g", 22, "B"),
        ("Cloro 1 L", 18, "A"), ("Limpiador multiusos 1 L", 28, "B"), ("Suavizante de telas 850 ml", 32, "C"),
        ("Lavatrastes líquido 750 ml", 35, "B"), ("Fibra para trastes", 12, "C"), ("Escoba", 65, "D"),
        ("Trapeador", 55, "D"), ("Bolsas para basura 10 pzas", 28, "C"), ("Papel aluminio 7 m", 30, "D"),
        ("Servilletas 500 pzas", 32, "C"), ("Desinfectante en aerosol 400 ml", 75, "D"), ("Limpiador aroma pino 1 L", 30, "C"),
    ],
    "Higiene personal": [
        ("Papel higiénico 4 rollos", 38, "A"), ("Jabón de tocador 150 g", 18, "B"), ("Shampoo 400 ml", 55, "C"),
        ("Pasta dental 100 ml", 32, "B"), ("Cepillo dental", 25, "D"), ("Desodorante en barra 50 g", 52, "C"),
        ("Toallas femeninas 10 pzas", 35, "C"), ("Pañales etapa 3 14 pzas", 120, "C"), ("Papel higiénico 12 rollos", 105, "C"),
        ("Rastrillo desechable 2 pzas", 28, "D"), ("Crema corporal 400 ml", 60, "D"), ("Gel para cabello 250 g", 30, "D"),
        ("Algodón 50 g", 18, "D"), ("Toallitas húmedas 80 pzas", 45, "C"), ("Acondicionador 400 ml", 58, "D"),
    ],
    "Panadería y tortillas": [
        ("Pan blanco de caja grande", 52, "B"), ("Pan integral de caja", 58, "C"), ("Tortillas de maíz 1 kg", 24, "A"),
        ("Tortillas de harina 10 pzas", 30, "B"), ("Bolillo", 3, "A"), ("Pan dulce", 10, "A"),
        ("Medias noches 8 pzas", 40, "C"), ("Pan molido 210 g", 22, "D"), ("Tostadas de maíz 30 pzas", 35, "C"),
        ("Pan tostado 210 g", 34, "C"), ("Mantecadas 4 pzas", 28, "B"), ("Donas de chocolate 4 pzas", 38, "C"),
        ("Roles de canela 4 pzas", 40, "C"), ("Panqué de nuez", 58, "D"), ("Rosca de reyes chica", 180, "D"),
    ],
    "Enlatados y conservas": [
        ("Atún en agua 140 g", 22, "A"), ("Atún en aceite 140 g", 22, "B"), ("Sardinas en tomate 425 g", 32, "C"),
        ("Chiles jalapeños 220 g", 16, "B"), ("Elote amarillo 400 g", 24, "C"), ("Frijoles refritos 430 g", 22, "B"),
        ("Chícharos con zanahoria 400 g", 20, "C"), ("Duraznos en almíbar 820 g", 48, "D"), ("Salsa picante 150 ml", 14, "B"),
        ("Salsa verde 450 g", 30, "C"), ("Champiñones en lata 186 g", 28, "D"), ("Sopa instantánea vaso", 14, "A"),
        ("Mermelada de fresa 470 g", 40, "D"), ("Puré de papa instantáneo 125 g", 28, "D"), ("Rajas de chile poblano 220 g", 22, "D"),
    ],
    "Cervezas y vinos": [
        ("Cerveza clara lata 355 ml", 22, "A"), ("Cerveza clara 6 pack", 120, "B"), ("Cerveza clara 12 pack", 230, "C"),
        ("Cerveza clara caguama 1.2 L", 48, "A"), ("Cerveza oscura lata 355 ml", 24, "B"), ("Cerveza ligera lata 355 ml", 22, "B"),
        ("Cerveza oscura 6 pack", 130, "C"), ("Vino tinto 750 ml", 180, "D"), ("Vino blanco 750 ml", 175, "D"),
        ("Sidra 750 ml", 85, "D"), ("Brandy 700 ml", 220, "D"), ("Tequila 750 ml", 260, "D"),
        ("Ron 750 ml", 190, "D"), ("Bebida preparada lata 355 ml", 35, "C"), ("Coctel de tomate 946 ml", 48, "C"),
    ],
}

PESO_ROTACION = {"A": 3.0, "B": 1.0, "C": 0.35, "D": 0.09}

# Productos que se venden por pieza en cantidades mayores (bolillo, pan dulce...)
PRODUCTOS_A_GRANEL = {"Bolillo", "Pan dulce", "Paleta de caramelo", "Mazapán", "Dulce de tamarindo",
                      "Cerveza clara lata 355 ml", "Cerveza oscura lata 355 ml", "Cerveza ligera lata 355 ml"}

# Factor de temporada por categoría y mes (1..12)
TEMPORADA = {
    "Bebidas":               [0.9, 0.9, 1.0, 1.15, 1.3, 1.35, 1.3, 1.25, 1.05, 1.0, 0.95, 1.3],
    "Cervezas y vinos":      [0.85, 0.9, 1.0, 1.1, 1.25, 1.3, 1.25, 1.2, 1.25, 1.0, 1.0, 1.55],
    "Botanas":               [0.9, 0.95, 1.0, 1.0, 1.05, 1.1, 1.05, 1.05, 1.1, 1.05, 1.1, 1.35],
    "Dulces y galletas":     [0.9, 1.05, 0.95, 0.95, 0.95, 0.95, 0.95, 0.95, 1.0, 1.25, 1.1, 1.45],
    "Panadería y tortillas": [1.1, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.05, 1.25],
    "Enlatados y conservas": [0.9, 1.0, 1.35, 1.35, 0.95, 0.95, 0.95, 0.95, 0.95, 1.0, 1.0, 1.2],
    "Limpieza del hogar":    [1.0, 0.95, 0.95, 1.0, 1.0, 0.95, 1.0, 1.05, 1.0, 1.0, 1.0, 1.2],
}
TRAFICO_MENSUAL = [0.86, 0.92, 0.97, 1.0, 1.02, 1.0, 1.0, 1.0, 0.95, 0.98, 1.02, 1.22]
FACTOR_DIA_SEMANA = [0.9, 0.88, 0.93, 0.95, 1.1, 1.3, 1.15]  # lunes..domingo
CATEGORIAS_FIN_DE_SEMANA = {"Cervezas y vinos": 1.35, "Botanas": 1.25, "Bebidas": 1.1}

PESOS_HORA = {7: 3, 8: 6, 9: 6, 10: 5, 11: 4, 12: 4, 13: 6, 14: 6, 15: 4, 16: 4, 17: 5,
              18: 7, 19: 8, 20: 7, 21: 5, 22: 2}

PROMOCIONES = [
    # nombre, productos, inicio, fin, descuento %, factor de demanda
    ("2x1 en papas fritas", ["Papas fritas sal 45 g", "Papas fritas chile 45 g"], "2025-03-01", "2025-03-15", 50, 1.9),
    ("10% en refrescos de 2 L", ["Refresco de cola 2 L", "Refresco sabor naranja 2 L", "Refresco sabor limón 2 L"],
     "2025-05-01", "2025-05-31", 10, 1.35),
    ("3x2 en leche deslactosada", ["Leche deslactosada 1 L"], "2025-07-01", "2025-07-14", 33, 1.3),
    ("Quincena de la limpieza 15%", [p for p, _, _ in CATALOGO["Limpieza del hogar"]], "2025-08-04", "2025-08-17", 15, 1.4),
    ("Fiestas patrias: 10% en cerveza 6 pack", ["Cerveza clara 6 pack", "Cerveza oscura 6 pack"], "2025-09-12", "2025-09-16", 10, 1.7),
    ("15% en galletas de animalitos", ["Galletas de animalitos 500 g"], "2025-10-01", "2025-10-15", 15, 1.04),
    ("Navidad: 10% en sidra y vino", ["Sidra 750 ml", "Vino tinto 750 ml", "Vino blanco 750 ml"], "2025-12-15", "2025-12-24", 10, 1.6),
]

# Problemas de surtido forzados (el proveedor no entrega y el producto se agota)
FALTANTES_FORZADOS = [
    ("Refresco 3 L sabor uva", "2025-12-08", "2025-12-16"),
    ("Huevo blanco 30 pzas", "2025-04-07", "2025-04-11"),
    ("Garrafón de agua 20 L", "2025-07-21", "2025-07-23"),
    ("Pañales etapa 3 14 pzas", "2025-10-20", "2025-10-26"),
]

NOMBRES_MES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
               "septiembre", "octubre", "noviembre", "diciembre"]
ABREV_MES = [m[:3] for m in NOMBRES_MES]


@dataclass
class Producto:
    nombre: str
    categoria: str
    precio: float
    costo: float
    rotacion: str
    peso: float


def construir_catalogo(rng: np.random.Generator) -> list[Producto]:
    productos = []
    for categoria, lista in CATALOGO.items():
        for nombre, precio, rot in lista:
            margen = rng.uniform(0.15, 0.32)
            if categoria == "Cervezas y vinos":
                margen = rng.uniform(0.12, 0.22)
            costo = round(precio * (1 - margen), 2)
            peso = PESO_ROTACION[rot] * rng.uniform(0.8, 1.2)
            productos.append(Producto(nombre, categoria, float(precio), costo, rot, peso))
    assert len(productos) == 150, len(productos)
    return productos


def factor_tendencia(nombre: str, d: date) -> float:
    """Tendencias de productos a lo largo del año."""
    t = (d - date(ANIO, 1, 1)).days / 364
    if nombre == "Galletas de animalitos 500 g":
        return 1.0 - 0.7 * t                       # pierde preferencia todo el año
    if nombre == "Leche entera 1 L":
        return 1.1 - 0.3 * t
    if nombre == "Leche deslactosada 1 L":
        return 0.8 + 0.6 * t
    if nombre == "Pan integral de caja":
        return 0.7 + 0.8 * t
    if nombre == "Bebida energética 473 ml":       # producto nuevo desde junio
        return 0.0 if d < date(ANIO, 6, 1) else 0.6 + 1.2 * (d - date(ANIO, 6, 1)).days / 213
    if nombre == "Refresco sabor limón 2 L":       # cae en el último trimestre
        return 1.0 if d < date(ANIO, 9, 15) else max(0.25, 1.0 - (d - date(ANIO, 9, 15)).days / 110)
    if nombre == "Rosca de reyes chica":           # solo se vende en temporada
        if date(ANIO, 1, 1) <= d <= date(ANIO, 1, 6):
            return 60.0
        if d >= date(ANIO, 12, 26):
            return 8.0
        return 0.0
    if nombre in ("Atún en agua 140 g", "Sardinas en tomate 425 g", "Atún en aceite 140 g"):
        return 1.5 if date(ANIO, 3, 5) <= d <= date(ANIO, 4, 18) else 1.0   # Cuaresma
    if nombre in ("Chocolate de mesa 540 g", "Duraznos en almíbar 820 g", "Sidra 750 ml", "Malvaviscos 250 g"):
        return 4.0 if d.month == 12 else 1.0
    if nombre == "Mazapán" and d.month == 10:
        return 1.6
    return 1.0


def es_quincena(d: date) -> bool:
    ultimo = (date(d.year + (d.month == 12), d.month % 12 + 1, 1) - timedelta(days=1)).day
    return d.day in (15, 16, 17) or d.day >= ultimo - 1 or d.day <= 2


def cantidad_aleatoria(rng: np.random.Generator, prod: Producto, promo_desc: float) -> int:
    if prod.nombre in PRODUCTOS_A_GRANEL:
        q = int(rng.choice([1, 2, 3, 4, 5, 6, 8, 10], p=[0.2, 0.22, 0.18, 0.14, 0.1, 0.08, 0.05, 0.03]))
    else:
        q = int(rng.choice([1, 2, 3, 4], p=[0.76, 0.17, 0.05, 0.02]))
    if promo_desc >= 50:          # 2x1: se llevan en pares
        q = max(2, q + (q % 2))
    elif promo_desc >= 33 and q < 3 and rng.random() < 0.5:  # 3x2
        q = 3
    return q


def simular(semilla: int = 42) -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(semilla)
    productos = construir_catalogo(rng)
    idx = {p.nombre: i for i, p in enumerate(productos)}
    n = len(productos)
    pesos_base = np.array([p.peso for p in productos])
    pesos_base = pesos_base / pesos_base.sum()

    # Promociones por día
    promo_por_producto: dict[int, list[tuple[date, date, str, float, float]]] = {}
    filas_promos = []
    for nombre, prods, ini, fin, desc, fac in PROMOCIONES:
        di, df_ = date.fromisoformat(ini), date.fromisoformat(fin)
        for p in prods:
            promo_por_producto.setdefault(idx[p], []).append((di, df_, nombre, desc, fac))
            filas_promos.append({"promocion": nombre, "producto": p, "categoria": productos[idx[p]].categoria,
                                 "fecha_inicio": di, "fecha_fin": df_, "descuento_pct": desc})

    faltantes = {(idx[p], date.fromisoformat(a) + timedelta(days=k))
                 for p, a, b in FALTANTES_FORZADOS
                 for k in range((date.fromisoformat(b) - date.fromisoformat(a)).days + 1)}

    # Demanda esperada en unidades/día para dimensionar el inventario
    unidades_prom = np.array([2.6 if p.nombre in PRODUCTOS_A_GRANEL else 1.33 for p in productos])
    demanda_dia = pesos_base * LINEAS_POR_DIA_OBJETIVO * unidades_prom * 1.25
    stock_max = np.ceil(demanda_dia * 6 * 1.6 + 3).astype(int)
    stock = stock_max.copy()

    horas = np.array(list(PESOS_HORA.keys()))
    p_horas = np.array(list(PESOS_HORA.values()), dtype=float)
    p_horas /= p_horas.sum()
    tamanos_ticket = np.array([1, 2, 3, 4, 5])
    p_tamanos = np.array([0.55, 0.25, 0.12, 0.05, 0.03])
    lineas_por_ticket = float((tamanos_ticket * p_tamanos).sum())

    ventas, inventario = [], []
    num_ticket = 0
    d = date(ANIO, 1, 1)
    while d.year == ANIO:
        dow = d.weekday()
        # Resurtido lunes y jueves (salvo faltante forzado)
        entradas = np.zeros(n, dtype=int)
        if dow in (0, 3):
            for i in range(n):
                if (i, d) not in faltantes and stock[i] < stock_max[i]:
                    entradas[i] = stock_max[i] - stock[i]
            stock = stock + entradas
        for i in range(n):            # el faltante forzado deja el producto en cero
            if (i, d) in faltantes:
                stock[i] = 0
        stock_inicial = stock - entradas
        vendidas = np.zeros(n, dtype=int)

        trafico = TRAFICO_MENSUAL[d.month - 1] * FACTOR_DIA_SEMANA[dow] * (1.2 if es_quincena(d) else 1.0)
        if d.month == 12 and d.day >= 15:
            trafico *= 1.15
        n_tickets = rng.poisson(LINEAS_POR_DIA_OBJETIVO / lineas_por_ticket * trafico / 1.02)

        pesos_dia = pesos_base.copy()
        promo_hoy: dict[int, tuple[str, float]] = {}
        for i, p in enumerate(productos):
            f = TEMPORADA.get(p.categoria, [1.0] * 12)[d.month - 1] * factor_tendencia(p.nombre, d)
            if dow >= 4:
                f *= CATEGORIAS_FIN_DE_SEMANA.get(p.categoria, 1.0)
            for di, df_, nombre, desc, fac in promo_por_producto.get(i, []):
                if di <= d <= df_:
                    f *= fac
                    promo_hoy[i] = (nombre, desc)
            pesos_dia[i] *= f

        for _ in range(n_tickets):
            num_ticket += 1
            tam = int(rng.choice(tamanos_ticket, p=p_tamanos))
            hora = int(rng.choice(horas, p=p_horas))
            minuto = int(rng.integers(0, 60))
            disponibles = pesos_dia * (stock > 0)
            if disponibles.sum() <= 0:
                continue
            elegidos = rng.choice(n, size=min(tam, int((disponibles > 0).sum())), replace=False,
                                  p=disponibles / disponibles.sum())
            lineas = []
            for i in elegidos:
                p = productos[i]
                nombre_promo, desc = promo_hoy.get(i, (None, 0.0))
                q = min(cantidad_aleatoria(rng, p, desc), int(stock[i]))
                if q <= 0:
                    continue
                precio = round(p.precio * (1 - desc / 100) * 2) / 2 if desc else p.precio
                stock[i] -= q
                vendidas[i] += q
                lineas.append((p, q, precio, nombre_promo))
            if not lineas:
                continue
            total_ticket = sum(q * pr for _, q, pr, _ in lineas)
            if total_ticket > 300:
                pago = rng.choice(["efectivo", "tarjeta", "transferencia"], p=[0.4, 0.42, 0.18])
            else:
                pago = rng.choice(["efectivo", "tarjeta", "transferencia"], p=[0.66, 0.22, 0.12])
            for p, q, precio, nombre_promo in lineas:
                ventas.append({
                    "fecha": d, "hora": f"{hora:02d}:{minuto:02d}", "ticket": f"T{num_ticket:06d}",
                    "producto": p.nombre, "categoria": p.categoria, "cantidad": q,
                    "precio_unitario": precio, "total": round(q * precio, 2),
                    "metodo_pago": str(pago), "promocion": nombre_promo or "",
                })

        for i, p in enumerate(productos):
            inventario.append({"fecha": d, "producto": p.nombre, "categoria": p.categoria,
                               "existencia_inicial": int(stock_inicial[i]), "entradas": int(entradas[i]),
                               "unidades_vendidas": int(vendidas[i]), "existencia_final": int(stock[i]),
                               "sin_existencia": bool(stock[i] == 0)})
        d += timedelta(days=1)

    ventas_df = pd.DataFrame(ventas).sort_values(["fecha", "hora", "ticket"]).reset_index(drop=True)
    catalogo_df = pd.DataFrame([{"producto": p.nombre, "categoria": p.categoria, "precio_lista": p.precio,
                                 "costo_unitario": p.costo} for p in productos])
    return {
        "ventas": ventas_df,
        "catalogo": catalogo_df,
        "inventario": pd.DataFrame(inventario),
        "promociones": pd.DataFrame(filas_promos),
    }


# ---------------------------------------------------------------------------
# Errores inyectados a propósito (para evaluar al agente Limpiador)
# ---------------------------------------------------------------------------
def _fecha_otro_formato(d: date, rng: np.random.Generator) -> str:
    opciones = [
        f"{d.day:02d}/{d.month:02d}/{d.year}",
        f"{d.year}/{d.month:02d}/{d.day:02d}",
        f"{d.day}-{ABREV_MES[d.month - 1]}-{d.year}",
        f"{d.day} de {NOMBRES_MES[d.month - 1]} de {d.year}",
        f"{d.day:02d}-{d.month:02d}-{d.year}",
    ]
    return opciones[int(rng.integers(len(opciones)))]


def _precio_con_texto(precio: float, rng: np.random.Generator, fake: Faker) -> str:
    opciones = [
        f"${precio:.2f}",
        f"{precio:.2f} pesos",
        f"{precio:.2f}".replace(".", ","),
        f"$ {precio:,.2f} MXN",
        f" {precio:g} ",
        f"{precio:.2f} {fake.random_element(['aprox', 'c/u', 'p/u'])}",
    ]
    return opciones[int(rng.integers(len(opciones)))]


def inyectar_errores(ventas: pd.DataFrame, semilla: int = 42) -> tuple[pd.DataFrame, list[dict]]:
    """Devuelve el CSV "sucio" (todo en texto) y la lista de errores inyectados.

    La posición de cada error se reporta como ``fila`` = índice de la fila de
    datos en el archivo sucio (0 = primera fila después del encabezado).
    """
    rng = np.random.default_rng(semilla + 1)
    fake = Faker("es_MX")
    fake.seed_instance(semilla)

    df = ventas.copy()
    df["fecha"] = df["fecha"].astype(str)
    for c in ("cantidad", "precio_unitario", "total"):
        df[c] = df[c].astype(object)
    df["_rid"] = np.arange(len(df))
    errores: list[dict] = []
    usados: set[int] = set()

    def elegir(k: int) -> list[int]:
        libres = np.setdiff1d(np.arange(len(df)), np.fromiter(usados, int, len(usados)))
        sel = rng.choice(libres, size=k, replace=False)
        usados.update(int(s) for s in sel)
        return [int(s) for s in sel]

    # 1) Valores nulos
    for col, k in (("cantidad", 20), ("producto", 15), ("fecha", 12), ("precio_unitario", 13)):
        for r in elegir(k):
            correcto = df.at[r, col]
            df.at[r, col] = None
            errores.append({"_rid": r, "tipo": "nulo", "columna": col, "valor_original": None,
                            "valor_correcto": str(correcto)})
    # 2) Fechas en otros formatos
    for r in elegir(80):
        d = date.fromisoformat(df.at[r, "fecha"])
        df.at[r, "fecha"] = _fecha_otro_formato(d, rng)
        errores.append({"_rid": r, "tipo": "fecha_formato", "columna": "fecha",
                        "valor_original": df.at[r, "fecha"], "valor_correcto": d.isoformat()})
    # 3) Precios con texto
    for r in elegir(60):
        precio = float(df.at[r, "precio_unitario"])
        df.at[r, "precio_unitario"] = _precio_con_texto(precio, rng, fake)
        errores.append({"_rid": r, "tipo": "precio_texto", "columna": "precio_unitario",
                        "valor_original": df.at[r, "precio_unitario"], "valor_correcto": f"{precio:.2f}"})
    # 4) Nombres de producto con mayúsculas/espacios inconsistentes
    for r in elegir(40):
        nombre = df.at[r, "producto"]
        variante = [nombre.upper(), nombre.lower(), f"  {nombre} ", nombre.replace(" ", "  ")][int(rng.integers(4))]
        df.at[r, "producto"] = variante
        errores.append({"_rid": r, "tipo": "producto_formato", "columna": "producto",
                        "valor_original": variante, "valor_correcto": nombre})
    # 5) Cantidades negativas (devoluciones mal capturadas)
    for r in elegir(15):
        q = int(df.at[r, "cantidad"])
        df.at[r, "cantidad"] = -q
        errores.append({"_rid": r, "tipo": "cantidad_negativa", "columna": "cantidad",
                        "valor_original": str(-q), "valor_correcto": str(q)})
    # 6) Totales que no cuadran con cantidad × precio
    for r in elegir(20):
        correcto = float(df.at[r, "total"])
        df.at[r, "total"] = round(correcto * float(rng.choice([0.1, 10, 1.5, 0.5])), 2)
        errores.append({"_rid": r, "tipo": "total_inconsistente", "columna": "total",
                        "valor_original": str(df.at[r, "total"]), "valor_correcto": f"{correcto:.2f}"})
    # 7) Filas duplicadas (se insertan copias exactas justo después del original)
    dup_src = elegir(50)
    copias = df.loc[dup_src].copy()
    copias["_dup"] = True
    df["_dup"] = False
    df = pd.concat([df, copias]).sort_values(["_rid", "_dup"], kind="stable").reset_index(drop=True)

    # Reubicar los errores a su posición final en el archivo sucio
    pos_original = {int(rid): i for i, (rid, dup) in enumerate(zip(df["_rid"], df["_dup"])) if not dup}
    for e in errores:
        e["fila"] = pos_original[e.pop("_rid")]
    for i, (rid, dup) in enumerate(zip(df["_rid"], df["_dup"])):
        if dup:
            errores.append({"fila": i, "tipo": "duplicado", "columna": "*", "valor_original": None,
                            "valor_correcto": f"duplicado de la fila {pos_original[int(rid)]}"})
    errores.sort(key=lambda e: (e["fila"], e["tipo"]))
    return df.drop(columns=["_rid", "_dup"]), errores


def formato_distinto(ventas: pd.DataFrame, semilla: int = 42) -> pd.DataFrame:
    """Último trimestre con encabezados y formatos distintos (como otra hoja del cliente)."""
    fake = Faker("es_MX")
    fake.seed_instance(semilla)
    rng = np.random.default_rng(semilla + 2)
    q4 = ventas[pd.to_datetime(ventas["fecha"]) >= "2025-10-01"].copy()
    pago = {"efectivo": "Efectivo", "tarjeta": "TARJETA", "transferencia": "Transf."}
    # Encabezados poco comunes a propósito: obligan al Limpiador a usar el LLM para mapearlos
    out = pd.DataFrame({
        "Día de venta": pd.to_datetime(q4["fecha"]).dt.strftime("%d/%m/%Y"),
        "Hora": q4["hora"],
        "Folio": q4["ticket"],
        "Artículo vendido": q4["producto"],
        "Pzas": q4["cantidad"],
        "Precio c/u": q4["precio_unitario"].map(lambda p: f"${p:,.2f}"),
        "Cobrado": q4["total"],
        "Pagó con": q4["metodo_pago"].map(pago),
        "Promo": q4["promocion"],
        # Columna libre que el Limpiador debe ignorar (texto aleatorio, sin datos personales)
        "Notas": [fake.word() if rng.random() < 0.05 else "" for _ in range(len(q4))],
    })
    return out.reset_index(drop=True)


def main() -> None:
    import sys
    for flujo in (sys.stdout, sys.stderr):
        if hasattr(flujo, "reconfigure"):
            flujo.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--semilla", type=int, default=42)
    ap.add_argument("--salida", type=Path, default=DIR_DATOS)
    args = ap.parse_args()
    args.salida.mkdir(parents=True, exist_ok=True)

    tablas = simular(args.semilla)
    v = tablas["ventas"]
    v.to_csv(args.salida / "ventas_2025.csv", index=False, encoding="utf-8")
    tablas["catalogo"].to_csv(args.salida / "catalogo_productos.csv", index=False, encoding="utf-8")
    tablas["inventario"].to_csv(args.salida / "inventario_diario.csv", index=False, encoding="utf-8")
    tablas["promociones"].to_csv(args.salida / "promociones.csv", index=False, encoding="utf-8")

    sucias, errores = inyectar_errores(v, args.semilla)
    sucias.to_csv(args.salida / "ventas_sucias.csv", index=False, encoding="utf-8")
    resumen = {}
    for e in errores:
        resumen[e["tipo"]] = resumen.get(e["tipo"], 0) + 1
    (args.salida / "errores_inyectados.json").write_text(
        json.dumps({"archivo": "ventas_sucias.csv", "total": len(errores), "por_tipo": resumen,
                    "errores": errores}, ensure_ascii=False, indent=1), encoding="utf-8")

    formato_distinto(v, args.semilla).to_excel(args.salida / "ventas_formato_distinto.xlsx", index=False)

    print(f"Ventas: {len(v):,} renglones · {v['ticket'].nunique():,} tickets · "
          f"{v['producto'].nunique()} productos · total ${v['total'].sum():,.2f}")
    print(f"Inventario diario: {len(tablas['inventario']):,} filas · días sin existencia: "
          f"{int(tablas['inventario']['sin_existencia'].sum()):,}")
    print(f"Errores inyectados: {len(errores)} → {resumen}")
    print(f"Archivos en {args.salida}")


if __name__ == "__main__":
    main()
