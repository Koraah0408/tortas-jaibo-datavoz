"""Interfaz web de DataVoz para Tortas Jaibo (Streamlit): pregúntale a tus ventas por texto o voz.

Ejecutar:  streamlit run app.py

Trabaja sobre la copia de SOLO LECTURA del POS (data/jaibo/jaibo.duckdb). Si no hay copia ni conexión
configurada, usa una demostración con ventas simuladas del mismo menú (para quien clona el repositorio).
"""

from __future__ import annotations

import hmac
import os
import re
import tempfile
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from datavoz import sesiones
from datavoz.agentes.analista_sql import olvidar_cache
from datavoz.basedatos import ejecutar_select, tablas_y_columnas
from datavoz.conectores import jaibo
from datavoz.config import obtener_config
from datavoz.datos import construir_base_ejemplo
from datavoz.herramientas.generar_grafica import figura_desde_json, generar_grafica
from datavoz.llm import proveedores_disponibles
from datavoz.sistema import SesionDataVoz
from datavoz.utilidades import formato_numero
from interfaz import estilos

RAIZ_APP = Path(__file__).resolve().parent

st.set_page_config(page_title="Tortas Jaibo · Asistente de ventas", page_icon=":material/lunch_dining:", layout="wide")
st.markdown(estilos.CSS, unsafe_allow_html=True)


def acceso_permitido() -> bool:
    """En la nube (APP_PASSWORD definido) pide contraseña: las ventas del negocio no son públicas."""
    clave = os.getenv("APP_PASSWORD")
    if not clave or st.session_state.get("acceso_ok"):
        return True
    _, centro, _ = st.columns([1, 1.2, 1])
    with centro:
        st.markdown(estilos.marca(), unsafe_allow_html=True)
        with st.form("acceso"):
            intento = st.text_input("Contraseña", type="password")
            if st.form_submit_button("Entrar", type="primary", width="stretch"):
                if hmac.compare_digest(intento.encode(), clave.encode()):
                    st.session_state.acceso_ok = True
                    st.rerun()
                st.error("Contraseña incorrecta.")
    return False


if not acceso_permitido():
    st.stop()

# Qué hace cada agente, en palabras del dueño (indicador de progreso)
NODOS = {"transcribir": (":material/mic:", "Orquestador", "escuchando tu nota de voz"),
         "orquestador": (":material/hub:", "Orquestador", "entendiendo tu pregunta"),
         "limpiador": (":material/cleaning_services:", "Limpiador", "revisando el archivo"),
         "analista_sql": (":material/database:", "Analista", "buscando en tus ventas"),
         "supervisor": (":material/fact_check:", "Orquestador", "revisando que el cálculo sea correcto"),
         "asesor_negocio": (":material/insights:", "Asesor de negocio", "haciendo las cuentas del negocio"),
         "visualizador": (":material/bar_chart:", "Visualizador", "preparando la gráfica"),
         "narrador": (":material/record_voice_over:", "Narrador", "explicándolo en palabras sencillas"),
         "responder": (":material/forum:", "Orquestador", "respondiendo"),
         "exportar": (":material/picture_as_pdf:", "Narrador", "armando tu reporte PDF"),
         "memoria": (":material/memory:", "Memoria", "guardando la conversación")}
ICONO_AGENTE = {"Orquestador": "agentes", "Limpiador": "datos", "Analista SQL": "datos", "Visualizador": "grafica",
                "Narrador": "chat", "Memoria": "sesiones", "Asesor de negocio": "foco"}

# Las decisiones del día a día del negocio (tarjetas de la bienvenida, en cuadrícula de 2 × 2)
ACCIONES = [
    ("pan", "¿Cuánto pan compro mañana?", "Pan normal y Mega según lo que se vende ese día, con margen de seguridad.",
     "¿Cuánto pan debo comprar para mañana?"),
    ("carrito", "Hazme la lista de compras", "Pan, carne, verduras y quesos de la semana y cuánto vas a gastar (precios de Chedraui).",
     "Hazme la lista de compras para esta semana"),
    ("moto", "¿Me conviene Didi y Rappi?", "Lo que te deja cada canal después de las comisiones de las apps.",
     "¿Me conviene vender en Didi y Rappi o en mostrador?"),
    ("etiqueta", "¿Qué promoción lanzo?", "Lo que tus clientes ya piden juntos y los horarios más flojos.",
     "¿Qué promoción nueva me recomiendas?"),
]
SUGERENCIAS = ["¿Cómo acabó el reporte de ventas de ayer?", "¿Cuánto entró en efectivo esta semana según los reportes?",
               "¿Cuántas tortas vendo cada día de la semana?", "¿Qué bebida se pide más con las tortas?",
               "¿Qué día de la semana cobro más dinero?", "¿A qué hora se venden más órdenes?",
               "¿Cuánto vendí en Rappi el mes pasado?", "¿Cuántos pedidos se corrigieron este mes?"]
DIAS_CORTOS = {"lunes": "Lun", "martes": "Mar", "miercoles": "Mié", "jueves": "Jue", "viernes": "Vie",
               "sabado": "Sáb", "domingo": "Dom"}
CONFIG_GRAFICA = {"displayModeBar": False}
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
         "noviembre", "diciembre"]
AVATAR_USUARIO = ":material/person:"
AVATAR_ASISTENTE = ":material/lunch_dining:"


@st.cache_resource(show_spinner="Preparando el asistente de Tortas Jaibo…")
def preparar_sistema() -> dict:
    return construir_base_ejemplo()  # índice del RAG (diccionario, reglas y ejemplos de cada negocio)


def fecha_larga(iso: str | None) -> str:
    try:
        d = date.fromisoformat(str(iso)[:10])
    except ValueError:
        return str(iso or "")
    return f"{d.day} de {MESES[d.month - 1]} de {d.year}"


