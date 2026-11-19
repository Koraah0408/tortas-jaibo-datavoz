"""Herramienta ``generar_grafica``: crea gráficas Plotly (y su versión PNG para el reporte).

Recibe una especificación (tipo, x, y, color, título) decidida por el agente
Visualizador y los datos del resultado SQL. Tipos soportados: barras,
barras_horizontales, lineas, pastel, mapa_calor, indicador, tabla y ninguna.
"""

from __future__ import annotations

import io

import pandas as pd
import plotly.graph_objects as go
import plotly.express as px

from ..utilidades import formato_numero

TIPOS = ["barras", "barras_horizontales", "lineas", "pastel", "mapa_calor", "indicador", "tabla", "ninguna"]
COLUMNAS_TIEMPO = ["fecha", "mes", "nombre_mes", "semana", "inicio_semana", "dia", "hora_del_dia", "trimestre",
                   "num_dia_semana", "dia_semana"]
ORDEN_DIAS = ["lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"]
ORDEN_MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre",
               "octubre", "noviembre", "diciembre"]
# Paleta de Tortas Jaibo (rojo de la marca primero). Validada con el verificador de paletas: banda de luminosidad,
# croma, separación para daltonismo (protan/deutan) entre colores vecinos y contraste >= 3:1 sobre fondo blanco.
PALETA = ["#C8102E", "#2F6FA8", "#C08414", "#7A4FA0", "#3F8F2F", "#C2577F"]
ESCALA_CALOR = [[0, "#FDF1E3"], [0.5, "#E8737B"], [1, "#8E0B21"]]   # un solo tono (rojo), de claro a oscuro
FUENTE = "Poppins, Segoe UI, sans-serif"
TINTA = "#2B2320"          # texto principal
CUADRICULA = "#F1E6CC"     # cuadrícula discreta
EJE = "#E2CFA0"


def columnas_numericas(df: pd.DataFrame) -> list[str]:
    return [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c]) and not pd.api.types.is_bool_dtype(df[c])]


def preparar_datos(df: pd.DataFrame, spec: dict) -> tuple[pd.DataFrame, dict]:
    """Normaliza la especificación contra las columnas reales y ordena ejes temporales."""
    df = df.copy()
    spec = dict(spec)
    numericas = columnas_numericas(df)
    cols = list(df.columns)
    y = spec.get("y")
    if isinstance(y, str):
        y = [y]
    y = [c for c in (y or []) if c in cols]
    if not y:
        y = [c for c in numericas if c not in (spec.get("x"), "mes", "num_dia_semana", "anio", "semana",
                                                "hora_del_dia", "dia", "trimestre")][:1] or numericas[-1:]
    x = spec.get("x") if spec.get("x") in cols else None
    if x is None:
        no_num = [c for c in cols if c not in y]
        x = no_num[0] if no_num else None
    # Resultado de una sola fila con varias columnas numéricas → pasar a formato largo
    if len(df) == 1 and spec.get("tipo") in ("barras", "barras_horizontales", "pastel") and len(numericas) >= 2:
        pedidas = [c for c in (spec.get("y") or []) if c in numericas] if isinstance(spec.get("y"), list) else []
        valores = pedidas if len(pedidas) >= 2 else [
            c for c in numericas if not any(s in c.lower() for s in ("pct", "porcentaje", "cambio", "variacion"))]
        largo = pd.DataFrame({"concepto": [NOMBRES_LEGIBLES.get(c, c) for c in valores],
                              "valor": [df.iloc[0][c] for c in valores]})
        return largo, {**spec, "x": "concepto", "y": ["valor"]}
    # Etiquetas legibles para meses y días
    if x == "mes" and "nombre_mes" in cols:
        df = df.sort_values("mes")
        x = "nombre_mes"
    if x == "dia_semana" and "num_dia_semana" in cols:
        df = df.sort_values("num_dia_semana")
    elif x == "dia_semana":
        df["_orden"] = df["dia_semana"].map({d: i for i, d in enumerate(ORDEN_DIAS)})
        df = df.sort_values("_orden").drop(columns="_orden")
    elif x == "nombre_mes" and "mes" not in cols:
        df["_orden"] = df["nombre_mes"].map({m: i for i, m in enumerate(ORDEN_MESES)})
        df = df.sort_values("_orden").drop(columns="_orden")
    elif x in ("fecha", "semana", "hora_del_dia", "dia", "trimestre", "inicio_semana"):
        df = df.sort_values(x)
    color = spec.get("color") if spec.get("color") in cols else None
    return df, {**spec, "x": x, "y": y, "color": color}


