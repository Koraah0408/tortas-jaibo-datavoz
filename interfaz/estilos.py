"""Hoja de estilos y componentes HTML de la interfaz de Tortas Jaibo (colores del menú: mantequilla, rojo y carbón)."""

from __future__ import annotations

import html

from .iconos import icono, jaiba

ROJO = "#C8102E"
ROJO_OSCURO = "#A00D25"
CREMA = "#FFF8EA"
MANTEQUILLA = "#F7E3A6"
MANTEQUILLA_SUAVE = "#FCEFCB"
CARBON = "#2B2320"
TEXTO_SUAVE = "#6E5F4E"
BORDE = "#EAD7A4"
VERDE = "#3F7F2C"

CSS = f"""
<style>
  .block-container {{ padding-top: 1.6rem; max-width: 1120px; }}
  h1, h2, h3, h4 {{ color:{CARBON}; letter-spacing:-.01em; }}

  /* ---------- Barra lateral ---------- */
  .jb-marca {{ display:flex; align-items:center; gap:12px; margin:-8px 0 14px; }}
  .jb-marca .nombre {{ font-weight:800; font-size:1.28rem; color:{CARBON}; letter-spacing:.06em; line-height:1.05; }}
  .jb-marca .nombre span {{ color:{ROJO}; }}
  .jb-marca .lema {{ font-size:.74rem; color:{TEXTO_SUAVE}; font-style:italic; margin-top:3px; }}
  .jb-seccion {{ display:flex; align-items:center; gap:7px; margin:18px 0 6px; font-size:.7rem; font-weight:700;
                 letter-spacing:.09em; text-transform:uppercase; color:#8A6A2E; }}
  .jb-seccion svg {{ color:{ROJO}; }}
  .jb-chip {{ display:flex; gap:9px; align-items:flex-start; padding:9px 11px; border-radius:12px; font-size:.8rem;
              background:#FFFDF6; border:1px solid #E3C67A; color:{CARBON}; line-height:1.4; }}
  .jb-chip svg {{ flex:none; margin-top:2px; color:{ROJO}; }}
  .jb-chip.demo {{ background:#FFF1D0; border-style:dashed; }}
  .jb-chip.error {{ background:#FDECEC; border-color:#E8A0A8; }}
  .jb-nota {{ font-size:.74rem !important; color:{TEXTO_SUAVE}; margin:6px 0 2px; line-height:1.45; }}

  /* ---------- Encabezado ---------- */
  .jb-hero {{ display:flex; justify-content:space-between; align-items:flex-end; gap:16px; flex-wrap:wrap;
              margin:0 0 14px; }}
  .jb-hero .titulo {{ font-size:1.7rem; font-weight:700; margin:0; color:{CARBON}; line-height:1.25; }}
  .jb-hero .titulo .rojo {{ color:{ROJO}; }}
  .jb-hero p {{ margin:4px 0 0; color:{TEXTO_SUAVE}; font-size:.92rem; }}
  .jb-fuente {{ display:inline-flex; gap:8px; align-items:center; padding:7px 13px; border-radius:999px;
                background:#FFFFFF; border:1px solid {BORDE}; color:{CARBON}; font-size:.8rem; white-space:nowrap; }}
  .jb-fuente svg {{ color:{ROJO}; }}
  .jb-fuente.demo {{ background:#FFF1D0; border-style:dashed; }}

  /* ---------- Indicadores ---------- */
  .jb-kpis {{ display:grid; grid-template-columns:repeat(4, minmax(0,1fr)); gap:12px; margin:0 0 18px; }}
  @media (max-width: 900px) {{ .jb-kpis {{ grid-template-columns:repeat(2, minmax(0,1fr)); }} }}
  .jb-kpi {{ background:#FFFFFF; border:1px solid {BORDE}; border-radius:16px; padding:14px 16px;
             box-shadow:0 1px 2px rgba(80,50,10,.05); }}
  .jb-kpi .arriba {{ display:flex; align-items:center; gap:10px; }}
  .jb-kpi .ico {{ width:36px; height:36px; border-radius:10px; background:{MANTEQUILLA_SUAVE}; color:{ROJO};
                  display:flex; align-items:center; justify-content:center; flex:none; }}
  .jb-kpi .rotulo {{ font-size:.76rem; color:{TEXTO_SUAVE}; line-height:1.25; }}
  .jb-kpi .valor {{ font-size:1.45rem; font-weight:700; color:{CARBON}; margin-top:8px; line-height:1.1;
                    font-variant-numeric:tabular-nums; }}
  .jb-kpi .cambio {{ display:flex; flex-wrap:wrap; align-items:center; gap:2px 6px; font-size:.74rem; margin-top:4px;
                     color:{TEXTO_SUAVE}; }}
  .jb-kpi .cambio .num {{ display:inline-flex; align-items:center; gap:2px; font-weight:600; white-space:nowrap; }}
  .jb-kpi .cambio .vs {{ color:{TEXTO_SUAVE}; font-weight:400; }}
  .jb-kpi .cambio.sube {{ color:{VERDE}; }} .jb-kpi .cambio.baja {{ color:{ROJO_OSCURO}; }}

  /* ---------- Acciones principales (bienvenida) ---------- */
  .jb-bienvenida h3 {{ margin:6px 0 2px; font-size:1.1rem; }}
  .jb-bienvenida p {{ margin:0 0 12px; color:{TEXTO_SUAVE}; font-size:.9rem; }}
  [class*="st-key-accion_"] {{ background:#FFFFFF; border:1px solid {BORDE}; border-radius:18px; padding:16px 16px 12px;
                               box-shadow:0 1px 2px rgba(80,50,10,.05); transition:box-shadow .15s, border-color .15s; }}
  [class*="st-key-accion_"]:hover {{ border-color:{ROJO}; box-shadow:0 6px 18px rgba(200,16,46,.10); }}
  .jb-accion .ico {{ width:44px; height:44px; border-radius:12px; background:{ROJO}; color:#FFFFFF; display:flex;
                     align-items:center; justify-content:center; margin-bottom:10px; }}
  .jb-accion .titulo {{ font-weight:700; font-size:1rem; color:{CARBON}; line-height:1.25; }}
  .jb-accion .desc {{ font-size:.82rem; color:{TEXTO_SUAVE}; margin-top:4px; line-height:1.4; min-height:4.2em; }}
  [class*="st-key-chips"] button {{ background:{MANTEQUILLA_SUAVE}; border:1px solid {BORDE}; border-radius:999px;
                                    color:{CARBON}; font-size:.84rem; min-height:38px; padding:4px 14px; }}
  [class*="st-key-chips"] button:hover {{ border-color:{ROJO}; color:{ROJO_OSCURO}; background:#FFFFFF; }}
  [class*="st-key-chips"] button p {{ white-space:normal !important; line-height:1.3; }}
  .jb-seguir {{ display:flex; align-items:center; gap:6px; font-size:.78rem; color:{TEXTO_SUAVE}; margin:10px 0 2px; }}
  .jb-seguir svg {{ color:{ROJO}; }}

  /* ---------- Resumen de la semana (una sola línea, sin tarjetas) ---------- */
  .jb-resumen {{ display:flex; flex-wrap:wrap; align-items:center; gap:6px 14px; margin:2px 0 18px; font-size:.9rem;
                 color:{TEXTO_SUAVE}; }}
  .jb-resumen .etq {{ background:{MANTEQUILLA}; color:{CARBON}; border-radius:999px; padding:3px 11px; font-size:.76rem;
                      font-weight:600; }}
  .jb-resumen b {{ color:{CARBON}; }}
  .jb-resumen .sube {{ color:{VERDE}; font-weight:600; }} .jb-resumen .baja {{ color:{ROJO_OSCURO}; font-weight:600; }}
  .jb-resumen .dato {{ display:inline-flex; align-items:center; gap:4px; white-space:nowrap; }}

  /* ---------- Conversación ---------- */
  [data-testid="stChatMessage"] {{ background:#FFFFFF; border:1px solid {BORDE}; border-radius:16px; padding:14px 18px;
                                   animation:jbEntrada .45s cubic-bezier(.2,.8,.2,1) both; }}
  /* Tus mensajes: globo a la derecha, color mantequilla */
  [data-testid="stChatMessage"]:has(.jb-msg-usuario) {{ background:{MANTEQUILLA}; border-color:#E8C878; flex-direction:row-reverse;
      margin-left:auto; max-width:min(78%, 640px); width:fit-content; border-radius:18px 18px 4px 18px; padding:10px 16px;
      animation-name:jbEntradaDerecha; }}
  [data-testid="stChatMessage"]:has(.jb-msg-usuario) [data-testid="stChatMessageContent"] {{ text-align:right; }}
  /* Respuestas del asistente: tarjeta blanca con la orilla roja de Jaibo */
  [data-testid="stChatMessage"]:has(.jb-msg-asistente) {{ border-left:4px solid {ROJO}; border-radius:6px 18px 18px 18px;
      box-shadow:0 2px 10px rgba(80,50,10,.06); }}
  .jb-msg-asistente .quien, .jb-msg-usuario .quien {{ font-size:.72rem; font-weight:700; letter-spacing:.06em;
      text-transform:uppercase; }}
  .jb-msg-asistente .quien {{ color:{ROJO}; }} .jb-msg-usuario .quien {{ color:#8A6A2E; }}
  @keyframes jbEntrada {{ from {{ opacity:0; transform:translateY(12px); }} to {{ opacity:1; transform:none; }} }}
  @keyframes jbEntradaDerecha {{ from {{ opacity:0; transform:translateX(18px); }} to {{ opacity:1; transform:none; }} }}
  @keyframes jbBrillo {{ 0% {{ box-shadow:0 0 0 0 rgba(200,16,46,.35); }} 100% {{ box-shadow:0 0 0 12px rgba(200,16,46,0); }} }}
  @keyframes jbLatido {{ 0%,100% {{ transform:scale(1); }} 50% {{ transform:scale(1.12); }} }}
  @keyframes jbAparece {{ from {{ opacity:0; transform:translateY(8px) scale(.98); }} to {{ opacity:1; transform:none; }} }}
  .jb-reco {{ animation:jbAparece .5s .15s both, jbBrillo 1.2s .5s 1; }}
  [class*="st-key-accion_"] {{ animation:jbAparece .5s both; }}
  .st-key-accion_1 {{ animation-delay:.06s; }} .st-key-accion_2 {{ animation-delay:.12s; }} .st-key-accion_3 {{ animation-delay:.18s; }}
  [class*="st-key-accion_"]:hover {{ transform:translateY(-3px); }}
  [class*="st-key-accion_"] .jb-accion .ico {{ transition:transform .2s; }}
  [class*="st-key-accion_"]:hover .jb-accion .ico {{ transform:rotate(-6deg) scale(1.08); }}
  [class*="st-key-chips"] button {{ transition:transform .15s, background .15s, border-color .15s; }}
  [class*="st-key-chips"] button:hover {{ transform:translateY(-2px); }}
  .jb-kpi, .jb-resumen {{ animation:jbAparece .45s both; }}
  [data-testid="stStatusWidget"], [data-testid="stExpander"] details summary svg {{ transition:transform .2s; }}
  .jb-marca svg {{ animation:jbLatido 2.4s ease-in-out 1; }}
  [data-testid="stExpander"]:has(.jb-pensando) summary {{ color:{ROJO}; }}
  @media (prefers-reduced-motion: reduce) {{ *, *::before, *::after {{ animation:none !important; transition:none !important; }} }}
  .jb-reco {{ display:flex; gap:10px; align-items:flex-start; background:#FFF4D6; border:1px solid #F0D58C;
              border-left:4px solid {ROJO}; border-radius:12px; padding:10px 14px; margin:6px 0 4px; color:{CARBON};
              font-size:.93rem; line-height:1.45; }}
  .jb-reco svg {{ flex:none; color:{ROJO}; margin-top:2px; }}
  .jb-reco b {{ color:{ROJO_OSCURO}; }}
  .jb-verif {{ display:inline-flex; gap:6px; align-items:center; font-size:.78rem; color:{TEXTO_SUAVE}; margin-top:4px; }}
  .jb-verif.ok svg {{ color:{VERDE}; }} .jb-verif.no svg {{ color:{ROJO}; }}
  .jb-paso {{ display:flex; gap:10px; align-items:center; padding:7px 0; border-bottom:1px solid #F3E7C8; font-size:.86rem; }}
  .jb-paso .agente {{ font-weight:600; color:{CARBON}; min-width:130px; }}
  .jb-paso .accion {{ color:{TEXTO_SUAVE}; flex:1; }}
  .jb-paso .tiempo {{ color:{CARBON}; font-variant-numeric:tabular-nums; }}
  .jb-paso svg {{ color:{ROJO}; flex:none; }}
  .jb-tarjeta-titulo {{ display:flex; gap:8px; align-items:center; font-weight:600; color:{CARBON}; }}
  .jb-tarjeta-titulo svg {{ color:{ROJO}; }}
  [data-testid="stChatInput"] textarea {{ font-size:.95rem; }}
</style>
"""


