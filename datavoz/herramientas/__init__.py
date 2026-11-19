"""Herramientas de los agentes de DataVoz, registradas como herramientas de LangChain.

| Herramienta         | Agente que la usa       |
|---------------------|-------------------------|
| limpiar_datos       | Limpiador               |
| ejecutar_sql        | Analista SQL            |
| buscar_diccionario  | Analista SQL, Narrador  |
| generar_grafica     | Visualizador            |
| transcribir_voz     | Orquestador             |
| exportar_reporte    | Narrador                |
| detectar_alertas    | Orquestador (ideal)     |
| pronosticar_pan     | Asesor de negocio       |
| rentabilidad_canales| Asesor de negocio       |
| combinaciones_frecuentes | Asesor de negocio  |
| simular_promocion   | Asesor de negocio       |

Cada agente invoca sus herramientas con ``herramienta.invoke({...})`` dentro de su
nodo del grafo, de modo que cada uso queda registrado en la traza (y en
LangSmith si está activado).
"""

from __future__ import annotations

from langchain_core.tools import StructuredTool

from ..basedatos import ejecutar_select
from ..rag import obtener_base
from .detectar_alertas import detectar_alertas
from .exportar_reporte import exportar_reporte
from .generar_grafica import generar_grafica
from .limpiar_datos import limpiar_datos
from . import negocio_jaibo
from .transcribir_voz import transcribir_voz


def _ejecutar_sql(sql: str, ruta_db: str) -> dict:
    """Ejecuta UNA consulta SELECT de solo lectura (con límite de tiempo y filas) y devuelve el resultado."""
    return ejecutar_select(sql, ruta_db).a_dict()


def _buscar_diccionario(consulta: str, tipos: list[str] | None = None, k: int = 4,
                        dominio: str | None = None) -> list[dict]:
    """Busca en el diccionario de datos, reglas del negocio, catálogo y ejemplos pregunta–SQL del negocio activo (RAG)."""
    return obtener_base().buscar(consulta, tipos=tipos, k=k, dominio=dominio)


def _limpiar_datos(ruta_archivo: str, mapeo: dict | None = None, ruta_catalogo: str | None = None) -> dict:
    """Detecta y corrige nulos, duplicados, fechas, precios y nombres inconsistentes de un CSV/Excel de ventas."""
    import pandas as pd
    catalogo = pd.read_csv(ruta_catalogo) if ruta_catalogo else None
    r = limpiar_datos(ruta_archivo, mapeo=mapeo, catalogo=catalogo)
    return {"resumen": r.resumen(), "problemas": r.problemas}


def _generar_grafica(columnas: list[str], filas: list[list], spec: dict) -> dict:
    """Crea una gráfica Plotly (barras, líneas, pastel, mapa de calor, indicador) a partir de un resultado."""
    return generar_grafica(columnas, filas, spec)


def _transcribir_voz(ruta_audio: str) -> dict:
    """Convierte una nota de voz en texto con Whisper local."""
    return transcribir_voz(ruta_audio)


def _exportar_reporte(historial: list[dict], resumen_datos: dict | None = None, alertas: list[dict] | None = None) -> str:
    """Genera un PDF con las preguntas, gráficas y conclusiones de la sesión y devuelve su ruta."""
    return exportar_reporte(historial, resumen_datos, alertas)


def _detectar_alertas(ruta_db: str) -> list[dict]:
    """Detecta productos que llevan varias semanas bajando o con faltantes recientes."""
    return detectar_alertas(ruta_db)


ejecutar_sql_tool = StructuredTool.from_function(_ejecutar_sql, name="ejecutar_sql")
buscar_diccionario_tool = StructuredTool.from_function(_buscar_diccionario, name="buscar_diccionario")
limpiar_datos_tool = StructuredTool.from_function(_limpiar_datos, name="limpiar_datos")
generar_grafica_tool = StructuredTool.from_function(_generar_grafica, name="generar_grafica")
transcribir_voz_tool = StructuredTool.from_function(_transcribir_voz, name="transcribir_voz")
exportar_reporte_tool = StructuredTool.from_function(_exportar_reporte, name="exportar_reporte")
detectar_alertas_tool = StructuredTool.from_function(_detectar_alertas, name="detectar_alertas")