@st.cache_data(ttl=600, show_spinner=False)
def kpis_de(ruta_db: str) -> dict:
    """Últimos 7 días contra los 7 anteriores (lo realmente cobrado, sin órdenes canceladas)."""
    from datavoz.herramientas.negocio_jaibo import productos_de_grupo
    if "ordenes" not in tablas_y_columnas(ruta_db):
        return {}
    r = ejecutar_select("""
        WITH f AS (SELECT MAX(fecha) AS m FROM ordenes)
        SELECT SUM(monto_total) FILTER (WHERE fecha > m - INTERVAL 7 DAY),
               SUM(monto_total) FILTER (WHERE fecha <= m - INTERVAL 7 DAY AND fecha > m - INTERVAL 14 DAY),
               COUNT(*) FILTER (WHERE fecha > m - INTERVAL 7 DAY),
               COUNT(*) FILTER (WHERE fecha <= m - INTERVAL 7 DAY AND fecha > m - INTERVAL 14 DAY)
        FROM ordenes, f WHERE NOT cancelada""", ruta_db)
    if not r.ok or not r.filas:
        return {}
    venta, venta_prev, ordenes, ordenes_prev = [x or 0 for x in r.filas[0]]
    productos = [f[0] for f in ejecutar_select("SELECT DISTINCT producto FROM ventas", ruta_db, max_filas=1000).filas]
    tortas = productos_de_grupo("tortas", productos)
    t = ejecutar_select(f"""
        WITH f AS (SELECT MAX(fecha) AS m FROM ventas)
        SELECT SUM(cantidad) FILTER (WHERE fecha > m - INTERVAL 7 DAY),
               SUM(cantidad) FILTER (WHERE fecha <= m - INTERVAL 7 DAY AND fecha > m - INTERVAL 14 DAY)
        FROM ventas, f WHERE producto IN ({", ".join("'" + p.replace("'", "''") + "'" for p in tortas) or "''"})""",
                        ruta_db)
    tortas_7, tortas_prev = [x or 0 for x in t.filas[0]] if t.ok and t.filas else (0, 0)
    return {"venta": venta, "venta_prev": venta_prev, "ordenes": ordenes, "ordenes_prev": ordenes_prev,
            "ticket": venta / ordenes if ordenes else 0, "ticket_prev": venta_prev / ordenes_prev if ordenes_prev else 0,
            "tortas": tortas_7, "tortas_prev": tortas_prev}


def cambio(actual: float, previo: float) -> float | None:
    return 100 * (actual - previo) / previo if previo else None


@st.cache_data(ttl=600, show_spinner=False)
def semana_de(ruta_db: str) -> dict:
    """Datos de la pestaña «Mi semana» (últimos 7 días; por día también los 7 anteriores)."""
    def tabla(sql: str) -> pd.DataFrame:
        r = ejecutar_select(sql, ruta_db, max_filas=500)
        return r.a_dataframe() if r.ok else pd.DataFrame()
    por_dia = tabla("""
        WITH f AS (SELECT MAX(fecha) AS m FROM ordenes)
        SELECT dia_semana, num_dia_semana,
               CASE WHEN fecha > m - INTERVAL 7 DAY THEN 'Esta semana' ELSE 'Semana anterior' END AS periodo,
               ROUND(SUM(monto_total), 2) AS vendido
        FROM ordenes, f WHERE NOT cancelada AND fecha > m - INTERVAL 14 DAY
        GROUP BY dia_semana, num_dia_semana, periodo ORDER BY num_dia_semana""")
    canales = tabla("""
        WITH f AS (SELECT MAX(fecha) AS m FROM ordenes)
        SELECT canal, ROUND(SUM(monto_total), 2) AS vendido FROM ordenes, f
        WHERE NOT cancelada AND fecha > m - INTERVAL 7 DAY GROUP BY canal""")
    productos = tabla("""
        WITH f AS (SELECT MAX(fecha) AS m FROM ventas)
        SELECT producto, SUM(cantidad) AS unidades FROM ventas, f
        WHERE fecha > m - INTERVAL 7 DAY AND categoria <> 'Interno' AND producto <> '--'
        GROUP BY producto ORDER BY unidades DESC LIMIT 7""")
    horas = tabla("""
        WITH f AS (SELECT MAX(fecha) AS m FROM ordenes)
        SELECT hora_del_dia, COUNT(*) AS ordenes FROM ordenes, f
        WHERE NOT cancelada AND fecha > m - INTERVAL 7 DAY GROUP BY hora_del_dia ORDER BY hora_del_dia""")
    return {"por_dia": por_dia, "canales": canales, "productos": productos, "horas": horas}


def graficas_semana(d: dict) -> list:
    import plotly.express as px
    from datavoz.herramientas.generar_grafica import PALETA, estilizar
    figuras = []
    if not d["por_dia"].empty:
        df = d["por_dia"].assign(dia=lambda x: x["dia_semana"].map(DIAS_CORTOS))
        fig = px.bar(df, x="dia", y="vendido", color="periodo", barmode="group",
                     category_orders={"dia": list(DIAS_CORTOS.values()), "periodo": ["Esta semana", "Semana anterior"]},
                     color_discrete_map={"Esta semana": PALETA[0], "Semana anterior": "#D8C49A"})
        figuras.append(estilizar(fig, "barras", "Ventas por día contra la semana anterior", "dia", ["vendido"], 340))
        figuras[-1].update_traces(texttemplate=None, selector=dict(name="Semana anterior"))
    if not d["canales"].empty:
        fig = px.bar(d["canales"], y="canal", x="vendido", orientation="h", color_discrete_sequence=PALETA)
        figuras.append(estilizar(fig, "barras_horizontales", "Ventas por canal", "canal", ["vendido"], 340))
    if not d["productos"].empty:
        fig = px.bar(d["productos"], y="producto", x="unidades", orientation="h", color_discrete_sequence=[PALETA[1]])
        figuras.append(estilizar(fig, "barras_horizontales", "Lo más vendido (piezas)", "producto", ["unidades"], 340))
    if not d["horas"].empty:
        df = d["horas"].assign(hora=lambda x: x["hora_del_dia"].map(lambda h: f"{int(h)} h"))
        fig = px.bar(df, x="hora", y="ordenes", color_discrete_sequence=[PALETA[2]])
        figuras.append(estilizar(fig, "barras", "Órdenes por hora del día", "hora", ["ordenes"], 340))
    return figuras


def _combo_sugerido(ruta_db: str, p1: str, p2: str) -> str | None:
    """«¿Conviene un combo de A + B a $X?» con ~10 % de descuento sobre el precio actual, redondeado a $5."""
    from datavoz.herramientas.negocio_jaibo import _precio_actual
    try:
        precios = _precio_actual(ruta_db, [p1, p2], [])
        normal = precios[p1] + precios[p2]
    except Exception:
        return None
    return f"¿Conviene un combo de {p1} + {p2} a ${int(normal * 0.9 // 5 * 5)}?"