def marca() -> str:
    return (f'<div class="jb-marca">{jaiba(46)}<div><div class="nombre">TORTAS <span>JAIBO</span></div>'
            f'<div class="lema">Un pedacito de Tampico en Carmen</div></div></div>')


def seccion(nombre_icono: str, texto: str) -> str:
    return f'<div class="jb-seccion">{icono(nombre_icono, 14)}<span>{html.escape(texto)}</span></div>'


def chip(nombre_icono: str, texto: str, error: bool = False, demo: bool = False) -> str:
    clase = " error" if error else (" demo" if demo else "")
    return f'<div class="jb-chip{clase}">{icono(nombre_icono, 15)}<span>{texto}</span></div>'


def encabezado(titulo_html: str, subtitulo: str, fuente: str, demo: bool = False) -> str:
    return (f'<div class="jb-hero"><div><div class="titulo">{titulo_html}</div><p>{html.escape(subtitulo)}</p></div>'
            f'<div class="jb-fuente{" demo" if demo else ""}">{icono("datos", 15)}<span>{html.escape(fuente)}</span></div></div>')


def kpis(items: list[tuple[str, str, str, float | None]]) -> str:
    """(icono, rótulo, valor, cambio % contra la semana anterior o None)."""
    tarjetas = []
    for ico, rot, val, cambio in items:
        linea = ""
        if cambio is not None:
            clase, flecha = ("sube", "sube") if cambio >= 0 else ("baja", "bajo")
            linea = (f'<div class="cambio {clase}"><span class="num">{icono(flecha, 13, 2.2)}{abs(cambio):.0f}&nbsp;%</span>'
                     f'<span class="vs">vs. semana anterior</span></div>')
        tarjetas.append(f'<div class="jb-kpi"><div class="arriba"><div class="ico">{icono(ico, 19)}</div>'
                        f'<div class="rotulo">{html.escape(rot)}</div></div><div class="valor">{html.escape(val)}</div>'
                        f'{linea}</div>')
    return f'<div class="jb-kpis">{"".join(tarjetas)}</div>'