def _pronosticar_pan(ruta_db: str, fechas: list[str] | None = None, semanas: int = 8,
                     margen: float | None = None, hoy: str | None = None) -> dict:
    """Pronostica cuánto pan normal y Mega comprar por día (promedio del mismo día de la semana + margen) y mide
    el error que habría tenido el método en las últimas 8 semanas."""
    from datetime import date
    return negocio_jaibo.pronosticar_pan(ruta_db, fechas, semanas, margen, date.fromisoformat(hoy) if hoy else None)


def _rentabilidad_canales(ruta_db: str, dias: int | None = 90, comisiones: dict | None = None,
                          mes: int | None = None, anio: int | None = None) -> dict:
    """Ingreso por canal después de la comisión de las apps y la comisión máxima que cubre su sobreprecio
    (de los últimos ``dias`` o de un ``mes``/``anio`` concreto)."""
    return negocio_jaibo.rentabilidad_canales(ruta_db, dias, comisiones, mes, anio)


def _combinaciones_frecuentes(ruta_db: str, dias: int | None = 180) -> dict:
    """Pares de productos que se piden juntos (con su afinidad) y horarios flojos, para proponer promociones."""
    return negocio_jaibo.combinaciones_frecuentes(ruta_db, dias)


def _simular_promocion(ruta_db: str, productos: dict, precio_promocional: float, dias: int | None = 90,
                       margen_bruto: float | None = None) -> dict:
    """Cuántos combos adicionales por semana hacen falta para que una promoción no cueste dinero."""
    return negocio_jaibo.simular_promocion(ruta_db, productos, precio_promocional, dias, margen_bruto)


pronosticar_pan_tool = StructuredTool.from_function(_pronosticar_pan, name="pronosticar_pan")
rentabilidad_canales_tool = StructuredTool.from_function(_rentabilidad_canales, name="rentabilidad_canales")
combinaciones_frecuentes_tool = StructuredTool.from_function(_combinaciones_frecuentes, name="combinaciones_frecuentes")
simular_promocion_tool = StructuredTool.from_function(_simular_promocion, name="simular_promocion")


def _lista_de_compras(ruta_db: str, fechas: list[str] | None = None, margen: float | None = None,
                      hoy: str | None = None) -> dict:
    """Pan a comprar y gasto estimado (precio de Chedraui Ciudad del Carmen o el del dueño) y bebidas por acabarse."""
    from datetime import date
    return negocio_jaibo.lista_de_compras(ruta_db, fechas, margen, date.fromisoformat(hoy) if hoy else None)


lista_de_compras_tool = StructuredTool.from_function(_lista_de_compras, name="lista_de_compras")
HERRAMIENTAS_NEGOCIO = {"pronosticar_pan": pronosticar_pan_tool, "rentabilidad_canales": rentabilidad_canales_tool,
                        "combinaciones_frecuentes": combinaciones_frecuentes_tool,
                        "simular_promocion": simular_promocion_tool, "lista_de_compras": lista_de_compras_tool}

HERRAMIENTAS = [limpiar_datos_tool, ejecutar_sql_tool, buscar_diccionario_tool, generar_grafica_tool,
                transcribir_voz_tool, exportar_reporte_tool, detectar_alertas_tool, *HERRAMIENTAS_NEGOCIO.values()]

__all__ = ["HERRAMIENTAS", "HERRAMIENTAS_NEGOCIO", "ejecutar_sql_tool", "buscar_diccionario_tool", "limpiar_datos_tool",
           "generar_grafica_tool", "transcribir_voz_tool", "exportar_reporte_tool", "detectar_alertas_tool",
           "limpiar_datos", "generar_grafica", "transcribir_voz", "exportar_reporte", "detectar_alertas"]
