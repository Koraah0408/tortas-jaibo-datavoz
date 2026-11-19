"""Genera docs/ProyectoFinal_DataVoz.pdf a partir de la plantilla HTML y de los resultados de la evaluación.

Uso:
    python docs/generar_documento.py --resultados evaluacion/resultados/eval_v1.json

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
<svg viewBox="0 0 760 340" width="100%" xmlns="http://www.w3.org/2000/svg" font-family="Segoe UI, Arial" font-size="11">
 <defs><marker id="f" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto">
   <path d="M0,0 L10,5 L0,10 z" fill="#0B1F3A"/></marker></defs>
 <g stroke="#0E7C86" stroke-width="1.5" fill="#EEF4FE">
  <rect x="10" y="15" width="150" height="58" rx="8"/><rect x="190" y="15" width="160" height="58" rx="8" fill="#0B1F3A"/>
  <rect x="380" y="15" width="170" height="58" rx="8" fill="#0E7C86"/><rect x="580" y="15" width="170" height="58" rx="8"/>
  <rect x="10" y="130" width="170" height="62" rx="8"/><rect x="200" y="130" width="170" height="62" rx="8"/>
  <rect x="390" y="130" width="170" height="62" rx="8"/><rect x="580" y="130" width="170" height="62" rx="8"/>
  <rect x="10" y="255" width="360" height="72" rx="8"/><rect x="390" y="255" width="170" height="72" rx="8"/>
  <rect x="580" y="255" width="170" height="72" rx="8"/>
 </g>
 <g text-anchor="middle" fill="#0B1F3A">
  <text x="85" y="38" font-weight="700">Usuario</text><text x="85" y="55">texto · voz · CSV/Excel</text>
  <text x="270" y="38" font-weight="700" fill="#fff">Interfaz web</text><text x="270" y="55" fill="#fff">Streamlit · chat + dashboard</text>
  <text x="465" y="36" font-weight="700" fill="#fff">Orquestador (supervisor)</text>
  <text x="465" y="52" fill="#fff">intención · contexto · valida</text><text x="465" y="66" fill="#fff">transcribir_voz · alertas</text>
  <text x="665" y="38" font-weight="700">Memoria</text><text x="665" y="55">historial + resumen de contexto</text>
  <text x="95" y="155" font-weight="700">Limpiador</text><text x="95" y="171">mapea columnas, corrige</text><text x="95" y="185">y carga a DuckDB</text>
  <text x="285" y="155" font-weight="700">Analista SQL</text><text x="285" y="171">RAG → SELECT → ejecuta</text><text x="285" y="185">+ consultas de apoyo</text>
  <text x="475" y="155" font-weight="700">Visualizador</text><text x="475" y="171">reglas + LLM si es ambiguo</text><text x="475" y="185">→ gráfica al dashboard</text>
  <text x="665" y="155" font-weight="700">Narrador</text><text x="665" y="171">explica, recomienda y</text><text x="665" y="185">verifica cada cifra</text>
  <text x="190" y="280" font-weight="700">Herramientas</text>
  <text x="190" y="298">limpiar_datos · ejecutar_sql (solo SELECT) · buscar_diccionario</text>
  <text x="190" y="314">generar_grafica · transcribir_voz · exportar_reporte · detectar_alertas</text>
  <text x="475" y="282" font-weight="700">DuckDB</text><text x="475" y="299">ventas · productos · inventario</text><text x="475" y="314">promociones (solo lectura)</text>
  <text x="665" y="282" font-weight="700">ChromaDB (RAG)</text><text x="665" y="299">diccionario · reglas</text><text x="665" y="314">catálogo · ejemplos SQL</text>
 </g>
 <g stroke="#0B1F3A" stroke-width="1.3" fill="none" marker-end="url(#f)">
  <path d="M160 44 H188"/><path d="M350 44 H378"/><path d="M550 44 H578"/>
  <path d="M430 73 L110 128"/><path d="M450 73 L300 128"/><path d="M475 73 V128"/><path d="M500 73 L650 128"/>
  <path d="M95 192 V253"/><path d="M285 192 V253"/><path d="M475 192 V253"/><path d="M665 192 V253"/>
  <path d="M360 192 Q 400 230 545 192" stroke-dasharray="4 3"/>
 </g>
 <text x="300" y="222" fill="#B42318" font-size="10">si falla o está vacío: reintento (≤ 2) con el error</text>
 <text x="560" y="210" fill="#5B6472" font-size="10">resultado →</text>
</svg>
"""


def b64(png: bytes) -> str:
    return base64.b64encode(png).decode()


def grafica_casos(casos: list[dict]) -> str:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    datos = [(c["id"], c.get("duracion_s") or c.get("tiempo_total_s") or 0,
              c.get("sql_correcto", c.get("correcto", True))) for c in casos]
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
        ("Utilidad para el cliente", "≥ 4/5 en encuesta", m.get("utilidad_texto") or "Pendiente de aplicar la encuesta",
         m.get("utilidad_cumple") or "—"),
    ]


def filas_casos(casos: list[dict]) -> list[dict]:
    salida = []
    for c in casos:
        if "metricas_limpieza" in c:
            ok = f'<span class="ok">{c["metricas_limpieza"]["tasa_deteccion"]} %</span>'
        elif "sql_correcto" in c:
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
    ap.add_argument("--resultados", required=True)
    ap.add_argument("--salida", default=str(DOCS / "ProyectoFinal_DataVoz.pdf"))
    args = ap.parse_args()

    res = json.loads(Path(args.resultados).read_text(encoding="utf-8"))
    contenido = yaml.safe_load((DOCS / "contenido_documento.yaml").read_text(encoding="utf-8"))
    m = res["metricas"]
    m["utilidad_texto"] = contenido.get("utilidad_texto")
    m["utilidad_cumple"] = contenido.get("utilidad_cumple")

    from datavoz.basedatos import resumen_ventas, ejecutar_select
    from datavoz.config import obtener_config
    rv = resumen_ventas(obtener_config().ruta_db)
    tickets = ejecutar_select("SELECT COUNT(DISTINCT ticket) FROM ventas").filas[0][0]
    hoy = date.today()
    capturas = capturas_html(contenido)
    n_figs = 2 + capturas.count("<figure>")

    html = Template((DOCS / "plantilla_documento.html").read_text(encoding="utf-8")).render(
        repositorio=contenido.get("repositorio", "(agregar enlace de GitHub)"),
        fecha=f"{hoy.day} de {MESES[hoy.month - 1]} de {hoy.year}",
        n_casos=len(res["casos"]), m=m, proveedor=contenido.get("proveedor", "Gemini 2.5 Flash"),
        estado_cliente=contenido.get("estado_cliente", "pendiente"),
        datos={"renglones": f"{rv['renglones']:,}", "tickets": f"{tickets:,}"},
        diagrama=DIAGRAMA, capturas=capturas, problemas=contenido.get("problemas", []),
        filas_metricas=filas_metricas(m), casos=filas_casos(res["casos"]),
        grafica_casos=grafica_casos(res["casos"]), fig_casos=n_figs,
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