def resumen_semana(items: list[tuple[str, str, float | None]]) -> str:
    """Una línea discreta: «Últimos 7 días · $12,768 en ventas ▲2 % · 89 órdenes ▲9 % · …»."""
    partes = []
    for valor, rotulo, cambio in items:
        flecha = ""
        if cambio is not None:
            clase, nombre = ("sube", "sube") if cambio >= 0 else ("baja", "bajo")
            flecha = f'<span class="{clase}">{icono(nombre, 12, 2.4)}{abs(cambio):.0f}&nbsp;%</span>'
        partes.append(f'<span class="dato"><b>{html.escape(valor)}</b>&nbsp;{html.escape(rotulo)} {flecha}</span>')
    return f'<div class="jb-resumen"><span class="etq">Últimos 7 días</span>{"".join(partes)}</div>'


def marca_mensaje(rol: str) -> str:
    """Marca invisible + rótulo que permite dar estilo distinto a tus mensajes y a los del asistente."""
    if rol == "user":
        return '<div class="jb-msg-usuario"><span class="quien">Tú</span></div>'
    return '<div class="jb-msg-asistente"><span class="quien">Asistente Jaibo</span></div>'


def seguir() -> str:
    return f'<div class="jb-seguir">{icono("chat", 14)}<span>Puedes seguir con:</span></div>'