@st.cache_data(show_spinner=False, ttl=900)
def _alertas(ruta_db: str, version: float) -> list[dict]:
    from datavoz.herramientas.detectar_alertas import detectar_alertas
    try:
        return detectar_alertas(ruta_db)
    except Exception:
        return []


def alertas_de(ruta_db: str) -> list[dict]:
    return _alertas(ruta_db, Path(ruta_db).stat().st_mtime) if Path(ruta_db).exists() else []


def mostrar_alertas(alertas: list[dict]) -> None:
    st.markdown(estilos.titulo_tarjeta("alertas", "Alertas automáticas"), unsafe_allow_html=True)
    if not alertas:
        st.caption("Sin alertas: en las últimas semanas no hay nada fuera de lo normal (caídas de productos o canales, "
                   "semana floja, pedidos corregidos de más o bebidas por acabarse).")
        return
    for a in alertas:
        st.markdown(estilos.chip("aviso", a["mensaje"]), unsafe_allow_html=True)


def mis_pdfs() -> list[tuple[Path, str]]:
    """Todos los PDF que se han hecho (reportes de ventas y de conversación), del más nuevo al más viejo."""
    carpeta = obtener_config().dir_reportes
    archivos = sorted(carpeta.glob("*.pdf"), key=lambda a: a.stat().st_mtime, reverse=True) if carpeta.exists() else []
    lista = []
    for a in archivos:
        m = re.fullmatch(r"reporte_ventas_(\d{8})(?:_(\d{8}))?", a.stem)
        if m:
            d1 = datetime.strptime(m.group(1), "%Y%m%d").date()
            d2 = datetime.strptime(m.group(2), "%Y%m%d").date() if m.group(2) else None
            nombre = (f"Ventas del {d1:%d/%m/%Y}" if not d2 else f"Ventas del {d1:%d/%m} al {d2:%d/%m/%Y}")
        else:
            nombre = f"Conversación · {datetime.fromtimestamp(a.stat().st_mtime):%d/%m %H:%M}"
        lista.append((a, nombre))
    return lista


def lista_pdfs(clave: str) -> None:
    pdfs = mis_pdfs()
    if not pdfs:
        st.caption("Aún no hay PDF. Pide, por ejemplo: «Reporte de ventas de ayer».")
        return
    for i, (archivo, nombre) in enumerate(pdfs):
        st.download_button(nombre, archivo.read_bytes(), file_name=archivo.name, mime="application/pdf",
                           icon=":material/download:", width="stretch", key=f"{clave}_{i}_{archivo.name}")


def sugerencias_para(r: dict, ruta_db: str) -> list[str]:
    """Siguientes preguntas lógicas según lo que se acaba de responder (el dueño solo las toca)."""
    hn = r.get("herramienta_negocio") or {}
    nombre, par = hn.get("nombre"), hn.get("parametros") or {}
    if nombre == "reporte_de_ventas":
        return ["Reporte de ventas de la semana pasada", "¿Qué producto se vendió más ese día?",
                "¿Cuánto pan compro para mañana?"]
    if nombre == "pronosticar_pan":
        return ["¿Cuánto me voy a gastar en pan esta semana?", "¿Y para el fin de semana?",
                "¿Qué pasa si compro con 20% de margen?"]
    if nombre == "lista_de_compras":
        otra = "¿Y solo para mañana?" if len(par.get("fechas") or []) > 2 else "¿Y para toda la semana?"
        return [otra, "¿Cuánto pan compro para el sábado?", "¿Qué día de la semana se venden más tortas?"]
    if nombre == "rentabilidad_canales":
        return ["Si Rappi me cobra 30% de comisión, ¿me conviene?", "¿Qué productos se piden más en Didi?",
                "¿Qué promoción nueva me recomiendas?"]
    if nombre == "combinaciones_frecuentes":
        res = r.get("resultado") or {}
        cols = res.get("columnas") or []
        sugs = []
        if "ya_es_promocion" in cols:
            libre = next((f for f in res.get("filas") or [] if f[cols.index("ya_es_promocion")] == "no"), None)
            combo = _combo_sugerido(ruta_db, libre[0], libre[1]) if libre else None
            sugs += [combo] if combo else []
        return sugs + ["¿Qué día y a qué hora casi no hay gente?", "¿Qué bebida se pide más con las tortas?"]
    if nombre == "simular_promocion":
        productos, precio = par.get("productos") or {}, par.get("precio_promocional") or 0
        combo = " + ".join(f"{q} {p}" if q > 1 else p for p, q in productos.items())
        return [f"¿Y si el combo de {combo} cuesta ${precio + 10:.0f}?", "¿Qué otros productos se piden juntos?",
                "¿Me conviene vender en Didi y Rappi?"]
    pregunta = (r.get("pregunta_completa") or r.get("pregunta") or "").lower()
    primera = ("¿Y cómo fue el mes anterior?" if re.search(r"\b(mes|enero|febrero|marzo|abril|mayo|junio|julio|agosto|"
                                                           r"septiembre|octubre|noviembre|diciembre)\b", pregunta)
               else "Compáralo con la semana anterior" if "semana" in pregunta else "¿Y cómo fue el mes pasado?")
    return [primera, "¿Qué me recomiendas hacer con esto?", "¿Cuánto pan debo comprar para mañana?"]


def chips(preguntas: list[str], clave: str, columnas: int = 3) -> None:
    with st.container(key=f"chips_{clave}"):
        cols = st.columns(columnas)
        for i, p in enumerate(preguntas):
            if cols[i % columnas].button(p, key=f"chip_{clave}_{i}", width="stretch"):
                st.session_state.pendiente = p
                st.rerun()


# ----------------------------- Sesiones ------------------------------------
def sesiones_jaibo() -> list[dict]:
    return [s for s in sesiones.listar() if "Jaibo" in (s.get("origen_datos") or "")]


def sincronizar_jaibo(forzar: bool) -> dict | None:
    """Actualiza la copia local desde el POS (solo lectura) y limpia cachés que dependen de los datos."""
    try:
        r = jaibo.sincronizar(forzar=forzar)
    except jaibo.ErrorConexionJaibo as e:
        st.toast(str(e), icon=":material/error:")
        return None
    if not r.get("omitida"):
        olvidar_cache(str(jaibo.RUTA_DB))
        kpis_de.clear()
    return r


