"""Genera docs/PROMPTS.md: instrucciones de sistema vigentes de cada agente y versiones descartadas (requisito R4).

Uso:  python docs/generar_prompts.py

Fuentes:
  - datavoz/agentes/prompts.py         prompts vigentes (el código es la fuente de verdad)
  - datavoz/seguridad.py (REGLA_DATOS) regla que se agrega al prompt de sistema de todos los agentes
  - docs/prompts/historial/*.py        versiones anteriores completas
  - docs/prompts/cambios.yaml          fecha, cambio, motivo y evidencia de cada versión
Vuelve a correrlo cada vez que cambie un prompt (y agrega la versión a cambios.yaml).
"""

from __future__ import annotations

import ast
import difflib
import sys
from pathlib import Path

import yaml

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
DOCS = RAIZ / "docs"
HISTORIAL = DOCS / "prompts" / "historial"

AGENTES = [  # constante, agente, archivo donde se usa, qué recibe, qué devuelve
    ("ORQUESTADOR", "Orquestador", "agentes/orquestador.py",
     "mensaje, historial, contexto y datos disponibles", "JSON: intención, pregunta completa, contexto, análisis"),
    ("ANALISTA_SQL", "Analista SQL", "agentes/analista_sql.py",
     "pregunta, esquema, RAG, productos y categorías detectados, intentos fallidos", "JSON: SQL, consultas de apoyo"),
    ("ASESOR", "Asesor de negocio", "agentes/asesor_negocio.py",
     "pregunta de decisión, análisis elegido, productos del menú, fecha", "JSON: herramienta y parámetros (validados con reglas)"),
    ("VISUALIZADOR", "Visualizador", "agentes/visualizador.py",
     "pregunta, columnas y primeras filas (solo si la gráfica es ambigua)", "JSON: tipo de gráfica y ejes"),
    ("NARRADOR", "Narrador", "agentes/narrador.py",
     "resultado, consultas de apoyo, hechos calculados, reglas del negocio", "texto con «Recomendación:» (cifras verificadas)"),
    ("LIMPIADOR_MAPEO", "Limpiador (mapeo)", "agentes/limpiador.py",
     "perfil de las columnas del archivo", "JSON: columna del archivo → columna estándar"),
    ("LIMPIADOR_RESUMEN", "Limpiador (resumen)", "agentes/limpiador.py",
     "reporte de limpieza ya aplicado", "texto para el dueño"),
]


def constantes(codigo: str) -> dict[str, str]:
    """Constantes de texto de un archivo de prompts (sin ejecutarlo)."""
    valores = {}
    for nodo in ast.parse(codigo).body:
        if isinstance(nodo, ast.Assign) and isinstance(nodo.value, ast.Constant) and isinstance(nodo.value.value, str):
            for objetivo in nodo.targets:
                if isinstance(objetivo, ast.Name) and objetivo.id.isupper():
                    valores[objetivo.id] = nodo.value.value
    return valores


def diferencias(antes: dict, despues: dict) -> list[str]:
    partes = []
    for nombre in list(antes) + [n for n in despues if n not in antes]:
        a, d = antes.get(nombre, ""), despues.get(nombre, "")
        if a == d:
            continue
        estado = "nuevo" if not a else ("eliminado" if not d else "modificado")
        diff = difflib.unified_diff(a.splitlines(), d.splitlines(), "descartado", "nuevo", lineterm="", n=1)
        partes.append(f"**{nombre}** ({estado})\n\n```diff\n" + "\n".join(list(diff)[2:]) + "\n```")
    return partes


def main() -> None:
    from datavoz.agentes import prompts
    from datavoz.seguridad import REGLA_DATOS

    vigentes = constantes((RAIZ / "datavoz/agentes/prompts.py").read_text(encoding="utf-8"))
    cambios = yaml.safe_load((DOCS / "prompts/cambios.yaml").read_text(encoding="utf-8"))["versiones"]
    versiones = {int(p.stem.split("_v")[1]): constantes(p.read_text(encoding="utf-8"))
                 for p in sorted(HISTORIAL.glob("prompts_v*.py"))}
    ultima = max(v["version"] for v in cambios)

    md = ["# Prompts de los agentes de DataVoz",
          "",
          "Documento generado con `python docs/generar_prompts.py` (no editar a mano). Cumple el requisito R4: "
          "instrucciones de sistema de cada agente y versiones descartadas con su motivo.",
          "",
          f"- **Versión vigente:** {ultima} ({next(v['fecha'] for v in cambios if v['version'] == ultima)}). "
          "Fuente: `datavoz/agentes/prompts.py`.",
          "- **Versiones anteriores completas:** `docs/prompts/historial/prompts_vNN.py`. Las versiones 1 a 9 se "
          "reconstruyeron de las sesiones de desarrollo aplicando cada cambio en orden; la versión 9 coincide byte a "
          "byte con el archivo del commit `1e2caea`.",
          "- **Qué NO hace el LLM:** los cálculos de decisión, las fechas, la validación del SQL y la verificación de "
          "cifras se hacen con código; el modelo solo clasifica, genera SQL, elige herramientas, gráficas y redacta.",
          "",
          "## Agentes y prompts vigentes", "",
          "| Agente | Prompt | Código | Recibe | Devuelve |", "|---|---|---|---|---|"]
    for constante, agente, archivo, recibe, devuelve in AGENTES:
        md.append(f"| {agente} | `{constante}` | `datavoz/{archivo}` | {recibe} | {devuelve} |")
    md += ["", "Además, `datavoz/llm.py` agrega a **todos** los prompts de sistema la regla de seguridad "
           "`REGLA_DATOS` (versión 11):", "", "```text", REGLA_DATOS.strip(), "```", ""]
    for constante, agente, *_ in AGENTES:
        texto = getattr(prompts, constante)
        md += [f"### {agente} · `{constante}`", "", "```text", texto.strip(), "```", ""]

    md += ["## Registro de versiones", "",
           "| Versión | Fecha | Cambio | Motivo | Evidencia |", "|---|---|---|---|---|"]
    for v in cambios:
        md.append(f"| {v['version']} | {v['fecha']} | {v['cambio']} | {v['motivo']} | {v['evidencia']} |")
    md += ["", "## Versiones descartadas (texto anterior → texto nuevo)", "",
           "Solo se muestran las líneas que cambiaron. Las líneas con `-` son el texto descartado."]
    for v in cambios:
        n = v["version"]
        if n == 1 or v.get("sin_cambio_en_prompts_py"):
            continue
        antes = versiones.get(n - 1)
        despues = versiones.get(n) or (vigentes if n == ultima else None)
        if antes is None or despues is None:
            continue
        md += ["", f"### Versión {n - 1} → {n} ({v['fecha']})", "", f"**Por qué:** {v['motivo']}", ""]
        if v.get("descartado"):
            md += [f"**Se descartó:** {v['descartado']}", ""]
        md += diferencias(antes, despues)
    ultima_archivada = max(versiones)
    if versiones[ultima_archivada] != vigentes:
        md += ["", f"### Versión {ultima_archivada} → vigente", ""] + diferencias(versiones[ultima_archivada], vigentes)
    (DOCS / "PROMPTS.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"Generado {DOCS / 'PROMPTS.md'}")


if __name__ == "__main__":
    main()