def accion(nombre_icono: str, titulo: str, descripcion: str) -> str:
    return (f'<div class="jb-accion"><div class="ico">{icono(nombre_icono, 24, 2)}</div>'
            f'<div class="titulo">{html.escape(titulo)}</div><div class="desc">{html.escape(descripcion)}</div></div>')


def recomendacion(texto: str) -> str:
    return (f'<div class="jb-reco">{icono("foco", 18, 2)}<div><b>Recomendación:</b> {html.escape(texto)}</div></div>')


def verificacion(ok: bool, texto: str) -> str:
    return f'<span class="jb-verif {"ok" if ok else "no"}">{icono("verificado" if ok else "aviso", 15)}{html.escape(texto)}</span>'


def paso(agente: str, accion_txt: str, tiempo: str, nombre_icono: str = "agentes") -> str:
    return (f'<div class="jb-paso">{icono(nombre_icono, 16)}<span class="agente">{html.escape(agente)}</span>'
            f'<span class="accion">{html.escape(accion_txt)}</span><span class="tiempo">{html.escape(tiempo)}</span></div>')


def titulo_tarjeta(nombre_icono: str, texto: str) -> str:
    return f'<div class="jb-tarjeta-titulo">{icono(nombre_icono, 17)}<span>{html.escape(texto)}</span></div>'