def fuente_jaibo() -> tuple[str, str | None]:
    """Copia del POS (se actualiza si tiene más de 30 min) o, sin conexión ni copia, la demostración."""
    if os.getenv("JAIBO_DEMO"):  # para presentaciones y capturas: nunca muestra las ventas reales
        return str(jaibo.asegurar_demo()), jaibo.ORIGEN_DEMO
    if jaibo.configuracion():
        sincronizar_jaibo(forzar=False)
    if jaibo.RUTA_DB.exists():
        return str(jaibo.RUTA_DB), None
    return str(jaibo.asegurar_demo()), jaibo.ORIGEN_DEMO


def mensajes_desde_historial(historial: list[dict]) -> list[dict]:
    """Reconstruye el chat de una sesión guardada (las gráficas se regeneran desde los datos)."""
    mensajes = []
    for t in historial or []:
        if t.get("pregunta"):
            mensajes.append({"rol": "user", "texto": t["pregunta"]})
        r = {k: t.get(k) for k in ("respuesta", "intencion", "sql", "resultado", "pregunta", "pregunta_completa")}
        spec = (t.get("grafica") or {}).get("spec")
        res = t.get("resultado") or {}
        if spec and res.get("columnas"):
            r["grafica"] = generar_grafica(res["columnas"], res.get("filas") or [], spec)
        r["restaurado"] = True
        mensajes.append({"rol": "assistant", "texto": t.get("respuesta") or "", "r": r})
    return mensajes


def abrir_sesion(sesion_id: str | None = None) -> None:
    if sesion_id:  # una conversación guardada retoma sus propios datos
        sesion = SesionDataVoz(sesion_id=sesion_id, persistente=True)
    else:
        ruta, origen = fuente_jaibo()
        sesion = SesionDataVoz(persistente=True, ruta_db=ruta, dominio="jaibo", origen=origen)
    st.session_state.sesion = sesion
    st.session_state.mensajes = mensajes_desde_historial(sesion.estado().get("historial")) if sesion_id else []
    st.session_state.ultimo = None
    st.session_state.reporte = None


def al_cambiar_sesion() -> None:
    abrir_sesion(st.session_state.selector_sesion)


def etiqueta_sesion(sesion_id: str, guardadas: dict) -> str:
    s = guardadas.get(sesion_id)
    if not s:
        return "Conversación nueva"
    return f"{s['nombre']} · {datetime.fromisoformat(s['actualizada']).strftime('%d/%m %H:%M')}"


# ----------------------------- Ejecución de turnos -------------------------
def ejecutar(funcion, *args, etiqueta: str = "Trabajando en tu pregunta…", **kwargs) -> dict:
    with st.status(etiqueta, expanded=False) as estado:
        def al_avanzar(nodo: str, paso: dict) -> None:
            icono, agente, accion = NODOS.get(nodo, (":material/hub:", nodo, ""))
            st.markdown(f"{icono} **{agente}** · {accion}")
            estado.update(label=accion[:1].upper() + accion[1:] + "…")
        r = funcion(*args, al_avanzar=al_avanzar, **kwargs)
        estado.update(label=f"Listo en {r['duracion_s']:.0f} s", state="error" if r.get("error") else "complete")
    return r


def registrar_respuesta(r: dict, pregunta_usuario: str | None, por_voz: bool = False) -> None:
    if pregunta_usuario:
        st.session_state.mensajes.append({"rol": "user", "texto": pregunta_usuario, "voz": por_voz})
    st.session_state.mensajes.append({"rol": "assistant", "texto": r.get("respuesta") or "", "r": r})
    st.session_state.ultimo = r
    if r.get("reporte_pdf"):
        st.session_state.reporte = r["reporte_pdf"]


def separar_recomendacion(texto: str) -> tuple[str, str | None, str]:
    """Respuesta del Narrador → (explicación, recomendación, nota final)."""
    m = re.search(r"\s*\**\s*Recomendaci[oó]n\s*:?\s*\**\s*:?\s*", texto or "")
    if not m:
        return texto or "", None, ""
    reco, _, nota = texto[m.end():].partition("\n\n")
    return texto[:m.start()].strip(), reco.strip(" *"), nota.strip()


def sin_latex(texto: str) -> str:
    return (texto or "").replace("$", "\\$")  # en Markdown de Streamlit «$…$» sería una fórmula


def mostrar_detalles(r: dict) -> None:
    resultado = r.get("resultado") or {}
    with st.expander("Ver cómo lo calculé", icon=":material/search:"):
        if r.get("pregunta_completa") and r.get("pregunta_completa") != r.get("pregunta"):
            st.caption(f"Entendí tu pregunta como: *{r['pregunta_completa']}*")
        if r.get("explicacion_sql") and not r.get("sql"):
            st.caption(sin_latex(r["explicacion_sql"]))
        if r.get("sql"):
            st.code(r["sql"], language="sql")
        if resultado.get("columnas"):
            st.dataframe(pd.DataFrame(resultado["filas"], columns=resultado["columnas"]), hide_index=True,
                         width="stretch", height=min(35 * (len(resultado.get("filas") or []) + 1) + 3, 320))
        for a in r.get("consultas_apoyo") or []:
            st.caption(f"Dato de apoyo: {a.get('proposito')}")
            if a.get("columnas"):
                st.dataframe(pd.DataFrame(a["filas"], columns=a["columnas"]), hide_index=True, width="stretch")
        intentos = r.get("intentos_sql") or []
        if len(intentos) > 1:
            st.caption(f"El Orquestador revisó el cálculo y pidió {len(intentos) - 1} corrección(es) antes de responder.")
        pasos = r.get("pasos") or []
        if pasos:
            st.markdown("".join(estilos.paso(p["agente"], p["accion"].replace("_", " "), f"{p['duracion_s']:.1f} s",
                                             ICONO_AGENTE.get(p["agente"], "agentes")) for p in pasos),
                        unsafe_allow_html=True)
        elif r.get("restaurado"):
            st.caption("Respuesta de una conversación guardada.")


