"""Genera docs/ProyectoFinal_DataVoz.pdf a partir de la plantilla HTML y de los resultados de la evaluación.

Uso:
    python docs/generar_documento.py      (usa eval_jaibo_v6 y la suite base eval_v6)

El texto narrativo (análisis de trazas, seguridad, limitaciones, conclusiones y problemas encontrados)
está en docs/contenido_documento.yaml. Las capturas de pantalla se toman de docs/img/*.png|jpg.
La conversión a PDF usa Chrome o Edge en modo headless.
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

import yaml
from jinja2 import Template

RAIZ = Path(__file__).resolve().parents[1]
DOCS = RAIZ / "docs"
sys.path.insert(0, str(RAIZ))

MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
         "noviembre", "diciembre"]

DIAGRAMA = """
<svg viewBox="0 0 770 360" width="100%" xmlns="http://www.w3.org/2000/svg" font-family="Segoe UI, Arial" font-size="10.5">
 <defs><marker id="f" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto">
   <path d="M0,0 L10,5 L0,10 z" fill="#2B2320"/></marker></defs>
 <g stroke="#C8102E" stroke-width="1.5" fill="#FCEFCB">
  <rect x="10" y="15" width="150" height="58" rx="8"/><rect x="190" y="15" width="165" height="58" rx="8" fill="#2B2320"/>
  <rect x="385" y="15" width="180" height="58" rx="8" fill="#C8102E"/><rect x="595" y="15" width="165" height="58" rx="8"/>
  <rect x="10" y="135" width="140" height="62" rx="8"/><rect x="162" y="135" width="140" height="62" rx="8"/>
  <rect x="314" y="135" width="140" height="62" rx="8" fill="#FFE2B8"/><rect x="466" y="135" width="140" height="62" rx="8"/>
  <rect x="618" y="135" width="142" height="62" rx="8"/>
  <rect x="10" y="265" width="330" height="84" rx="8"/><rect x="355" y="265" width="200" height="84" rx="8"/>
  <rect x="570" y="265" width="190" height="84" rx="8"/>
 </g>
 <g text-anchor="middle" fill="#2B2320">
  <text x="85" y="38" font-weight="700">Dueño</text><text x="85" y="55">texto · voz · celular</text>
  <text x="272" y="38" font-weight="700" fill="#fff">Interfaz Streamlit</text><text x="272" y="55" fill="#fff">chat · Mi semana · PDF</text>
  <text x="475" y="35" font-weight="700" fill="#fff">Orquestador (supervisor)</text>
  <text x="475" y="51" fill="#fff">intención · análisis · ruta</text><text x="475" y="65" fill="#fff">revisa el SQL · voz · alertas</text>
  <text x="677" y="38" font-weight="700">Memoria</text><text x="677" y="55">historial + contexto (SQLite)</text>
  <text x="80" y="160" font-weight="700">Limpiador</text><text x="80" y="176">archivos CSV/Excel</text><text x="80" y="190">→ DuckDB</text>
  <text x="232" y="160" font-weight="700">Analista SQL</text><text x="232" y="176">RAG → SELECT</text><text x="232" y="190">+ consultas de apoyo</text>
  <text x="384" y="160" font-weight="700">Asesor de negocio</text><text x="384" y="176">elige herramienta y</text><text x="384" y="190">parámetros validados</text>
  <text x="536" y="160" font-weight="700">Visualizador</text><text x="536" y="176">reglas + LLM</text><text x="536" y="190">→ gráfica</text>
  <text x="689" y="160" font-weight="700">Narrador</text><text x="689" y="176">explica, recomienda</text><text x="689" y="190">y verifica cifras</text>
  <text x="175" y="285" font-weight="700">Herramientas (13)</text>
  <text x="175" y="302">ejecutar_sql · buscar_diccionario · generar_grafica · limpiar_datos</text>
  <text x="175" y="317">transcribir_voz · exportar_reporte · detectar_alertas · pronosticar_pan</text>
  <text x="175" y="332">rentabilidad_canales · combinaciones · simular_promocion</text>
  <text x="175" y="345">lista_de_compras (Chedraui) · reporte_de_ventas</text>
  <text x="455" y="287" font-weight="700">POS en Supabase</text><text x="455" y="303">rol datavoz_lector (solo lectura)</text>
  <text x="455" y="319">↓ copia sin datos personales</text><text x="455" y="337" font-weight="700">DuckDB (solo lectura)</text>
  <text x="665" y="287" font-weight="700">ChromaDB (RAG)</text><text x="665" y="304">por negocio: diccionario,</text>
  <text x="665" y="319">reglas y ejemplos SQL</text><text x="665" y="336">embeddings locales</text>
 </g>
 <g stroke="#2B2320" stroke-width="1.3" fill="none" marker-end="url(#f)">
  <path d="M160 44 H188"/><path d="M355 44 H383"/><path d="M565 44 H593"/>
  <path d="M430 73 L90 133"/><path d="M450 73 L240 133"/><path d="M475 73 L390 133"/>
  <path d="M454 166 H464"/><path d="M606 166 H616"/>
  <path d="M80 197 V263"/><path d="M232 197 L420 263"/><path d="M384 197 L180 263"/><path d="M240 197 L640 263"/>
  <path d="M232 197 C 300 232, 470 232, 530 199"/>
  <path d="M260 135 Q 330 100 455 75" stroke-dasharray="4 3"/>
 </g>
 <text x="500" y="100" fill="#C8102E" font-size="9.5">- - - si falla o la revisión encuentra</text>
 <text x="500" y="113" fill="#C8102E" font-size="9.5">un error: reintento (≤ 2)</text>
 <text x="618" y="222" fill="#6E5F4E" font-size="9.5">resultado → Visualizador → Narrador</text>
