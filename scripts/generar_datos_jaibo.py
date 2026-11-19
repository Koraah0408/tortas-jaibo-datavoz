"""Ventas sintéticas de Tortas Jaibo con el esquema del POS anterior (para pruebas y evaluación).

Usa los nombres, categorías y precios del menú real y la misma estructura que el POS (canales,
formas de pago, tipos de orden, estados), pero las ventas son simuladas: no copia ninguna venta
real. Patrones simulados: horario de 9 a 19 h con hora fuerte a las 14–16 h, lunes que a veces
no abre, platillo "del día" según el día de la semana, quincenas, subida de precios a medio
periodo, precios más altos en Didi y Rappi, promociones de cantidad en mostrador, órdenes
corregidas ("Cancelada por Modificación") y compras a crédito de las empresas Legacy y
Automatas. No contiene datos personales: los "empleados" son ficticios y solo existen para
comprobar que DataVoz NO puede leerlos.

Uso:
    python scripts/generar_datos_jaibo.py --csv data/jaibo/sinteticos
    python scripts/generar_datos_jaibo.py --postgres postgresql://usuario:clave@localhost:5432/postgres
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

RAIZ = Path(__file__).resolve().parents[1]
ZONA = ZoneInfo("America/Monterrey")

# (nombre, categoría, precio de catálogo, peso de popularidad)
MENU = [
    ("Barda normal", "Principal", 95, 12), ("Mega barda", "Principal", 110, 14),
    ("Pierna normal", "Principal", 95, 3), ("Mega pierna", "Principal", 110, 3),
    ("Mixta normal", "Principal", 110, 1), ("Mega mixta", "Principal", 125, 3),
    ("Barbacoa normal", "Principal", 100, 1.5), ("Mega barbacoa", "Principal", 125, 1.2),
    ("Gordita", "Principal", 0, 4), ("Bocoles", "Principal", 22, 4), ("Tacos de barbacoa", "Principal", 30, 4),
    ("Barbacoa", "Principal", 0, 0.3),  # por peso: el renglón se cobra 275 (1/2 kg) o 550 (1 kg)
    ("Huevos al gusto", "Desayuno", 125, 0.7), ("Quesadillas", "Desayuno", 95, 0.6),
    ("Cecina de res", "Del Dia", 125, 0), ("Enmoladas", "Del Dia", 125, 0), ("Milanesa de pollo", "Del Dia", 125, 0),
    ("Enchiladas c/ cecina", "Del Dia", 105, 0), ("Enchiladas suizas", "Del Dia", 125, 0),
    ("Bistec a la mexicana", "Del Dia", 105, 0), ("Consome Barbacoa", "Del Dia", 130, 0.05),
    ("Cargo Extra", "Interno", 0, 0),
]
BEBIDAS = [("Tamarindo", 30, 5), ("Horchata", 30, 9), ("Jamaica", 30, 9), ("Fuze tea", 30, 2), ("Arizona", 30, 3),
           ("Agua natural", 30, 2), ("Sprite", 35, 1), ("Sidral mundet", 35, 2), ("Coca cola", 35, 13),
           ("Delaware punch", 35, 4), ("Coca sin azucar", 35, 3), ("Coca cola cherry", 40, 0.7),
           ("Coca cola vainilla", 40, 0.5), ("Fesca", 35, 0.4)]
# Precio cobrado antes de la subida de precios (mitad del periodo); los demás no cambiaron
PRECIO_ANTES = {"Mega barda": 95, "Bocoles": 16, "Tacos de barbacoa": 25, "Gordita": 25}
PRECIO_RENGLON = {"Gordita": 28}  # la gordita cobra según el guiso aunque en catálogo esté en $0
# Platillo del día que rota según el día de la semana (lunes=0)
DEL_DIA = {0: "Cecina de res", 1: "Enmoladas", 2: "Milanesa de pollo", 3: "Enchiladas c/ cecina",
           4: "Enchiladas suizas", 5: "Enchiladas suizas"}
GUISOS = ["Carne Deshebrada", "Chicharron en Salsa Verde", "Papa con Chorizo", "Chicharron Prensado", "Barbacoa",
          "Machaca con Huevo", "Machaca con Papa", "Huevo Rojo", "Huevo Verde", "Queso Blanco"]
PROMOS = [  # (nombre, precio, productos, cantidad que activa la promo)
    ("2 x Barda/ Pierna", 170, ["Barda normal", "Pierna normal"], 2),
    ("4 Tacos x $105", 105, ["Tacos de barbacoa"], 4),
    ("3 Bocoles x $60", 60, ["Bocoles"], 3),
    ("3 Gorditas x $85", 85, ["Gordita"], 3),
    ("Combo Enmoladas + Horchata", 145, ["Enmoladas", "Horchata"], 1),
]
SOBREPRECIO_APP = {"Didi": 1.05, "Rappi": 1.12}


def generar(inicio: date = date(2026, 1, 5), fin: date = date(2026, 11, 15), semilla: int = 7) -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(semilla)
    nombres = [m[0] for m in MENU] + [b[0] for b in BEBIDAS]
    productos = pd.DataFrame({
        "id": range(1, len(nombres) + 1), "nombre": nombres,
        "precio": [m[2] for m in MENU] + [b[1] for b in BEBIDAS],
        "categoria": [m[1] for m in MENU] + ["Bebidas"] * len(BEBIDAS),
        "ruta_imagen": None,
        "stock": pd.array([None] * len(MENU) + [int(rng.integers(12, 48)) for _ in BEBIDAS], dtype="Int64"),
        "es_personalizable": [m[0] in ("Gordita", "Bocoles", "Huevos al gusto", "Quesadillas") for m in MENU] + [False] * len(BEBIDAS),
        "permite_guisos_extra": [m[0] == "Gordita" for m in MENU] + [False] * len(BEBIDAS),
        "esta_activo": [m[0] != "Cargo Extra" for m in MENU] + [True] * len(BEBIDAS)})
    id_de = dict(zip(productos["nombre"], productos["id"]))
    precio_de = dict(zip(productos["nombre"], productos["precio"]))
    cambio_precios = inicio + (fin - inicio) / 2

    ingredientes = pd.DataFrame({"id": range(1, len(GUISOS) + 4), "nombre": GUISOS + ["Cebolla", "Limon", "Cilantro"],
                                 "precio_adicional": [5.0] * len(GUISOS) + [0.0] * 3,
                                 "categoria": ["Guisos"] * len(GUISOS) + ["Ingredientes"] * 3})
    prod_ing = []
    for prod, grupo, tipo in (("Gordita", "Guisos", "VARIAS"), ("Bocoles", "Elige tu guiso", "UNA")):
        for i, g in enumerate(GUISOS[:7], start=1):
            prod_ing.append({"id_producto": id_de[prod], "id_ingrediente": i, "grupo": grupo, "tipo_grupo": tipo})
    for prod in ("Tacos de barbacoa", "Consome Barbacoa"):
        for j in (len(GUISOS) + 1, len(GUISOS) + 2, len(GUISOS) + 3):
            prod_ing.append({"id_producto": id_de[prod], "id_ingrediente": j, "grupo": "Extras", "tipo_grupo": "EXTRA"})

    promociones = pd.DataFrame({"id": range(1, len(PROMOS) + 1), "nombre": [p[0] for p in PROMOS],
                                "precio_promocional": [float(p[1]) for p in PROMOS], "esta_activa": True})
    detalle_promos = pd.DataFrame([{"id_promocion": i, "id_producto": id_de[n]}
                                   for i, p in enumerate(PROMOS, start=1) for n in p[2]])

    empleados = pd.DataFrame({"id": range(1, 7), "nombre": [f"Empleado de prueba {i}" for i in range(1, 7)],
                              "empresa": ["Legacy"] * 3 + ["Automatas"] * 3, "limite_credito": 450.0})

    def precio_renglon(nombre: str, d: date) -> float:
        if nombre == "Barbacoa":
            return float(rng.choice([275, 550], p=[0.4, 0.6]))
        if d < cambio_precios and nombre in PRECIO_ANTES:
            return float(PRECIO_ANTES[nombre])
        return float(PRECIO_RENGLON.get(nombre, precio_de[nombre]))

    pesos_bebidas = np.array([b[2] for b in BEBIDAS]) / sum(b[2] for b in BEBIDAS)
    ventas, detalle, creditos = [], [], []
    id_venta = 0
    d = inicio
    while d <= fin:
        dow = d.weekday()
        if dow == 0 and rng.random() < 0.35:  # a veces no abre en lunes
            d += timedelta(days=1)
            continue
        quincena = d.day in (15, 16, 30, 31, 1, 2)
        n_ordenes = rng.poisson((19 if dow == 6 else 17) * (1.1 if quincena else 1.0))
        horas = rng.choice(np.arange(9, 20), size=n_ordenes,
                           p=np.array([4, 7, 8, 8, 9, 16, 14, 12, 10, 10, 2]) / 100)
        for num, hora in enumerate(sorted(horas), start=1):
            id_venta += 1
            p_canal = [0.48, 0.25, 0.10, 0.13, 0.04] if dow < 6 else [0.62, 0.26, 0.10, 0.02, 0.0]
            canal = rng.choice(["Local", "Didi", "Rappi", "Legacy", "Automatas"], p=p_canal)
            if canal == "Local":
                pago = rng.choice(["Efectivo", "Tarjeta", "Transferencia"], p=[0.6, 0.33, 0.07])
                tipo = rng.choice(["Para Aquí", "Para Llevar"], p=[0.6, 0.4])
            elif canal == "Didi":
                pago, tipo = rng.choice(["Didi", "Didi Efectivo"], p=[0.73, 0.27]), "Para Llevar"
            elif canal == "Rappi":
                pago, tipo = "Rappi", "Para Llevar"
            elif canal == "Legacy":
                pago, tipo = "Crédito Empleado", rng.choice(["Para Aquí", "Para Llevar"], p=[0.3, 0.7])
            else:
                pago, tipo = "Crédito Automatas", "Para Llevar"
            pesos = []
            for nombre, cat, _precio, peso in MENU:
                w = peso
                if cat == "Del Dia" and nombre != "Consome Barbacoa":
                    w = 2.5 if DEL_DIA.get(dow) == nombre else 0.0
                pesos.append(w)
            pesos = np.array(pesos) / sum(pesos)
            lineas = {}
            for _ in range(rng.choice([1, 2, 3], p=[0.62, 0.3, 0.08])):
                prod = MENU[rng.choice(len(MENU), p=pesos)][0]
                q = int(rng.choice([2, 3, 4], p=[0.3, 0.4, 0.3])) if prod in ("Gordita", "Bocoles", "Tacos de barbacoa") else 1
                lineas[prod] = lineas.get(prod, 0) + q
            n_platos = sum(1 for p in lineas if p != "Barbacoa")
            verano = 1.2 if d.month in (5, 6, 7, 8) else 1.0
            for _ in range(n_platos):
                if rng.random() < min(0.95, 0.55 * verano):
                    beb = BEBIDAS[rng.choice(len(BEBIDAS), p=pesos_bebidas)][0]
                    lineas[beb] = lineas.get(beb, 0) + 1
            precios = {p: precio_renglon(p, d) for p in lineas}
            if rng.random() < 0.02:
                lineas["Cargo Extra"], precios["Cargo Extra"] = 1, float(rng.choice([10, 20, 40, 45, 50]))
            subtotal = sum(precios[p] * q for p, q in lineas.items())
            ajuste = 0.0
            if canal in SOBREPRECIO_APP:
                ajuste = round(subtotal * (SOBREPRECIO_APP[canal] - 1))
            else:
                for _nombre, precio_p, prods, n in PROMOS[:4]:
                    cuantos = sum(lineas.get(p, 0) for p in prods)
                    if cuantos >= n:
                        normal = n * precios.get(prods[0], precio_de[prods[0]])
                        ajuste -= (cuantos // n) * max(0.0, normal - precio_p)
                if "Gordita" in lineas and rng.random() < 0.3:
                    ajuste += 5.0 * lineas["Gordita"]  # guiso extra
            monto = round(subtotal + ajuste, 2)
            factura = canal == "Local" and rng.random() < 0.01
            iva = round(monto * 0.16, 2) if factura else 0.0
            estado = "Completada" if rng.random() > 0.06 else "Cancelada por Modificación"
            momento = datetime(d.year, d.month, d.day, int(hora), int(rng.integers(0, 60)), int(rng.integers(0, 60)), tzinfo=ZONA)
            ventas.append({"id": id_venta, "fecha_hora": momento, "monto_total": monto, "metodo_pago": pago,
                           "canal_venta": canal, "tipo_orden": tipo, "iva": iva, "total_con_iva": round(monto + iva, 2),
                           "estado": estado, "numero_orden_dia": num})
            for p, q in lineas.items():
                detalle.append({"id_venta": id_venta, "id_producto": id_de[p], "cantidad": q,
                                "precio_unitario": precios[p], "notas": None})
            if canal in ("Legacy", "Automatas"):
                emp = int(rng.integers(1, 4)) if canal == "Legacy" else int(rng.integers(4, 7))
                creditos.append({"id_empleado": emp, "id_venta": id_venta, "monto_credito": monto,
                                 "monto_excedente_pagado": 0.0, "metodo_pago_excedente": None,
                                 "estado": "Activo", "fecha": d})
        d += timedelta(days=1)

    return {"productos": productos, "ingredientes": ingredientes, "producto_ingredientes": pd.DataFrame(prod_ing),
            "promociones": promociones, "detalle_promociones": detalle_promos, "ventas": pd.DataFrame(ventas),
            "detalle_ventas": pd.DataFrame(detalle), "empleados": empleados,
            "creditos_empleados": pd.DataFrame(creditos)}


ORDEN_CARGA = ["productos", "ingredientes", "producto_ingredientes", "promociones", "detalle_promociones",
               "ventas", "detalle_ventas", "empleados", "creditos_empleados"]


def _valor_sql(v):
    if v is None or v is pd.NA or (isinstance(v, float) and np.isnan(v)):
        return None
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, np.floating):
        return float(v)
    if isinstance(v, np.bool_):
        return bool(v)
    return v


def cargar_postgres(tablas: dict[str, pd.DataFrame], url: str) -> None:
    """Crea el esquema del POS anterior en un Postgres DE PRUEBA y carga los datos sintéticos."""
    import psycopg
    from psycopg.conninfo import conninfo_to_dict

    host = (conninfo_to_dict(url).get("host") or "localhost").lower()
    if host not in ("localhost", "127.0.0.1", "::1"):
        # Este script BORRA el esquema public: jamás debe apuntar a la base de producción
        raise SystemExit(f"Rechazado: '{host}' no es un Postgres local de prueba. Este script borra el esquema "
                         "public y solo se permite contra localhost.")
    esquema = (RAIZ / "tests" / "jaibo" / "esquema_pos_anterior.sql").read_text(encoding="utf-8")
    with psycopg.connect(url, autocommit=True) as con:
        con.execute("drop schema if exists public cascade; create schema public;")
        con.execute(esquema)
        for nombre in ORDEN_CARGA:
            df = tablas[nombre]
            columnas = list(df.columns)
            with con.cursor().copy(f"COPY {nombre} ({', '.join(columnas)}) FROM STDIN") as copia:
                for fila in df.itertuples(index=False):
                    copia.write_row([_valor_sql(v) for v in fila])
            if "id" in columnas:
                con.execute(f"select setval(pg_get_serial_sequence('{nombre}', 'id'), (select max(id) from {nombre}))")


def main() -> None:
    for flujo in (sys.stdout, sys.stderr):
        flujo.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--csv", type=Path, help="carpeta donde escribir un CSV por tabla")
    ap.add_argument("--postgres", help="URL de un Postgres DE PRUEBA donde crear el esquema y cargar los datos")
    args = ap.parse_args()
    tablas = generar()
    v = tablas["ventas"]
    print(f"Ventas sintéticas: {len(v):,} órdenes · {len(tablas['detalle_ventas']):,} renglones · "
          f"{v['fecha_hora'].min():%Y-%m-%d} a {v['fecha_hora'].max():%Y-%m-%d}")
    if args.csv:
        args.csv.mkdir(parents=True, exist_ok=True)
        for nombre, df in tablas.items():
            df.to_csv(args.csv / f"{nombre}.csv", index=False, encoding="utf-8")
        print("CSV en", args.csv)
    if args.postgres:
        cargar_postgres(tablas, args.postgres)
        print("Cargado en Postgres de prueba")


if __name__ == "__main__":
    main()
