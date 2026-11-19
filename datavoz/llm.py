"""Capa de acceso a modelos de lenguaje con respaldo automático, caché y límite de peticiones.

Proveedor principal: Google Gemini (capa gratuita). Respaldos: Groq (Llama 3.x)
y Ollama local. Si el principal falla (límite de cuota, red, etc.) LangChain
pasa automáticamente al siguiente modelo o proveedor de la cadena, y cada fallo queda en la traza.

Para pruebas sin red se puede instalar un *simulador* con
``establecer_simulador(funcion)``; la función recibe (rol, sistema, usuario)
y devuelve el texto que "respondería" el modelo.
"""

from __future__ import annotations

import os
import time
import urllib.request
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass
from typing import Callable

from langchain_core.messages import HumanMessage, SystemMessage

from .config import obtener_config
from .utilidades import extraer_json

ROLES_JSON = {"orquestador", "analista_sql", "visualizador", "limpiador", "asesor"}


class ErrorLLM(RuntimeError):
    """Error al invocar al modelo (sin proveedor, cuota agotada, respuesta inválida)."""


@dataclass
class LlamadaLLM:
    rol: str
    proveedor: str
    modelo: str
    duracion_s: float
    tokens_entrada: int = 0
    tokens_salida: int = 0
    ok: bool = True
    error: str | None = None


_llamadas: ContextVar[list | None] = ContextVar("llamadas_llm", default=None)
_simulador: Callable[[str, str, str], str] | None = None
_modelos: dict[tuple[str, bool], object] = {}
_cache_configurado = False


@contextmanager
def registrar_llamadas():
    """Recolecta las llamadas al LLM hechas dentro del bloque (para trazas y métricas)."""
    padre = _llamadas.get()
    lista: list[LlamadaLLM] = []
    token = _llamadas.set(lista)
    try:
        yield lista
    finally:
        _llamadas.reset(token)
        if padre is not None:  # los bloques anidados (nodo dentro de turno) también suben al turno
            padre.extend(lista)


def _anotar(llamada: LlamadaLLM) -> None:
    lista = _llamadas.get()
    if lista is not None:
        lista.append(llamada)


def establecer_simulador(funcion: Callable[[str, str, str], str] | None) -> None:
    """Instala (o quita con None) un simulador de LLM para pruebas sin red."""
    global _simulador
    _simulador = funcion


def _api_key_google() -> str | None:
    return os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")


def _ollama_disponible(url: str) -> bool:
    try:
        with urllib.request.urlopen(f"{url.rstrip('/')}/api/tags", timeout=0.8) as r:
            return r.status == 200
    except Exception:
        return False


def _configurar_cache() -> None:
    global _cache_configurado
    if _cache_configurado:
        return
    cfg = obtener_config()
    if cfg.cache_llm:
        from langchain_community.cache import SQLiteCache
        from langchain_core.globals import set_llm_cache
        cfg.dir_cache.mkdir(parents=True, exist_ok=True)
        set_llm_cache(SQLiteCache(database_path=str(cfg.dir_cache / "llm_cache.db")))
    _cache_configurado = True


_limitador = None


def _limitador_compartido():
    """Un solo limitador para TODOS los agentes: la cuota de Gemini es por proyecto, no por rol."""
    global _limitador
    if _limitador is None:
        from langchain_core.rate_limiters import InMemoryRateLimiter
        _limitador = InMemoryRateLimiter(requests_per_second=obtener_config().peticiones_por_minuto / 60,
                                         check_every_n_seconds=0.1, max_bucket_size=5)
        # La cubeta empieza llena: una pregunta (4–5 llamadas) no espera; ráfagas seguidas sí se frenan.
        _limitador.available_tokens = 5.0
    return _limitador


def _crear_modelos(proveedor: str, rol: str, json_salida: bool) -> list[tuple[str, object]]:
    """Crea los modelos de chat de un proveedor como [(nombre, modelo)]; [] si no está disponible.

    Cada modelo de Gemini tiene su propia cuota diaria en la capa gratuita, por eso se encadenan:
    si el principal responde 429 (cuota) o 503 (saturado), LangChain pasa al siguiente.
    """
    cfg = obtener_config()
    if proveedor == "gemini":
        clave = _api_key_google()
        if not clave:
            return []
        from langchain_google_genai import ChatGoogleGenerativeAI
        modelos = []
        principal = cfg.modelo_gemini_sql if rol == "analista_sql" else cfg.modelo_gemini
        for nombre in dict.fromkeys([principal, *cfg.modelos_gemini_respaldo]):
            extra = {}
            if nombre.startswith("gemini-2.5-flash"):
                extra["thinking_budget"] = cfg.presupuesto_razonamiento_sql if rol == "analista_sql" else 0
            if json_salida:
                extra["response_mime_type"] = "application/json"
            modelos.append((nombre, ChatGoogleGenerativeAI(model=nombre, google_api_key=clave, temperature=0,
                                                           max_retries=1, timeout=cfg.timeout_llm,
                                                           rate_limiter=_limitador_compartido(), **extra)))
        return modelos
    if proveedor == "groq":
        if not os.getenv("GROQ_API_KEY"):
            return []
        from langchain_groq import ChatGroq
        kwargs = {"response_format": {"type": "json_object"}} if json_salida else {}
        return [(cfg.modelo_groq, ChatGroq(model=cfg.modelo_groq, temperature=0, max_retries=1,
                                           timeout=cfg.timeout_llm, model_kwargs=kwargs))]
    if proveedor == "ollama":
        if not _ollama_disponible(cfg.url_ollama):
            return []
        from langchain_ollama import ChatOllama
        return [(cfg.modelo_ollama, ChatOllama(model=cfg.modelo_ollama, base_url=cfg.url_ollama, temperature=0,
                                               format="json" if json_salida else None))]
    return []


