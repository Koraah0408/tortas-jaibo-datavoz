"""Grafo LangGraph de DataVoz: patrón supervisor con flujo secuencial y ciclos de corrección.

                    ┌──────────────┐
          archivo → │  Limpiador   │──────────────────────────────┐
                    └──────────────┘                              │
 START ─┬─ audio → transcribir ─┐                                 │
        └────────────────────── ▼                                 ▼
                         ┌─────────────┐  consulta  ┌──────────────┐     ┌────────────┐
                         │ Orquestador │──────────▶ │ Analista SQL │ ──▶ │ Supervisor │
                         └─────────────┘            └──────────────┘ ◀── └────────────┘
                            │ reporte │ otra            ▲  reintentar (≤2)   │ continuar │ aclarar
                            │ decisión (Jaibo) → Asesor de negocio (herramientas) ──▶ Visualizador
                            ▼         ▼               └────────────────────┘           │
                       exportar   responder ◀──────────────────────────────────────────┘
                            │         │          Visualizador ──▶ Narrador
                            ▼         ▼                                │
                         ┌──────────────────────── memoria ◀───────────┘
                         ▼
                        END
"""

from __future__ import annotations

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from .agentes.analista_sql import analista_sql
from .agentes.asesor_negocio import asesor_negocio, ruta_asesor
from .agentes.base import EstadoDataVoz
from .agentes.limpiador import limpiador
from .agentes.narrador import narrador
from .agentes.orquestador import (actualizar_memoria, exportar, orquestar, responder, ruta_inicio,
                                  ruta_intencion, ruta_supervisor, supervisar, transcribir)
from .agentes.visualizador import visualizador


def construir_grafo(checkpointer=None):
    g = StateGraph(EstadoDataVoz)
    g.add_node("transcribir", transcribir)
    g.add_node("orquestador", orquestar)
    g.add_node("limpiador", limpiador)
    g.add_node("analista_sql", analista_sql)
    g.add_node("supervisor", supervisar)
    g.add_node("asesor_negocio", asesor_negocio)
    g.add_node("visualizador", visualizador)
    g.add_node("narrador", narrador)
    g.add_node("responder", responder)
    g.add_node("exportar", exportar)
    g.add_node("memoria", actualizar_memoria)

    g.add_conditional_edges(START, ruta_inicio, ["limpiador", "transcribir", "orquestador"])
    g.add_edge("transcribir", "orquestador")
    g.add_conditional_edges("orquestador", ruta_intencion, ["analista_sql", "asesor_negocio", "exportar", "responder"])
    g.add_conditional_edges("asesor_negocio", ruta_asesor, ["visualizador", "narrador", "responder"])
    g.add_edge("analista_sql", "supervisor")
    g.add_conditional_edges("supervisor", ruta_supervisor, ["analista_sql", "responder", "visualizador", "narrador"])
    g.add_edge("visualizador", "narrador")
    g.add_edge("narrador", "memoria")
    g.add_edge("limpiador", "memoria")
    g.add_edge("responder", "memoria")
    g.add_edge("exportar", "memoria")
    g.add_edge("memoria", END)
    return g.compile(checkpointer=checkpointer if checkpointer is not None else InMemorySaver())
