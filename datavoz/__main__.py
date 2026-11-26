"""Demo por terminal (sin interfaz web).

    python -m datavoz                       # conversación interactiva
    python -m datavoz "¿Cuánto vendí en diciembre?"
    python -m datavoz --audio evaluacion/audio/voz_01.wav

Comandos dentro de la conversación: /reporte, /archivo <ruta>, /memoria, /salir
"""

from __future__ import annotations

import argparse

from .sistema import SesionDataVoz
from .utilidades import tabla_markdown


def mostrar(r: dict) -> None:
    if r.get("transcripcion"):
        print(f"🎤 Transcripción: {r['transcripcion'].get('texto')}")
    if r.get("pregunta_completa") and r["pregunta_completa"] != r.get("pregunta"):
        print(f"🧭 Interpretada como: {r['pregunta_completa']}")
    print(f"\n🗣️  {r.get('respuesta')}\n")
    if r.get("sql"):
        print("SQL:", " ".join(r["sql"].split()))
    res = r.get("resultado") or {}
    if res.get("columnas"):
        print(tabla_markdown(res["columnas"], res["filas"], 10, delimitar=False))
    if r.get("grafica"):
        print(f"📊 Gráfica: {r['grafica']['spec'].get('tipo')} · {r['grafica']['spec'].get('titulo')}")
    if r.get("reporte_pdf"):
        print(f"📄 Reporte: {r['reporte_pdf']}")
    pasos = " → ".join(f"{p['agente']}" for p in r.get("pasos") or [])
    print(f"⏱️  {r.get('duracion_s')} s · {len(r.get('llamadas_llm') or [])} llamadas al LLM · {pasos}\n")


def main() -> None:
    ap = argparse.ArgumentParser(description="DataVoz por terminal")
    ap.add_argument("pregunta", nargs="?", help="pregunta a responder (si se omite, modo interactivo)")
    ap.add_argument("--audio", help="ruta a una nota de voz")
    args = ap.parse_args()
    s = SesionDataVoz()
    if args.audio or args.pregunta:
        mostrar(s.preguntar(args.pregunta, audio=args.audio))
        return
    print("DataVoz · Háblale a tus datos. Escribe tu pregunta (/salir para terminar).")
    while True:
        try:
            texto = input("\n🧑 > ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not texto:
            continue
        if texto in ("/salir", "/exit"):
            break
        if texto == "/reporte":
            mostrar(s.exportar_reporte())
        elif texto.startswith("/archivo "):
            mostrar(s.cargar_archivo(texto.split(" ", 1)[1].strip().strip('"')))
        elif texto == "/memoria":
            m = s.estado()
            print({"turnos": len(m["historial"]), "contexto": m["contexto"], "dashboard": len(m["dashboard"]),
                   "datos": m["datos"].get("origen")})
        else:
            mostrar(s.preguntar(texto))


if __name__ == "__main__":
    main()