def proveedores_disponibles() -> list[str]:
    cfg = obtener_config()
    disponibles = []
    for p in [cfg.proveedor, *cfg.respaldos]:
        if p in disponibles:
            continue
        if (p == "gemini" and _api_key_google()) or (p == "groq" and os.getenv("GROQ_API_KEY")) or \
           (p == "ollama" and _ollama_disponible(cfg.url_ollama)):
            disponibles.append(p)
    return disponibles


def obtener_cadena(rol: str, json_salida: bool) -> list[tuple[str, str, object]]:
    """Cadena de respaldo de un rol: [(proveedor, nombre_modelo, modelo)], en orden de preferencia.

    Se recorre manualmente (en lugar de ``with_fallbacks``) para que cada fallo quede en la traza.
    """
    clave = (rol, json_salida)
    if clave not in _modelos:
        _configurar_cache()
        cfg = obtener_config()
        cadena = []
        for p in dict.fromkeys([cfg.proveedor, *cfg.respaldos]):
            cadena += [(p, nombre, m) for nombre, m in _crear_modelos(p, rol, json_salida)]
        _modelos[clave] = cadena
    return _modelos[clave]


def reiniciar_modelos() -> None:
    _modelos.clear()


def _texto_respuesta(respuesta) -> str:
    texto = getattr(respuesta, "text", None)
    if isinstance(texto, str):          # langchain-core ≥ 1.0: propiedad (str)
        texto = str(texto)
    elif callable(texto):               # versiones anteriores: método
        texto = texto()
    if not texto:
        contenido = respuesta.content
        if isinstance(contenido, list):
            texto = "".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in contenido)
        else:
            texto = str(contenido)
    return texto


def invocar_llm(rol: str, sistema: str, usuario: str, json_salida: bool | None = None) -> dict | str:
    """Invoca al modelo para un rol. Devuelve dict (roles JSON) o texto (Narrador)."""
    json_salida = rol in ROLES_JSON if json_salida is None else json_salida
    from .seguridad import REGLA_DATOS
    sistema = sistema + REGLA_DATOS
    intentos = 2 if json_salida else 1
    ultimo_error = None
    for intento in range(intentos):
        mensaje_usuario = usuario if intento == 0 else (
            usuario + "\n\nIMPORTANTE: tu respuesta anterior no era JSON válido. Responde SOLO con un objeto JSON.")
        inicio = time.perf_counter()
        if _simulador is not None:
            texto = _simulador(rol, sistema, mensaje_usuario)
            _anotar(LlamadaLLM(rol, "simulado", "simulado", time.perf_counter() - inicio))
        else:
            cadena = obtener_cadena(rol, json_salida)
            if not cadena:
                raise ErrorLLM("No hay ningún modelo de lenguaje configurado. Agrega GOOGLE_API_KEY (o GROQ_API_KEY) "
                               "en el archivo .env o inicia Ollama.")
            respuesta, errores = None, []
            for proveedor, nombre, llm in cadena:
                t0 = time.perf_counter()
                try:
                    respuesta = llm.invoke([SystemMessage(content=sistema), HumanMessage(content=mensaje_usuario)])
                except Exception as e:  # cuota (429), saturación (503), red… → siguiente modelo de la cadena
                    _anotar(LlamadaLLM(rol, "error", nombre, time.perf_counter() - t0, ok=False,
                                       error=f"{type(e).__name__}: {str(e)[:500]}"))
                    errores.append(f"{nombre}: {type(e).__name__}")
                    continue
                uso = getattr(respuesta, "usage_metadata", None) or {}
                _anotar(LlamadaLLM(rol, proveedor, nombre, time.perf_counter() - t0,
                                   int(uso.get("input_tokens", 0) or 0), int(uso.get("output_tokens", 0) or 0)))
                break
            if respuesta is None:
                raise ErrorLLM("Falló la llamada al modelo en todos los respaldos (" + "; ".join(errores) +
                               "). Puede ser la cuota diaria de la capa gratuita.")
            texto = _texto_respuesta(respuesta)
        if not json_salida:
            return texto.strip()
        try:
            return extraer_json(texto)
        except ValueError as e:
            ultimo_error = e
    raise ErrorLLM(f"El modelo no devolvió JSON válido: {ultimo_error}")


def llamadas_a_dict(llamadas: list[LlamadaLLM]) -> list[dict]:
    return [asdict(x) | {"duracion_s": round(x.duracion_s, 3)} for x in llamadas]