def mostrar_mensaje(m: dict, indice: int, ultimo: bool = False, ruta_db: str = "") -> None:
    with st.chat_message(m["rol"], avatar=AVATAR_USUARIO if m["rol"] == "user" else AVATAR_ASISTENTE):
        st.markdown(estilos.marca_mensaje(m["rol"]), unsafe_allow_html=True)
        if m["rol"] == "user":
            st.markdown(sin_latex(m["texto"]))
            if m.get("voz"):
                st.caption(":material/mic: Pregunta por voz")
            return
        r = m.get("r") or {}
        cuerpo, reco, nota = separar_recomendacion(m["texto"])
        st.markdown(sin_latex(cuerpo))
        grafica = r.get("grafica") or {}
        fig = figura_desde_json(grafica.get("figura_json"))
        if fig is not None:
            st.plotly_chart(fig, width="stretch", key=f"graf_{indice}", config=CONFIG_GRAFICA)
        elif (grafica.get("spec") or {}).get("tipo") == "tabla" and (r.get("resultado") or {}).get("columnas"):
            res = r["resultado"]
            st.dataframe(pd.DataFrame(res["filas"], columns=res["columnas"]), hide_index=True, width="stretch")
        if reco:
            st.markdown(estilos.recomendacion(reco), unsafe_allow_html=True)
        if nota:
            st.caption(sin_latex(nota))
        pdf = r.get("reporte_pdf")
        if pdf and Path(pdf).exists():
            st.download_button("Descargar el PDF", Path(pdf).read_bytes(), file_name=Path(pdf).name,
                               mime="application/pdf", icon=":material/picture_as_pdf:", key=f"pdf_{indice}")
        if r.get("intencion") == "confirmar_carga":
            problemas = (r.get("limpieza") or {}).get("problemas") or []
            if problemas:
                with st.expander("Ver ejemplos de lo que voy a cambiar", icon=":material/rule:"):
                    columnas = [c for c in ("fila", "tipo", "columna", "valor_original", "valor_corregido", "accion")
                                if c in problemas[0]]
                    st.dataframe(pd.DataFrame(problemas[:30])[columnas], hide_index=True, width="stretch")
            if ultimo and sesion.carga_pendiente():
                c1, c2 = st.columns(2)
                if c1.button("Aprobar y cargar", icon=":material/check:", type="primary", width="stretch",
                             key=f"aprobar_{indice}"):
                    r2 = ejecutar(sesion.aprobar_carga, etiqueta="Aplicando los cambios aprobados…")
                    registrar_respuesta(r2, "Apruebo los cambios: cárgalo")
                    st.rerun()
                if c2.button("Cancelar", icon=":material/close:", width="stretch", key=f"cancelar_{indice}"):
                    registrar_respuesta(sesion.cancelar_carga(), "No, cancela la carga")
                    st.rerun()
        verif = r.get("verificacion")
        if verif and verif.get("total_cifras"):
            texto = ("Cifras verificadas contra tus ventas" if verif.get("ok")
                     else "Algunas cifras no se pudieron verificar: revisa el detalle")
            st.markdown(estilos.verificacion(bool(verif.get("ok")), texto), unsafe_allow_html=True)
        if r.get("intencion") == "consulta_datos":
            mostrar_detalles(r)
            if ultimo:  # sugerencias para responder: la siguiente pregunta lógica, a un toque
                st.markdown(estilos.seguir(), unsafe_allow_html=True)
                chips(sugerencias_para(r, ruta_db), f"seguir_{indice}")


def pestana_reportes(ruta_db: str) -> None:
    """Reportes financieros diarios que el POS manda por Gmail: cifras de caja, PDF y enlace al correo."""
    import plotly.express as px
    from datavoz.conectores import gmail_reportes
    from datavoz.herramientas.generar_grafica import PALETA, estilizar
    st.markdown(estilos.titulo_tarjeta("reporte", "Tus PDF"), unsafe_allow_html=True)
    st.caption("Reportes de ventas y de conversaciones que has pedido. Pide uno nuevo en «Preguntar», "
               "por ejemplo: «Reporte de ventas del 18».")
    if len(mis_pdfs()) > 5:  # con muchos PDF, una caja con su propia barra para no alargar la página
        with st.container(height=260, border=False):
            lista_pdfs("pestana")
    else:
        lista_pdfs("pestana")
    st.divider()
    almacen = gmail_reportes.guardados()
    df = gmail_reportes.tabla_reportes(almacen)
    c1, c2 = st.columns([3, 1])
    c1.markdown(estilos.titulo_tarjeta("reporte", "Reportes diarios que mandas por Gmail"), unsafe_allow_html=True)
    if almacen.get("actualizado"):
        c1.caption(f"{len(df)} días guardados · última búsqueda {datetime.fromisoformat(almacen['actualizado']).strftime('%d/%m %H:%M')}")
    if gmail_reportes.configurado():
        if c2.button("Buscar nuevos", icon=":material/mail:", width="stretch", help="Solo lee tu Gmail; no envía ni borra nada"):
            with st.spinner("Buscando tus reportes en Gmail…"):
                try:
                    r = gmail_reportes.sincronizar(ruta_db=ruta_db if "jaibo" in ruta_db else None)
                    olvidar_cache(ruta_db)
                    st.toast(f"Listo: {r['nuevos']} reportes nuevos · {r['total']} días", icon=":material/check_circle:")
                    st.rerun()
                except gmail_reportes.ErrorGmail as e:
                    st.error(str(e), icon=":material/error:")
    else:
        c2.caption("Gmail aún no está conectado: sigue docs/jaibo/GMAIL.md.")
    if df.empty and gmail_reportes.configurado() and not st.session_state.get("gmail_auto"):
        st.session_state.gmail_auto = True  # en la nube arranca sin reportes: se traen solos una vez
        with st.spinner("Trayendo tus reportes de Gmail…"):
            try:
                gmail_reportes.sincronizar(ruta_db=ruta_db if "jaibo" in ruta_db else None)
                st.rerun()
            except gmail_reportes.ErrorGmail as e:
                st.error(str(e), icon=":material/error:")
    if df.empty:
        st.info("Todavía no hay reportes guardados. Conecta Gmail para traerlos.", icon=":material/mail:")
        return
    fig = px.bar(df.tail(30).assign(dia=lambda x: pd.to_datetime(x["fecha"]).dt.strftime("%d/%m")), x="dia",
                 y="ingresos_brutos", color_discrete_sequence=[PALETA[0]])
    st.plotly_chart(estilizar(fig, "barras", "Ingresos brutos por día", "dia", ["ingresos_brutos"], 320),
                    width="stretch", key="reportes_grafica", config=CONFIG_GRAFICA)
    dias = list(reversed(df["fecha"].tolist()))
    elegido = st.selectbox("Ver el reporte del día", dias, format_func=lambda d: fecha_larga(d.isoformat()))
    fila = df[df["fecha"] == elegido].iloc[0]
    registro = almacen["reportes"].get(f"{elegido.isoformat()}_{elegido.isoformat()}", {})
    st.markdown(estilos.kpis([
        ("dinero", "Ingresos brutos", f"${fila['ingresos_brutos']:,.2f}", None),
        ("ticket", "Órdenes", f"{int(fila['total_ordenes'] or 0)}", None),
        ("caja", "Efectivo", f"${fila['efectivo']:,.2f}", None),
        ("baja", "Egresos", f"${fila['egresos'] or 0:,.2f}", None),
    ]), unsafe_allow_html=True)
    detalle = pd.DataFrame([{"Concepto": k, "Monto": v} for k, v in (registro.get("metodos") or {}).items()]
                           + [{"Concepto": "Fondo inicial de caja", "Monto": fila["fondo_inicial"]},
                              {"Concepto": "Crédito otorgado", "Monto": fila["credito_otorgado"]},
                              {"Concepto": "Ingresos netos", "Monto": fila["ingresos_netos"]}])
    st.dataframe(detalle, hide_index=True, width="stretch",
                 column_config={"Monto": st.column_config.NumberColumn(format="$%.2f")})
    b1, b2 = st.columns(2)
    archivo = RAIZ_APP / registro.get("archivo", "") if registro.get("archivo") else None
    if archivo and archivo.exists():
        b1.download_button("Descargar PDF", archivo.read_bytes(), file_name=archivo.name, mime="application/pdf",
                           icon=":material/download:", width="stretch")
    if registro.get("id_mensaje"):
        b2.link_button("Abrir el correo en Gmail", f"https://mail.google.com/mail/u/0/#all/{registro['id_mensaje']}",
                       icon=":material/open_in_new:", width="stretch")
    with st.expander("Todos los días guardados", icon=":material/table_chart:"):
        st.dataframe(df.sort_values("fecha", ascending=False), hide_index=True, width="stretch")


