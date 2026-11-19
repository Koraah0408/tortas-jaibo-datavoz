"""Configuración central de DataVoz (se lee de variables de entorno / .env)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parents[1]
load_dotenv(RAIZ / ".env")


def _bool(nombre: str, defecto: bool) -> bool:
    valor = os.getenv(nombre)
    if valor is None or valor.strip() == "":
        return defecto
    return valor.strip().lower() in {"1", "true", "si", "sí", "yes", "on"}


def _float(nombre: str, defecto: float) -> float:
    try:
        return float(os.getenv(nombre, defecto))
    except ValueError:
        return defecto


@dataclass
class Config:
    # --- Modelo de lenguaje ---
    proveedor: str = field(default_factory=lambda: os.getenv("LLM_PROVEEDOR", "gemini").lower())
    respaldos: list[str] = field(default_factory=lambda: [
        p.strip().lower() for p in os.getenv("LLM_RESPALDOS", "groq,ollama").split(",") if p.strip()])
    # Modelo por rol: uno rápido para Orquestador/Visualizador/Narrador/Limpiador y otro para el Analista SQL
    modelo_gemini: str = field(default_factory=lambda: os.getenv("GEMINI_MODELO", "gemini-3.1-flash-lite"))
    modelo_gemini_sql: str = field(default_factory=lambda: os.getenv("GEMINI_MODELO_SQL", "gemini-3.5-flash-lite"))
    # Cada modelo de Gemini tiene su propia cuota diaria gratuita: se usan como respaldo en orden
    modelos_gemini_respaldo: list[str] = field(default_factory=lambda: [
        m.strip() for m in os.getenv("GEMINI_MODELOS_RESPALDO",
                                     "gemini-3.5-flash-lite,gemini-3.1-flash-lite,gemini-2.5-flash").split(",")
        if m.strip()])
    modelo_groq: str = field(default_factory=lambda: os.getenv("GROQ_MODELO", "llama-3.3-70b-versatile"))
    modelo_ollama: str = field(default_factory=lambda: os.getenv("OLLAMA_MODELO", "llama3.1:8b"))
    url_ollama: str = field(default_factory=lambda: os.getenv("OLLAMA_URL", "http://localhost:11434"))
    peticiones_por_minuto: float = field(default_factory=lambda: _float("LLM_PETICIONES_POR_MINUTO", 10))
    presupuesto_razonamiento_sql: int = field(default_factory=lambda: int(_float("GEMINI_RAZONAMIENTO_SQL", 512)))
    cache_llm: bool = field(default_factory=lambda: _bool("LLM_CACHE", True))
    timeout_llm: float = field(default_factory=lambda: _float("LLM_TIMEOUT", 30))

    # --- Datos ---
    ruta_db: Path = field(default_factory=lambda: Path(os.getenv("DATAVOZ_DB", RAIZ / "data" / "datavoz.duckdb")))
    dir_sesiones: Path = field(default_factory=lambda: RAIZ / "data" / "sesiones")
    timeout_sql: float = field(default_factory=lambda: _float("SQL_TIMEOUT", 10))
    max_filas: int = field(default_factory=lambda: int(_float("SQL_MAX_FILAS", 500)))
    max_reintentos_sql: int = field(default_factory=lambda: int(_float("SQL_MAX_REINTENTOS", 2)))

    # --- RAG ---
    dir_chroma: Path = field(default_factory=lambda: RAIZ / ".chroma")
    dir_conocimiento: Path = field(default_factory=lambda: RAIZ / "conocimiento")

    # --- Voz ---
    modelo_whisper: str = field(default_factory=lambda: os.getenv("WHISPER_MODELO", "small"))
    dispositivo_whisper: str = field(default_factory=lambda: os.getenv("WHISPER_DISPOSITIVO", "cpu"))

    # --- Agentes ---
    visualizador_con_llm: bool = field(default_factory=lambda: _bool("VISUALIZADOR_LLM", True))

    # --- Salidas ---
    dir_trazas: Path = field(default_factory=lambda: RAIZ / "trazas")
    dir_reportes: Path = field(default_factory=lambda: RAIZ / "reportes")
    dir_cache: Path = field(default_factory=lambda: RAIZ / ".cache")


_config: Config | None = None


def obtener_config() -> Config:
    global _config
    if _config is None:
        _config = Config()
    return _config


def reiniciar_config() -> Config:
    """Vuelve a leer las variables de entorno (útil en pruebas)."""
    global _config
    _config = Config()
    return _config
