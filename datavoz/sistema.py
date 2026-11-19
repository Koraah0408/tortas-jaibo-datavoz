"""Fachada de DataVoz: una sesión de conversación sobre el grafo multiagente.

Ejemplo:
    from datavoz.sistema import SesionDataVoz
    s = SesionDataVoz()
    r = s.preguntar("¿Qué producto se vendió menos en diciembre y por qué crees que pasó?")
    print(r["respuesta"])
    r = s.preguntar("¿Y en enero?")           # usa la memoria de la conversación
"""

from __future__ import annotations

import json
import re
import time
import uuid
from datetime import datetime
from pathlib import Path

from .agentes.base import CAMPOS_TURNO
from .agentes.orquestador import datos_iniciales
from .config import obtener_config
from .grafo import construir_grafo
from .llm import llamadas_a_dict, registrar_llamadas
from .utilidades import a_json_serializable, normalizar

_APRUEBA = re.compile(r"^\s*(si|sí|ok|va|dale|claro|de acuerdo|apruebo|aprobado|cargalo|carga(lo)?|adelante)\b")
_RECHAZA = re.compile(r"^\s*(no|cancela|cancelar|mejor no|detente|alto)\b")

CLAVES_RESPUESTA = ["pregunta", "pregunta_completa", "intencion", "es_seguimiento", "respuesta", "sql",
                    "explicacion_sql", "resultado", "consultas_apoyo", "grafica", "verificacion", "intentos_sql",
                    "sql_ejecutadas", "transcripcion", "limpieza", "reporte_pdf", "pasos", "error",
                    "decision_supervisor", "analisis", "herramienta_negocio", "carga_pendiente"]