# ---------------------------------------------------------------------------
preparar_sistema()
if "sesion" not in st.session_state:
    guardadas_al_iniciar = sesiones_jaibo()
    abrir_sesion(guardadas_al_iniciar[0]["id"] if guardadas_al_iniciar else None)
sesion: SesionDataVoz = st.session_state.sesion
cfg = obtener_config()
_datos_sesion = sesion.estado().get("datos") or {}
if not Path(_datos_sesion.get("ruta_db") or "").exists():
    st.warning("Esta conversación usaba una copia de las ventas que ya no está en esta computadora. "
               "Abre una **conversación nueva** para usar la copia actual.", icon=":material/cloud_off:")

# ----------------------------- Barra lateral -------------------------------
with st.sidebar:
    st.markdown(estilos.marca(), unsafe_allow_html=True)
    proveedores = proveedores_disponibles()
    if not proveedores:
        st.markdown(estilos.chip("aviso", "Falta configurar el modelo de lenguaje: copia <b>.env.example</b> a "
                                 "<b>.env</b> y agrega tu GOOGLE_API_KEY.", error=True), unsafe_allow_html=True)
    if st.button("Nueva conversación", icon=":material/add:", type="primary", width="stretch"):
        with st.spinner("Preparando tus ventas…"):
            abrir_sesion(None)
        st.rerun()

    # Conversaciones guardadas
    st.markdown(estilos.seccion("chat", "Tus conversaciones"), unsafe_allow_html=True)
    guardadas = {s["id"]: s for s in sesiones_jaibo()}
    ids = list(guardadas)
    if sesion.sesion_id not in guardadas:
        ids = [sesion.sesion_id] + ids
    st.session_state.selector_sesion = sesion.sesion_id
    st.selectbox("Conversación", ids, key="selector_sesion", on_change=al_cambiar_sesion,
                 label_visibility="collapsed", format_func=lambda i: etiqueta_sesion(i, guardadas))
    with st.popover("Renombrar o borrar", icon=":material/edit:", width="stretch",
                    disabled=sesion.sesion_id not in guardadas):
        actual = guardadas.get(sesion.sesion_id) or {}
        nombre = st.text_input("Nombre de la conversación", value=actual.get("nombre", ""))
        if st.button("Guardar nombre", icon=":material/check:", width="stretch"):
            sesiones.renombrar(sesion.sesion_id, nombre)
            st.rerun()
        st.divider()
        confirmar = st.checkbox("Confirmo que quiero borrarla")
        if st.button("Borrar conversación", icon=":material/delete:", width="stretch", disabled=not confirmar):
            sesiones.eliminar(sesion.sesion_id)
            abrir_sesion(None)
            st.rerun()

    # Ventas
    memoria = sesion.estado()
    datos = memoria.get("datos") or {}
    es_demo = datos.get("origen") == jaibo.ORIGEN_DEMO
    st.markdown(estilos.seccion("datos", "Tus ventas"), unsafe_allow_html=True)
    if es_demo:
        st.markdown(estilos.chip("aviso", "<b>Demostración</b> con ventas simuladas del menú de Jaibo. Conecta el POS "
                                 "(docs/jaibo/CONEXION.md) para ver tus ventas reales.", demo=True),
                    unsafe_allow_html=True)
    else:
        est = jaibo.estado()
        cuando = datetime.fromisoformat(est["ultima"]).strftime("%d/%m a las %H:%M") if est.get("ultima") else "—"
        st.markdown(estilos.chip("sync", f"Copia del POS del <b>{cuando}</b><br>{formato_numero(est.get('ordenes'))} "
                                         "órdenes · solo lectura"), unsafe_allow_html=True)
        if jaibo.configuracion() and st.button("Actualizar ventas", icon=":material/sync:", width="stretch",
                                               help="Descarga una copia nueva del POS sin modificar nada"):
            with st.spinner("Descargando del POS (solo lectura)…"):
                r = sincronizar_jaibo(forzar=True)
            if r:
                st.toast(f"Listo: {formato_numero(r['ordenes'])} órdenes en {r['duracion_s']} s",
                         icon=":material/check_circle:")
                st.rerun()

    # Archivo (simulación del agente Limpiador con confirmación del dueño)
    st.markdown(estilos.seccion("datos", "Revisar un archivo de ventas"), unsafe_allow_html=True)
    archivo = st.file_uploader("CSV o Excel de ventas", type=["csv", "xlsx", "xls"], label_visibility="collapsed",
                               key=f"subir_{sesion.sesion_id}")
    st.markdown('<div class="jb-nota"><b>Simulación:</b> el Limpiador revisa el archivo y te dice qué va a corregir; '
                'solo si lo apruebas lo carga en una base de prueba de una conversación nueva. Nunca toca tu POS.</div>',
                unsafe_allow_html=True)
    if archivo is not None and st.session_state.get("archivo_firma") != (archivo.name, archivo.size):
        st.session_state.archivo_firma = (archivo.name, archivo.size)
        destino = Path(tempfile.gettempdir()) / "datavoz_archivos" / f"{datetime.now():%Y%m%d%H%M%S}" / Path(archivo.name).name
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(archivo.getvalue())
        abrir_sesion(None)  # conversación aparte para no mezclar el archivo con las ventas del POS
        sesion = st.session_state.sesion
        r = ejecutar(sesion.cargar_archivo, destino, etiqueta="Revisando tu archivo…")
        registrar_respuesta(r, f"Revisa mi archivo «{Path(archivo.name).name}»")
        st.rerun()

    # Reporte
    st.markdown(estilos.seccion("reporte", "Reporte"), unsafe_allow_html=True)
    if st.button("Crear reporte PDF de la conversación", icon=":material/picture_as_pdf:", width="stretch"):
        r = ejecutar(sesion.preguntar, "Genera el reporte PDF de la sesión", etiqueta="Armando tu reporte…")
        registrar_respuesta(r, "Genera el reporte PDF de la conversación")
        st.rerun()
    with st.expander(f"Mis PDF ({len(mis_pdfs())})", icon=":material/folder:"):
        lista_pdfs("lateral")

    # Detalles técnicos (para la evaluación del proyecto; el dueño no los necesita)
    with st.expander("Detalles técnicos", icon=":material/settings:"):
        if proveedores and proveedores[0] == "gemini":
            st.markdown(estilos.chip("modelo", f"Gemini · agentes: <b>{cfg.modelo_gemini}</b><br>"
                                               f"SQL: <b>{cfg.modelo_gemini_sql}</b>"), unsafe_allow_html=True)
            st.markdown(f'<div class="jb-nota">Respaldo automático: '
                        f'{", ".join(cfg.modelos_gemini_respaldo + proveedores[1:])}</div>', unsafe_allow_html=True)
        elif proveedores:
            st.markdown(estilos.chip("modelo", f"Modelo: <b>{proveedores[0]}</b>"), unsafe_allow_html=True)
        st.toggle("Mostrar datos y trazas de los agentes", key="modo_tecnico")

    st.markdown('<div class="jb-nota" style="margin-top:20px">Asistente de ventas hecho con DataVoz · '
                'Proyecto académico ITCM.<br>Solo lee tus ventas: nunca modifica el POS.</div>', unsafe_allow_html=True)