</svg>
"""


def b64(png: bytes) -> str:
    return base64.b64encode(png).decode()


def grafica_casos(casos: list[dict]) -> str:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    datos = [(c["id"], c.get("duracion_s") or c.get("tiempo_total_s") or 0,
              next((c[k] for k in ("sql_correcto", "resultado_correcto", "correcto") if c.get(k) is not None), True))
             for c in casos]
    fig, ax = plt.subplots(figsize=(9, 2.8), dpi=150)
    ax.bar([d[0] for d in datos], [d[1] for d in datos], color=["#10B981" if d[2] else "#EF4444" for d in datos])
    ax.axhline(15, color="#0B1F3A", ls="--", lw=1)
    ax.text(len(datos) - 0.5, 15.4, "meta 15 s", ha="right", fontsize=7, color="#0B1F3A")
    ax.set_ylabel("segundos", fontsize=8)
    ax.tick_params(axis="x", labelsize=7, rotation=60)
    ax.tick_params(axis="y", labelsize=7)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    return b64(buf.getvalue())


def capturas_html(contenido: dict) -> str:
    partes = []
    n = 2
    for cap in contenido.get("capturas", []):
        ruta = DOCS / "img" / cap["archivo"]
        if not ruta.exists():
            continue
        tipo = "jpeg" if ruta.suffix.lower() in (".jpg", ".jpeg") else "png"
        partes.append(f'<figure><img src="data:image/{tipo};base64,{b64(ruta.read_bytes())}" style="width:{cap.get("ancho", "95%")}">'
                      f'<figcaption>Figura {n}. {cap["pie"]}</figcaption></figure>')
        n += 1
    if not partes:
        return "<p>La interfaz tiene cuatro pestañas: Conversación, Dashboard, Datos y Trazas.</p>"
    return contenido.get("texto_interfaz", "") + "\n".join(partes)


def filas_metricas(m: dict) -> list[tuple]:
    def si(c):
        return '<span class="ok">Sí</span>' if c else '<span class="no">No</span>'
    lim = m.get("limpieza") or {}
    mapeo = m.get("mapeo_columnas") or {}
    return [
        ("Exactitud del SQL", "≥ 85 % de casos correctos",
         f"{m['exactitud_sql']['porcentaje']} % ({m['exactitud_sql']['correctos']}/{m['exactitud_sql']['total']} casos)",
         si((m['exactitud_sql']['porcentaje'] or 0) >= 85)),
        ("Veracidad de la respuesta", "100 % de cifras verificadas",
         f"{m['veracidad']['porcentaje']} % ({m['veracidad']['cifras_verificadas']}/{m['veracidad']['cifras_total']} cifras)",
         si((m['veracidad']['porcentaje'] or 0) >= 100)),
        ("Calidad de la limpieza", "≥ 90 % de errores detectados",
         f"{lim.get('tasa_deteccion')} % detectados y {lim.get('tasa_correccion')} % corregidos de {lim.get('inyectados')} "
         f"errores; {lim.get('falsos_positivos')} falsos positivos; mapeo de columnas desconocidas "
         f"{mapeo.get('aciertos')}/{mapeo.get('total')}", si((lim.get('tasa_deteccion') or 0) >= 90)),
        ("Pertinencia de la gráfica", "Promedio ≥ 4/5", f"{m['grafica']['promedio']}/5 en {m['grafica']['casos']} casos",
         si((m['grafica']['promedio'] or 0) >= 4)),
        ("Memoria y seguimiento", "≥ 80 % correctas",
         f"{m['memoria']['porcentaje']} % ({m['memoria']['correctos']}/{m['memoria']['total']})",
         si((m['memoria']['porcentaje'] or 0) >= 80)),
        ("Entrada por voz", "≥ 90 % bien interpretadas",
         f"{m['voz']['porcentaje']} % ({m['voz']['bien_interpretadas']}/{m['voz']['total']}); similitud promedio "
         f"{m['voz']['similitud_promedio']}", si((m['voz']['porcentaje'] or 0) >= 90)),
        ("Seguridad", "0 consultas distintas de SELECT",
         f"{m['seguridad']['sentencias_no_select_ejecutadas']} ejecutadas; {m['seguridad']['casos_correctos']}/"
         f"{m['seguridad']['casos']} casos rechazados correctamente; datos intactos: "
         f"{'sí' if m['seguridad']['filas_sin_cambios'] else 'no'}",
         si(m['seguridad']['sentencias_no_select_ejecutadas'] == 0 and m['seguridad']['filas_sin_cambios'])),
        ("Tiempo de respuesta", "≤ 15 s en promedio",
         f"{m['tiempo']['promedio_s']} s promedio · mediana {m['tiempo']['mediana_s']} s · máx. {m['tiempo']['maximo_s']} s · "
         f"{m['tiempo']['llamadas_llm_promedio']} llamadas al LLM por pregunta", si((m['tiempo']['promedio_s'] or 99) <= 15)),
        *([("Confirmación humana", "100 % de las cargas con aprobación",
            f"{m['confirmacion']['propuestas_sin_escribir']}/{m['confirmacion']['cargas']} propuestas sin escribir · "
            f"{m['confirmacion']['escritas_con_aprobacion']}/{m['confirmacion']['cargas']} escritas con aprobación",
            si(m['confirmacion']['propuestas_sin_escribir'] == m['confirmacion']['escritas_con_aprobacion']
               == m['confirmacion']['cargas']))] if (m.get("confirmacion") or {}).get("cargas") else []),
        *([("Consumo", "≤ 5 llamadas por pregunta",
            f"{m['consumo']['llamadas_promedio']} llamadas · {m['consumo']['tokens_promedio']:,} tokens por pregunta",
            si((m['consumo']['llamadas_promedio'] or 99) <= 5))] if m.get("consumo") else []),
        ("Utilidad para el cliente", "≥ 4/5 en encuesta", m.get("utilidad_texto") or "Pendiente de aplicar la encuesta",
         m.get("utilidad_cumple") or "—"),
    ]


def filas_metricas_jaibo(m: dict) -> list[tuple]:
    def si(c):
        return '<span class="ok">Sí</span>' if c else '<span class="no">No</span>'
    d, ruta = m["decisiones"], m["ruta"]
    base = [f for f in filas_metricas(m) if f[0] != "Calidad de la limpieza"]
    extra = [
        ("Ruta correcta", "≥ 90 % de los casos", f"{ruta['porcentaje']} % ({ruta['correctas']}/{ruta['total']})",
         si((ruta["porcentaje"] or 0) >= 90)),
        ("Decisiones: herramienta y parámetros", "≥ 85 % de los casos",
         f"{d['porcentaje_herramienta_y_parametros']} % ({d['herramienta_correcta']}/{d['total']})",
         si((d["porcentaje_herramienta_y_parametros"] or 0) >= 85)),
        ("Decisiones: resultado", "≥ 85 % igual a la referencia",
         f"{d['porcentaje_resultado']} % ({d['resultado_correcto']}/{d['total']})", si((d["porcentaje_resultado"] or 0) >= 85)),
        ("Aviso de supuestos", "100 % de los casos con supuestos",
         f"{d['porcentaje_supuestos_declarados']} % ({d['supuestos_declarados']}/{d['con_supuestos']})",
         si((d["porcentaje_supuestos_declarados"] or 0) >= 100)),
    ]
    a = m.get("aclaracion") or {}
    if a.get("total"):
        extra.append(("Aclaración de preguntas ambiguas", "Pregunta antes de consultar",
                      f"{a['porcentaje']} % ({a['correctas']}/{a['total']})", si(a["correctas"] == a["total"])))
    return base[:1] + extra + base[1:]


def filas_casos(casos: list[dict]) -> list[dict]:
    salida = []
    for c in casos:
        if "metricas_limpieza" in c:
            ok = f'<span class="ok">{c["metricas_limpieza"]["tasa_deteccion"]} %</span>'
        elif c.get("sql_correcto") is None and "resultado_correcto" in c:  # decisión del Asesor de negocio
            ok = '<span class="ok">✔</span>' if c["resultado_correcto"] else '<span class="no">✘</span>'
        elif c.get("sql_correcto") is not None:
            ok = '<span class="ok">✔</span>' if c["sql_correcto"] else '<span class="no">✘</span>'
        else:
            ok = '<span class="ok">✔</span>' if c.get("correcto") else '<span class="no">✘</span>'
        pregunta = c.get("pregunta") or ""
        if c.get("transcripcion"):
            pregunta = f"(voz) {pregunta}"
        salida.append({"id": c["id"], "categoria": c["categoria"].replace("_", " "), "pregunta": pregunta, "ok": ok,
                       "grafica": f"{c.get('grafica') or '—'} ({c['puntaje_grafica']})" if c.get("puntaje_grafica") else "—",
                       "cifras": f"{c['cifras_verificadas']}/{c['cifras_total']}" if c.get("cifras_total") is not None else "—",
                       "tiempo": f"{(c.get('duracion_s') or c.get('tiempo_total_s') or 0):.1f} s"})
    return salida


def imprimir_pdf(html: Path, pdf: Path) -> None:
    candidatos = [shutil.which("chrome"), shutil.which("msedge"),
                  r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                  r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                  r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
                  shutil.which("google-chrome"), shutil.which("chromium")]
    navegador = next((c for c in candidatos if c and Path(c).exists()), None)
    if not navegador:
        sys.exit(f"No se encontró Chrome/Edge. Abre {html} en el navegador e imprímelo como PDF.")
    subprocess.run([navegador, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                    f"--print-to-pdf={pdf}", html.resolve().as_uri()], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--resultados-jaibo", default=str(RAIZ / "evaluacion/resultados/eval_jaibo_v6.json"))
    ap.add_argument("--resultados", default=str(RAIZ / "evaluacion/resultados/eval_v6.json"),
                    help="suite base de la tienda de abarrotes")
    ap.add_argument("--salida", default=str(DOCS / "ProyectoFinal_DataVoz.pdf"))
    args = ap.parse_args()

    res = json.loads(Path(args.resultados_jaibo).read_text(encoding="utf-8"))
    base = json.loads(Path(args.resultados).read_text(encoding="utf-8"))
    contenido = yaml.safe_load((DOCS / "contenido_documento.yaml").read_text(encoding="utf-8"))
    m, mb = res["metricas"], base["metricas"]
    for x in (m, mb):
        x["utilidad_texto"] = contenido.get("utilidad_texto")
        x["utilidad_cumple"] = contenido.get("utilidad_cumple")
    filas = m["seguridad"]["filas_antes"]
    from datavoz.herramientas import HERRAMIENTAS
    hoy = date.today()
    capturas = capturas_html(contenido)
    n_figs = 2 + capturas.count("<figure>")

    html = Template((DOCS / "plantilla_documento.html").read_text(encoding="utf-8")).render(
        repositorio=contenido.get("repositorio", "(agregar enlace de GitHub)"),
        fecha=f"{hoy.day} de {MESES[hoy.month - 1]} de {hoy.year}",
        n_casos=len(res["casos"]), n_casos_base=len(base["casos"]), m=m, mb=mb,
        etiqueta=Path(args.resultados_jaibo).stem, etiqueta_base=Path(args.resultados).stem,
        n_herramientas=len(HERRAMIENTAS), proveedor=contenido.get("proveedor", "Gemini"),
        estado_cliente=contenido.get("estado_cliente", "pendiente"),
        datos={"ordenes": f"{filas['ordenes']:,}", "renglones": f"{filas['ventas']:,}", "productos": filas["productos"]},
        diagrama=DIAGRAMA, capturas=capturas, problemas=contenido.get("problemas", []),
        filas_metricas=filas_metricas_jaibo(m), filas_metricas_base=filas_metricas(mb),
        casos=filas_casos(res["casos"]), grafica_casos=grafica_casos(res["casos"]), fig_casos=n_figs,
        trazas=contenido.get("trazas", ""), seguridad=contenido.get("seguridad", ""),
        limitaciones=contenido.get("limitaciones", ""), conclusiones=contenido.get("conclusiones", ""),
        evolucion=contenido.get("evolucion", ""), n_pruebas=contenido.get("n_pruebas", ""),
    )
    ruta_html = DOCS / "ProyectoFinal_DataVoz.html"
    ruta_html.write_text(html, encoding="utf-8")
    imprimir_pdf(ruta_html, Path(args.salida).resolve())
    print(f"Documento generado: {args.salida}")


if __name__ == "__main__":
    main()