def _etiqueta(col: str | None) -> str:
    return (col or "").replace("_", " ").capitalize()


# Nombres en palabras del dueño para leyendas y ejes (columnas de las herramientas del Asesor de negocio)
NOMBRES_LEGIBLES = {"comprar_pan_normal": "Pan normal", "comprar_pan_mega": "Pan Mega", "venta_cobrada": "Lo que cobras",
                    "ingreso_despues_de_comision": "Lo que te queda", "ordenes_juntos": "Órdenes en que se piden juntos",
                    "combos_extra_por_semana_para_no_perder": "Combos extra por semana", "dia_compra": "Día",
                    "combinacion": "Combinación", "escenario": "Escenario"}


def _nombres_legibles(datos: pd.DataFrame, spec: dict) -> tuple[pd.DataFrame, dict]:
    cambio = {c: NOMBRES_LEGIBLES[c] for c in datos.columns if c in NOMBRES_LEGIBLES}
    if not cambio:
        return datos, spec
    spec = dict(spec)
    for k in ("x", "color", "valor", "y_dim"):
        if spec.get(k) in cambio:
            spec[k] = cambio[spec[k]]
    spec["y"] = [cambio.get(c, c) for c in spec.get("y") or []]
    return datos.rename(columns=cambio), spec


def generar_figura(df: pd.DataFrame, spec: dict) -> go.Figure | None:
    """Construye la figura Plotly. Devuelve None para 'tabla' o 'ninguna'."""
    tipo = spec.get("tipo", "barras")
    if tipo in ("tabla", "ninguna") or df.empty:
        return None
    titulo = spec.get("titulo") or ""
    if tipo == "indicador":
        num = columnas_numericas(df)
        if not num:
            return None
        col = (spec.get("y") or [num[0]])
        col = col[0] if isinstance(col, list) else col
        col = col if col in df.columns else num[0]
        valor = float(df.iloc[0][col])
        es_dinero = any(s in col.lower() for s in ("total", "venta", "importe", "ingreso", "ganancia", "monto", "ticket_prom"))
        fig = go.Figure(go.Indicator(mode="number", value=valor,
                                     number={"prefix": "$" if es_dinero else "", "valueformat": ",.2f" if valor % 1 else ",.0f"},
                                     title={"text": f"{titulo}<br><span style='font-size:0.8em;color:gray'>{_etiqueta(col)}</span>"}))
        fig.update_layout(height=260, margin=dict(l=20, r=20, t=60, b=20), font=dict(family=FUENTE, color=TINTA),
                          paper_bgcolor="rgba(0,0,0,0)")
        fig.update_traces(number_font=dict(color=PALETA[0], size=46))
        return fig

    datos, spec = preparar_datos(df, spec)
    datos, spec = _nombres_legibles(datos, spec)
    x, y, color = spec["x"], spec["y"], spec.get("color")
    if tipo == "mapa_calor":
        dims = [c for c in datos.columns if c not in columnas_numericas(datos) or c in ("hora_del_dia", "mes", "semana")]
        fila = spec.get("y_dim") or next((c for c in dims if c != x and c not in ("num_dia_semana",)), None)
        valor = spec.get("valor") if spec.get("valor") in datos.columns else y[0]
        if x is None or fila is None or fila == valor:
            return generar_figura(df, {**spec, "tipo": "barras"})
        if fila == "dia_semana" and "num_dia_semana" in datos.columns:
            datos = datos.sort_values("num_dia_semana")
        tabla = datos.pivot_table(index=fila, columns=x, values=valor, aggfunc="sum", sort=False)
        fig = px.imshow(tabla, aspect="auto", color_continuous_scale=ESCALA_CALOR, title=titulo,
                        labels=dict(x=_etiqueta(x), y=_etiqueta(fila), color=_etiqueta(valor)))
    elif tipo == "pastel":
        fig = px.pie(datos, names=x, values=y[0], title=titulo, color_discrete_sequence=PALETA, hole=0.35)
        fig.update_traces(textinfo="percent+label")
    elif tipo == "lineas":
        fig = px.line(datos, x=x, y=y if len(y) > 1 else y[0], color=color, markers=True, title=titulo,
                      color_discrete_sequence=PALETA)
    elif tipo == "barras_horizontales":
        fig = px.bar(datos, y=x, x=y if len(y) > 1 else y[0], color=color, orientation="h", title=titulo,
                     color_discrete_sequence=PALETA, barmode="group")
        fig.update_layout(yaxis={"categoryorder": "total ascending"})
    else:
        fig = px.bar(datos, x=x, y=y if len(y) > 1 else y[0], color=color, title=titulo, barmode="group",
                     color_discrete_sequence=PALETA)
    return estilizar(fig, tipo, titulo, x, y)


