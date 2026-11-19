"""Herramienta ``transcribir_voz``: nota de voz → texto con Whisper local (faster-whisper)."""

from __future__ import annotations

import os
import time
from pathlib import Path

from ..config import obtener_config

_modelo = None

# Vocabulario del negocio para orientar a Whisper (mejora nombres de productos y meses)
PROMPT_DOMINIO = ("Preguntas sobre las ventas del negocio: Tortas Jaibo (tortas, Barda, Mega barda, pierna, gorditas, "
                  "bocoles, tacos de barbacoa, pan, Didi, Rappi, mostrador, ticket promedio, combo, Jamaica) o una "
                  "tienda de abarrotes (refresco, cerveza, tortillas, botanas, existencias). Meses, quincena, "
                  "promoción, ¿cuánto vendí?, ¿cuánto cobré?, ¿qué producto se vendió más?")


def whisper_disponible() -> bool:
    try:
        import faster_whisper  # noqa: F401
        return True
    except ImportError:
        return False


def _obtener_modelo():
    global _modelo
    if _modelo is None:
        from faster_whisper import WhisperModel
        cfg = obtener_config()
        tipo = "int8" if cfg.dispositivo_whisper == "cpu" else "float16"
        _modelo = WhisperModel(cfg.modelo_whisper, device=cfg.dispositivo_whisper, compute_type=tipo)
    return _modelo


def _leer_wav(ruta: Path):
    """Decodifica WAV PCM sin depender de FFmpeg/PyAV: mono, float32, 16 kHz."""
    import wave

    import numpy as np
    with wave.open(str(ruta), "rb") as w:
        canales, ancho, tasa = w.getnchannels(), w.getsampwidth(), w.getframerate()
        crudo = w.readframes(w.getnframes())
    tipos = {1: np.uint8, 2: np.int16, 4: np.int32}
    if ancho not in tipos:
        return None
    x = np.frombuffer(crudo, dtype=tipos[ancho]).astype(np.float32)
    x = (x - 128) / 128 if ancho == 1 else x / float(2 ** (8 * ancho - 1))
    if canales > 1:
        x = x.reshape(-1, canales).mean(axis=1)
    if tasa != 16000 and len(x):
        n = int(len(x) * 16000 / tasa)
        x = np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x).astype(np.float32)
    return x


def transcribir_voz(ruta_audio: str | Path, idioma: str = "es") -> dict:
    """Transcribe un archivo de audio (wav, mp3, m4a, ogg, webm).

    Devuelve {"texto", "idioma", "duracion_audio_s", "duracion_s", "error"}.
    """
    inicio = time.perf_counter()
    ruta_audio = Path(ruta_audio)
    if not ruta_audio.exists():
        return {"texto": "", "error": f"No existe el archivo de audio {ruta_audio.name}"}
    if not whisper_disponible():  # p. ej. en la nube: Gemini también entiende audio y no pesa nada
        return transcribir_con_gemini(ruta_audio, inicio)
    try:
        entrada = None
        if ruta_audio.suffix.lower() == ".wav":
            try:
                entrada = _leer_wav(ruta_audio)
            except Exception:
                entrada = None
        if entrada is None:
            entrada = str(ruta_audio)  # otros formatos: decodifica faster-whisper (PyAV)
        segmentos, info = _obtener_modelo().transcribe(entrada, language=idioma, beam_size=5,
                                                       vad_filter=True, initial_prompt=PROMPT_DOMINIO)
        texto = " ".join(s.text.strip() for s in segmentos).strip()
        return {"texto": texto, "idioma": info.language, "duracion_audio_s": round(info.duration, 2),
                "duracion_s": round(time.perf_counter() - inicio, 2), "error": None}
    except Exception as e:
        return {"texto": "", "error": f"No se pudo transcribir el audio: {e}",
                "duracion_s": round(time.perf_counter() - inicio, 2)}


def transcribir_con_gemini(ruta_audio: Path, inicio: float | None = None) -> dict:
    """Respaldo sin Whisper: le pide a Gemini la transcripción literal del audio."""
    import base64
    import mimetypes
    inicio = inicio or time.perf_counter()
    try:
        from langchain_core.messages import HumanMessage
        from langchain_google_genai import ChatGoogleGenerativeAI

        from ..config import obtener_config
        cfg = obtener_config()
        if not os.getenv("GOOGLE_API_KEY"):
            return {"texto": "", "error": "Para usar la voz sin Whisper hace falta GOOGLE_API_KEY."}
        tipo = mimetypes.guess_type(str(ruta_audio))[0] or "audio/wav"
        datos = base64.b64encode(Path(ruta_audio).read_bytes()).decode()
        llm = ChatGoogleGenerativeAI(model=cfg.modelo_gemini, temperature=0, timeout=cfg.timeout_llm)
        respuesta = llm.invoke([HumanMessage(content=[
            {"type": "text", "text": "Transcribe literalmente lo que se dice en este audio en español de México. "
                                     "Es una pregunta del dueño de Tortas Jaibo sobre sus ventas (tortas, pan, Didi, "
                                     "Rappi, barbacoa, promociones). Responde solo con el texto transcrito."},
            {"type": "media", "data": datos, "mime_type": tipo}])])
        texto = respuesta.content if isinstance(respuesta.content, str) else " ".join(
            p.get("text", "") if isinstance(p, dict) else str(p) for p in respuesta.content)
        return {"texto": texto.strip().strip('"'), "idioma": "es", "motor": "gemini",
                "duracion_s": round(time.perf_counter() - inicio, 2), "error": None}
    except Exception as e:
        return {"texto": "", "error": f"No se pudo transcribir el audio con Gemini: {type(e).__name__}",
                "duracion_s": round(time.perf_counter() - inicio, 2)}