class SesionDataVoz:
    """Una conversación con DataVoz.

    Con ``persistente=True`` la memoria se guarda en SQLite (``data/sesiones/sesiones.sqlite``) y la
    sesión aparece en el catálogo: se puede cerrar la app y reabrirla con ``SesionDataVoz(sesion_id=...,
    persistente=True)``. Sin persistencia (evaluación y pruebas) la memoria vive en RAM.
    """

    def __init__(self, sesion_id: str | None = None, ruta_db: str | None = None, guardar_trazas: bool = True,
                 dir_trazas: str | Path | None = None, persistente: bool = False, dominio: str = "abarrotes",
                 origen: str | None = None):
        cfg = obtener_config()
        if ruta_db is None and not Path(cfg.ruta_db).exists():
            from .datos import construir_base_ejemplo
            construir_base_ejemplo()
        self.sesion_id = sesion_id or datetime.now().strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:4]
        self.persistente = persistente
        checkpointer = None
        if persistente:
            from .sesiones import obtener_checkpointer
            checkpointer = obtener_checkpointer()
        self.grafo = construir_grafo(checkpointer)
        self.config = {"configurable": {"thread_id": self.sesion_id}, "recursion_limit": 30}
        self.guardar_trazas = guardar_trazas
        self.dir_trazas = Path(dir_trazas or cfg.dir_trazas) / self.sesion_id
        self.turno = 0
        datos = datos_iniciales(ruta_db, origen, dominio)
        datos["sesion_id"] = self.sesion_id
        self._iniciales = {"historial": [], "contexto": {}, "datos": datos, "dashboard": []}
        self._iniciado = False
        if persistente:  # ¿es una sesión guardada? entonces se continúa donde se quedó
            valores = self.grafo.get_state(self.config).values
            if valores.get("historial") is not None:
                self._iniciado = True
                self.turno = len(valores.get("historial") or [])

    # ------------------------------------------------------------------
    def _invocar(self, entrada: dict, al_avanzar=None) -> dict:
        """Ejecuta un turno. ``al_avanzar(nodo, paso)`` se llama cada vez que termina un agente."""
        entrada = {**CAMPOS_TURNO, **entrada}
        if not self._iniciado:
            entrada.update(self._iniciales)
            self._iniciado = True
        self.turno += 1
        inicio = time.perf_counter()
        error = None
        # En sesiones guardadas basta un punto de control por turno (al terminar el grafo)
        opciones = {"durability": "exit"} if self.persistente else {}
        with registrar_llamadas() as llamadas:
            try:
                if al_avanzar is None:
                    estado = self.grafo.invoke(entrada, self.config, **opciones)
                else:
                    for evento in self.grafo.stream(entrada, self.config, stream_mode="updates", **opciones):
                        for nombre_nodo, actualizacion in evento.items():
                            pasos = (actualizacion or {}).get("pasos") or [{}]
                            al_avanzar(nombre_nodo, pasos[-1])
                    estado = self.grafo.get_state(self.config).values
            except Exception as e:  # errores inesperados: se reportan sin tumbar la interfaz
                error = f"{type(e).__name__}: {e}"
                estado = {**entrada, "respuesta": "Ocurrió un error inesperado al procesar tu pregunta. "
                                                  "Intenta de nuevo o reformúlala.", "error": error}
        duracion = time.perf_counter() - inicio
        salida = {k: estado.get(k) for k in CLAVES_RESPUESTA}
        salida["duracion_s"] = round(duracion, 2)
        salida["llamadas_llm"] = llamadas_a_dict(llamadas)
        salida["tokens"] = sum(x.tokens_entrada + x.tokens_salida for x in llamadas)
        salida["error"] = error or salida.get("error")
        salida["turno"] = self.turno
        if self.guardar_trazas:
            salida["ruta_traza"] = str(self._guardar_traza(entrada, salida))
        if self.persistente and not error:
            from . import sesiones
            memoria = self.estado()
            primera = next((t.get("pregunta") for t in memoria.get("historial") or []
                            if t.get("intencion") == "consulta_datos" and t.get("pregunta")), "")
            sesiones.registrar_turno(self.sesion_id, len(memoria.get("historial") or []), primera or "Sesión sin título",
                                     (memoria.get("datos") or {}).get("origen", ""))
        return salida

    def _guardar_traza(self, entrada: dict, salida: dict) -> Path:
        self.dir_trazas.mkdir(parents=True, exist_ok=True)
        ruta = self.dir_trazas / f"turno_{self.turno:03d}.json"
        traza = {"sesion": self.sesion_id, "turno": self.turno, "fecha": datetime.now().isoformat(timespec="seconds"),
                 "entrada": {k: entrada.get(k) for k in ("pregunta", "audio", "archivo")},
                 **{k: v for k, v in salida.items() if k not in ("grafica",)},
                 "grafica": {"spec": (salida.get("grafica") or {}).get("spec")} if salida.get("grafica") else None}
        if traza.get("limpieza"):
            traza["limpieza"] = {"resumen": traza["limpieza"]["resumen"],
                                 "problemas_muestra": traza["limpieza"]["problemas"][:30]}
        ruta.write_text(json.dumps(a_json_serializable(traza), ensure_ascii=False, indent=1), encoding="utf-8")
        return ruta

    # ------------------------------------------------------------------
    def preguntar(self, texto: str | None = None, audio: str | Path | None = None, al_avanzar=None) -> dict:
        """Hace una pregunta por texto o por nota de voz (ruta a un archivo de audio)."""
        if texto and self.carga_pendiente():  # «sí, cárgalo» / «no» responde a los cambios propuestos
            t = normalizar(texto)
            if _APRUEBA.search(t):
                return self.aprobar_carga(al_avanzar)
            if _RECHAZA.search(t):
                return self.cancelar_carga()
        return self._invocar({"pregunta": texto or "", "audio": str(audio) if audio else None}, al_avanzar)

    def cargar_archivo(self, ruta: str | Path, mapeo: dict | None = None, al_avanzar=None) -> dict:
        """Sube un CSV/Excel de ventas. El Limpiador lo revisa y PROPONE los cambios; no escribe nada hasta que
        el dueño los apruebe con ``aprobar_carga()`` (o respondiendo «sí, cárgalo»)."""
        return self._invocar({"pregunta": "", "archivo": str(ruta), "mapeo_columnas": mapeo}, al_avanzar)

    def carga_pendiente(self) -> dict | None:
        return self.estado().get("carga_pendiente") if self._iniciado else None

    def aprobar_carga(self, al_avanzar=None) -> dict:
        """El dueño aprueba los cambios propuestos: el Limpiador los aplica y carga los datos."""
        pendiente = self.carga_pendiente()
        if not pendiente:
            return {"respuesta": "No hay ningún archivo esperando tu aprobación.", "intencion": "conversacion"}
        return self._invocar({"pregunta": "", "archivo": pendiente["archivo"], "mapeo_columnas": pendiente["mapeo"],
                              "carga_aprobada": True}, al_avanzar)

    def cancelar_carga(self) -> dict:
        """El dueño no aprueba: se descartan los cambios propuestos y no se escribe nada."""
        pendiente = self.carga_pendiente()
        if pendiente:
            self.grafo.update_state(self.config, {"carga_pendiente": None})
        return {"respuesta": ("Listo, no cargué nada: tus datos siguen como estaban." if pendiente
                              else "No hay ningún archivo esperando tu aprobación."), "intencion": "conversacion",
                "carga_pendiente": None}

    def exportar_reporte(self) -> dict:
        return self._invocar({"pregunta": "Genera el reporte PDF de la sesión"})

    def estado(self) -> dict:
        """Memoria actual de la sesión (historial, contexto, datos y dashboard)."""
        if not self._iniciado:
            return dict(self._iniciales)
        valores = self.grafo.get_state(self.config).values
        return {k: valores.get(k) for k in ("historial", "contexto", "datos", "dashboard", "carga_pendiente")}

    def quitar_del_dashboard(self, id_tarjeta: str) -> None:
        if not self._iniciado:
            return
        dashboard = [t for t in (self.estado().get("dashboard") or []) if t.get("id") != id_tarjeta]
        self.grafo.update_state(self.config, {"dashboard": dashboard}, as_node="memoria")