# ----------------------------- Entrada del usuario -------------------------
entrada = st.chat_input("Escribe o toca el micrófono… por ejemplo: ¿cuánto pan compro para el sábado?",
                        accept_audio=True)
pregunta, por_voz = None, False
if entrada is not None:
    pregunta = (getattr(entrada, "text", None) if not isinstance(entrada, str) else entrada) or None
    audio = None if isinstance(entrada, str) else getattr(entrada, "audio", None)
    if audio is not None and not pregunta:  # nota de voz desde la misma caja: se transcribe y se pregunta
        ruta_audio = Path(tempfile.gettempdir()) / f"datavoz_{sesion.sesion_id}_voz.wav"
        ruta_audio.write_bytes(audio.getvalue())
        st.session_state.pendiente_audio = str(ruta_audio)
if st.session_state.get("pendiente"):
    pregunta = st.session_state.pop("pendiente")
    por_voz = st.session_state.pop("pendiente_es_voz", False)
if pregunta:
    r = ejecutar(sesion.preguntar, pregunta)
    registrar_respuesta(r, pregunta, por_voz)
    st.rerun()  # refresca la barra lateral y el tablero con la conversación ya guardada
elif st.session_state.get("pendiente_audio"):
    ruta = st.session_state.pop("pendiente_audio")
    r = ejecutar(sesion.preguntar, None, audio=ruta)
    registrar_respuesta(r, (r.get("transcripcion") or {}).get("texto") or "(nota de voz)", True)
    st.rerun()

memoria = sesion.estado()
datos = memoria.get("datos") or {}
ruta_db = datos.get("ruta_db") or ""
ruta_panel = fuente_jaibo()[0] if datos.get("archivo_subido") else ruta_db  # «Mi semana» y alertas: el POS

# ----------------------------- Contenido principal -------------------------
st.markdown(estilos.encabezado('¡Hola! ¿Qué quieres <span class="rojo">decidir</span> hoy?',
                               f"Ventas registradas hasta el {fecha_larga((datos.get('resumen') or {}).get('hasta'))}",
                               "Demostración · ventas simuladas" if es_demo else "Copia del POS · solo lectura",
                               demo=es_demo), unsafe_allow_html=True)
k = kpis_de(ruta_panel) if Path(ruta_panel).exists() else {}
alertas = alertas_de(ruta_panel)
if datos.get("archivo_subido"):
    st.markdown(estilos.chip("datos", f"Esta conversación usa el archivo de prueba <b>{datos.get('origen')}</b> "
                                      "(simulación). Tus ventas del POS no cambian.", demo=True), unsafe_allow_html=True)
if k:  # una sola línea discreta; el detalle vive en «Mi semana»
    st.markdown(estilos.resumen_semana([
        (f"${formato_numero(round(k['venta']))}", "en ventas", cambio(k["venta"], k["venta_prev"])),
        (formato_numero(k["ordenes"]), "órdenes", cambio(k["ordenes"], k["ordenes_prev"])),
        (formato_numero(k["tortas"]), "tortas", cambio(k["tortas"], k["tortas_prev"])),
    ]), unsafe_allow_html=True)