_PALABRAS_DINERO = ("venta", "vendido", "total", "cobr", "ingreso", "costo", "ticket", "comision", "ganancia",
                    "monto", "precio", "dinero", "lo que te queda", "a_credito", "descuento")


def es_dinero(columna: str | None) -> bool:
    c = (columna or "").lower()
    return any(p in c for p in _PALABRAS_DINERO) and not any(p in c for p in ("pct", "porcentaje", "%"))


def estilizar(fig: go.Figure, tipo: str, titulo: str = "", x: str | None = None, y: list[str] | None = None,
              alto: int = 400) -> go.Figure:
    """Estilo común de Tortas Jaibo: título a la izquierda, valores sobre las barras, cuadrícula discreta."""
    y = y or []
    dinero = bool(y) and all(es_dinero(c) for c in y)
    fig.update_layout(template="plotly_white", font=dict(family=FUENTE, size=13, color=TINTA),
                      title=dict(text=f"<b>{titulo}</b>" if titulo else "", x=0, xanchor="left", y=0.97,
                                 font=dict(size=16, color=TINTA)),
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", colorway=PALETA,
                      hoverlabel=dict(font_family=FUENTE, bgcolor="#FFFFFF", bordercolor=EJE, font_color=TINTA),
                      legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="left", x=0, title_text=""),
                      height=alto, margin=dict(l=8, r=16, t=84, b=8), separators=".,")
    eje_valor = dict(showgrid=True, gridcolor=CUADRICULA, zeroline=False, showline=False, ticks="",
                     tickprefix="$" if dinero else "", tickformat=",.0f" if dinero else None,
                     title_text="", automargin=True)
    eje_categoria = dict(showgrid=False, showline=True, linecolor=EJE, ticks="", title_text="", automargin=True)
    formato = "$%{VAL:,.0f}" if dinero else "%{VAL:,.4~f}"
    if tipo in ("barras", "barras_horizontales"):
        horizontal = tipo == "barras_horizontales"
        fig.update_xaxes(**(eje_valor if horizontal else eje_categoria))
        fig.update_yaxes(**(eje_categoria if horizontal else eje_valor))
        if horizontal:
            fig.update_yaxes(categoryorder="total ascending", showline=False)
        n_barras = sum(len(t.x if not horizontal else t.y) for t in fig.data if getattr(t, "type", "") == "bar")
        etiqueta = formato.replace("VAL", "x" if horizontal else "y")
        fig.update_traces(marker_cornerradius=4, marker_line_width=0, hovertemplate=f"%{{{'y' if horizontal else 'x'}}}: "
                          + etiqueta + "<extra>%{fullData.name}</extra>")
        if n_barras <= 16:  # pocas barras: el valor se lee directo, sin adivinar con el eje
            fig.update_traces(texttemplate=etiqueta, textposition="outside", cliponaxis=False,
                              textfont=dict(size=12, color=TINTA))
        fig.update_layout(bargap=0.32, bargroupgap=0.08, uniformtext_minsize=10, uniformtext_mode="hide")
        # espacio para que el valor escrito afuera de la barra más larga no se corte
        valores = [float(v) for t in fig.data if getattr(t, "type", "") == "bar"
                   for v in (t.x if horizontal else t.y) if v is not None and not isinstance(v, str)]
        if valores and n_barras <= 16:
            alto_max, bajo_min = max(max(valores), 0), min(min(valores), 0)
            rango = [bajo_min * 1.2, alto_max * 1.2 if alto_max else 1]
            (fig.update_xaxes if horizontal else fig.update_yaxes)(range=rango)
    elif tipo == "lineas":
        fig.update_xaxes(**eje_categoria)
        fig.update_yaxes(**eje_valor)
        fig.update_traces(line_width=2.4, marker_size=8, hovertemplate="%{x}: " + formato.replace("VAL", "y")
                          + "<extra>%{fullData.name}</extra>")
    elif tipo == "pastel":
        fig.update_traces(textinfo="percent+label", marker=dict(line=dict(color="#FFFFFF", width=2)),
                          hovertemplate="%{label}: " + formato.replace("VAL", "value") + " (%{percent})<extra></extra>")
        fig.update_layout(showlegend=False)
    elif tipo == "mapa_calor":
        fig.update_xaxes(showgrid=False, title_text="")
        fig.update_yaxes(showgrid=False, title_text="")
    if len(fig.data) <= 1 and tipo != "pastel":
        fig.update_layout(showlegend=False)   # una sola serie: el título ya dice qué es
    return fig