tecnico = bool(st.session_state.get("modo_tecnico"))
nombres = [":material/forum: Preguntar", ":material/calendar_month: Mi semana", ":material/mail: Reportes",
           f":material/dashboard: Mi tablero ({len(memoria.get('dashboard') or [])})"]
if tecnico:
    nombres += [":material/table_chart: Datos", ":material/account_tree: Trazas"]
pestanas = st.tabs(nombres)

with pestanas[0]:
    if not st.session_state.mensajes:
        st.markdown('<div class="jb-bienvenida"><h3>¿En qué te ayudo hoy?</h3><p>Toca una tarjeta, escribe tu '
                    'pregunta abajo o grábala con tu voz.</p></div>', unsafe_allow_html=True)
        for fila in (ACCIONES[:2], ACCIONES[2:]):
            columnas = st.columns(2)
            for j, (ico, titulo, desc, pregunta_accion) in enumerate(fila):
                i = ACCIONES.index((ico, titulo, desc, pregunta_accion))
                with columnas[j].container(key=f"accion_{i}"):
                    st.markdown(estilos.accion(ico, titulo, desc), unsafe_allow_html=True)
                    if st.button("Preguntar", key=f"btn_accion_{i}", icon=":material/arrow_forward:", width="stretch"):
                        st.session_state.pendiente = pregunta_accion
                        st.rerun()
        if alertas:
            st.markdown(estilos.chip("aviso", f"<b>{len(alertas)} alerta{'s' if len(alertas) > 1 else ''}</b>: "
                                              f"{alertas[0]['mensaje']} Más en «Mi semana»."), unsafe_allow_html=True)
        with st.expander("Más ideas de preguntas sobre lo que ya vendiste", icon=":material/lightbulb:"):
            chips(SUGERENCIAS, "inicio", columnas=2)
    for i, m in enumerate(st.session_state.mensajes):
        mostrar_mensaje(m, i, ultimo=i == len(st.session_state.mensajes) - 1, ruta_db=ruta_db)

with pestanas[1]:
    if k:
        st.markdown(estilos.kpis([
            ("dinero", "Ventas de los últimos 7 días", f"${formato_numero(round(k['venta']))}", cambio(k["venta"], k["venta_prev"])),
            ("ticket", "Órdenes en 7 días", formato_numero(k["ordenes"]), cambio(k["ordenes"], k["ordenes_prev"])),
            ("tendencia", "Ticket promedio", f"${k['ticket']:,.0f}", cambio(k["ticket"], k["ticket_prev"])),
            ("pan", "Tortas vendidas en 7 días", formato_numero(k["tortas"]), cambio(k["tortas"], k["tortas_prev"])),
        ]), unsafe_allow_html=True)
    mostrar_alertas(alertas)
    figuras = graficas_semana(semana_de(ruta_panel)) if Path(ruta_panel).exists() else []
    for par in range(0, len(figuras), 2):
        columnas = st.columns(2)
        for j, fig in enumerate(figuras[par:par + 2]):
            with columnas[j].container(border=True):
                st.plotly_chart(fig, width="stretch", key=f"semana_{par + j}", config=CONFIG_GRAFICA)
    if figuras:
        st.caption("Ventas cobradas, sin órdenes canceladas. Para ver otro periodo, pregúntalo en «Preguntar».")

with pestanas[2]:
    pestana_reportes(ruta_panel)

with pestanas[3]:
    tarjetas = memoria.get("dashboard") or []
    if not tarjetas:
        st.info("Tu tablero se arma solo: cada pregunta que hagas agrega aquí su gráfica.", icon=":material/insights:")
    columnas = st.columns(2)
    for i, t in enumerate(reversed(tarjetas)):
        with columnas[i % 2].container(border=True):
            st.caption(t.get("pregunta"))
            fig = figura_desde_json(t.get("figura_json"))
            if fig is not None:
                fig.update_layout(height=320)
                st.plotly_chart(fig, width="stretch", key=f"dash_{t['id']}", config=CONFIG_GRAFICA)
            elif t.get("resultado"):
                st.dataframe(pd.DataFrame(t["resultado"]["filas"], columns=t["resultado"]["columnas"]), hide_index=True)
            if st.button("Quitar del tablero", key=f"quitar_{t['id']}", icon=":material/close:"):
                sesion.quitar_del_dashboard(t["id"])
                st.rerun()

if tecnico:
    with pestanas[4]:
        st.markdown(estilos.titulo_tarjeta("datos", f"Origen: {datos.get('origen')}"), unsafe_allow_html=True)
        st.caption(f"Tablas disponibles: {', '.join(datos.get('tablas') or [])}")
        vista = ejecutar_select("SELECT * EXCLUDE (anio, nombre_mes, dia, num_dia_semana, semana, trimestre, "
                                "hora_del_dia, es_fin_de_semana, es_quincena) FROM ventas ORDER BY fecha DESC, hora DESC "
                                "LIMIT 300", ruta_db, max_filas=300)
        if vista.ok:
            st.markdown("##### Últimas ventas")
            st.dataframe(vista.a_dataframe(), hide_index=True, width="stretch", height=380)
    with pestanas[5]:
        r = st.session_state.get("ultimo")
        if not r:
            st.info("Aquí verás el recorrido de los agentes en la última pregunta.", icon=":material/account_tree:")
        else:
            st.markdown(f"**Turno {r.get('turno')}** · intención `{r.get('intencion')}` · {r.get('duracion_s')} s")
            st.markdown("".join(estilos.paso(p["agente"], p["accion"].replace("_", " "),
                                             f"{p['duracion_s']:.2f} s · {len(p.get('llamadas_llm') or [])} LLM",
                                             ICONO_AGENTE.get(p["agente"], "agentes")) for p in r.get("pasos") or []),
                        unsafe_allow_html=True)
            st.caption(f"Traza guardada en {r.get('ruta_traza')}")
            with st.expander("Traza completa (JSON)", icon=":material/data_object:"):
                st.json({k2: v for k2, v in r.items() if k2 not in ("grafica",)}, expanded=False)