def generar_grafica(columnas: list[str], filas: list[list], spec: dict) -> dict:
    """Herramienta: devuelve {spec, figura_json} listo para el dashboard."""
    df = pd.DataFrame(filas, columns=columnas)
    tipo = spec.get("tipo") if spec.get("tipo") in TIPOS else "barras"
    spec = {**spec, "tipo": tipo}
    try:
        fig = generar_figura(df, spec)
    except Exception as e:  # una mala especificación no debe romper la respuesta
        return {"spec": {**spec, "tipo": "tabla"}, "figura_json": None, "error": f"No se pudo graficar: {e}"}
    return {"spec": spec, "figura_json": fig.to_json() if fig is not None else None, "error": None}


def figura_desde_json(figura_json: str | None) -> go.Figure | None:
    if not figura_json:
        return None
    import plotly.io as pio
    return pio.from_json(figura_json)


def grafica_png(columnas: list[str], filas: list[list], spec: dict) -> bytes | None:
    """Versión estática (matplotlib) de la gráfica para el reporte PDF."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    df = pd.DataFrame(filas, columns=columnas)
    tipo = spec.get("tipo")
    if tipo in (None, "tabla", "ninguna", "indicador") or df.empty:
        return None
    try:
        datos, spec = preparar_datos(df, spec)
        x, y = spec["x"], spec["y"]
        fig, ax = plt.subplots(figsize=(7.5, 3.6), dpi=130)
        if tipo == "pastel":
            ax.pie(datos[y[0]], labels=datos[x], autopct="%1.0f%%", colors=PALETA[:len(datos)],
                   wedgeprops={"width": 0.6})
        elif tipo == "lineas":
            for i, col in enumerate(y):
                ax.plot(datos[x].astype(str), datos[col], marker="o", color=PALETA[i % len(PALETA)], label=_etiqueta(col))
            if len(y) > 1:
                ax.legend()
            plt.xticks(rotation=45, ha="right")
        elif tipo == "mapa_calor":
            num = columnas_numericas(datos)
            dims = [c for c in datos.columns if c not in num or c in ("hora_del_dia", "mes")]
            fila = next((c for c in dims if c != x and c != "num_dia_semana"), None)
            if fila is None:
                plt.close(fig)
                return None
            tabla = datos.pivot_table(index=fila, columns=x, values=y[0], aggfunc="sum", sort=False)
            im = ax.imshow(tabla.values, aspect="auto", cmap="GnBu")
            ax.set_xticks(range(len(tabla.columns)), [str(c) for c in tabla.columns], fontsize=7)
            ax.set_yticks(range(len(tabla.index)), [str(c) for c in tabla.index], fontsize=7)
            fig.colorbar(im, ax=ax)
        elif tipo == "barras_horizontales":
            d = datos.sort_values(y[0])
            ax.barh(d[x].astype(str), d[y[0]], color=PALETA[0])
        else:
            ancho = 0.8 / len(y)
            posiciones = range(len(datos))
            for i, col in enumerate(y):
                ax.bar([p + i * ancho for p in posiciones], datos[col], width=ancho, color=PALETA[i % len(PALETA)], label=_etiqueta(col))
            ax.set_xticks([p + ancho * (len(y) - 1) / 2 for p in posiciones], datos[x].astype(str), rotation=45, ha="right")
            if len(y) > 1:
                ax.legend()
        ax.set_title(spec.get("titulo") or "", fontsize=10)
        ax.spines[["top", "right"]].set_visible(False)
        fig.tight_layout()
        buffer = io.BytesIO()
        fig.savefig(buffer, format="png")
        plt.close(fig)
        return buffer.getvalue()
    except Exception:
        plt.close("all")
        return None


def resumen_valor(valor) -> str:
    return formato_numero(valor)
