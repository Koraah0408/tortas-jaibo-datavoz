"""LLM simulado ("oráculo") para probar el grafo y la suite de evaluación SIN red ni API key.

No sirve para medir la calidad del agente: responde con el SQL de referencia de cada caso.
Se usa en las pruebas automáticas (pytest) y con ``ejecutar_evaluacion.py --simulado`` para
verificar que el arnés de evaluación funciona de punta a punta.
"""

from __future__ import annotations

import difflib
import json
import re
from pathlib import Path

import yaml

from datavoz.utilidades import normalizar

RAIZ = Path(__file__).resolve().parents[1]

MAPEO_FORMATO_DISTINTO = {"Día de venta": "fecha", "Hora": "hora", "Folio": "ticket", "Artículo vendido": "producto",
                          "Pzas": "cantidad", "Precio c/u": "precio_unitario", "Cobrado": "total",
                          "Pagó con": "metodo_pago", "Promo": "promocion"}


ANALISIS_DE_HERRAMIENTA = {"pronosticar_pan": "pronostico_pan", "rentabilidad_canales": "rentabilidad_canales",
                           "combinaciones_frecuentes": "promociones", "simular_promocion": "promociones",
                           "lista_de_compras": "compras", "reporte_de_ventas": "reporte_ventas"}


def _casos() -> list[dict]:
    casos = []
    for archivo in ("casos_prueba.yaml", "casos_jaibo.yaml"):
        ruta = RAIZ / "evaluacion" / archivo
        if ruta.exists():
            casos += yaml.safe_load(ruta.read_text(encoding="utf-8"))["casos"]
    return casos


class OraculoLLM:
    def __init__(self, sql_erroneo_primero: set[str] | None = None, sql_semantico_malo_primero: set[str] | None = None,
                 json_roto_primero: set[str] | None = None):
        self.casos = _casos()
        self.textos = {}
        for c in self.casos:
            texto = c.get("pregunta") or c.get("texto_hablado")
            if texto:
                self.textos.setdefault(normalizar(texto), c)  # si dos casos repiten la pregunta, manda el primero
        # casos en los que el primer SQL viene con un error (para probar el ciclo de reintento)
        self.sql_erroneo_primero = sql_erroneo_primero or set()
        # casos en los que el primer SQL corre pero tiene un error de lógica (para probar la revisión semántica)
        self.sql_semantico_malo_primero = sql_semantico_malo_primero or set()
        # casos en los que el modelo responde 2 veces con texto que no es JSON (para probar el reintento)
        self.json_roto_primero = json_roto_primero or set()
        self.respuestas_rotas: dict[str, int] = {}
        self.vistos: set[str] = set()

    def _caso(self, texto: str) -> dict | None:
        clave = normalizar(texto)
        if clave in self.textos:
            return self.textos[clave]
        parecido = difflib.get_close_matches(clave, list(self.textos), n=1, cutoff=0.75)
        return self.textos[parecido[0]] if parecido else None

    def __call__(self, rol: str, sistema: str, usuario: str) -> str:
        if rol == "orquestador":
            mensaje = usuario.split("Mensaje del usuario:")[-1].split("\n\n")[0].strip()
            caso = self._caso(mensaje)
            cat = (caso or {}).get("categoria")
            intencion = {"seguridad": "peligrosa", "fuera_de_alcance": "fuera_de_alcance"}.get(cat, "consulta_datos")
            return json.dumps({"intencion": intencion, "es_seguimiento": cat == "seguimiento",
                               "pregunta_completa": mensaje, "contexto": {},
                               "analisis": ANALISIS_DE_HERRAMIENTA.get((caso or {}).get("herramienta")),
                               "respuesta_directa": "No puedo ayudarte con eso." if intencion != "consulta_datos" else None})
        if rol == "asesor":
            caso = self._caso(usuario.split("Pregunta del dueño:")[-1].strip()) or {}
            p = dict(caso.get("parametros_esperados") or {})
            p.pop("fechas", None)  # las fechas las calcula el sistema con reglas
            if "productos" in p:
                p["productos"] = [{"producto": k, "cantidad": v} for k, v in p["productos"].items()]
            return json.dumps({"herramienta": caso.get("herramienta"), "parametros": p})
        if rol == "analista_sql":
            pregunta = usuario.split("Pregunta del usuario:")[-1].split("\n\n")[0].strip()
            caso = self._caso(pregunta)
            if not caso or not caso.get("sql_referencia"):
                return json.dumps({"sql": "", "falta_informacion": "No hay datos para eso.", "consultas_apoyo": []})
            if caso["id"] in self.json_roto_primero and self.respuestas_rotas.get(caso["id"], 0) < 2:
                self.respuestas_rotas[caso["id"]] = self.respuestas_rotas.get(caso["id"], 0) + 1
                return "Claro, aquí está la consulta: SELECT * FROM ventas (sin formato JSON)"
            if caso["id"] in self.sql_erroneo_primero and caso["id"] not in self.vistos:
                self.vistos.add(caso["id"])
                return json.dumps({"sql": "SELECT productoo FROM ventas", "explicacion": "con error a propósito",
                                   "consultas_apoyo": []})
            if caso["id"] in self.sql_semantico_malo_primero and ("sem", caso["id"]) not in self.vistos:
                self.vistos.add(("sem", caso["id"]))
                return json.dumps({"sql": "SELECT v.producto, COUNT(*) FILTER (WHERE i.sin_existencia) AS dias "
                                          "FROM ventas v JOIN inventario_diario i ON v.producto = i.producto "
                                          "AND v.fecha = i.fecha WHERE v.mes = 12 GROUP BY v.producto",
                                   "explicacion": "con error de lógica a propósito", "consultas_apoyo": []})
            return json.dumps({"sql": caso["sql_referencia"], "explicacion": f"Consulta del caso {caso['id']}",
                               "consultas_apoyo": []})
        if rol == "visualizador":
            return "{}"  # el Visualizador usará sus reglas
        if rol == "narrador":
            filas = re.findall(r"^\| (.+) \|$", usuario.split("Resultado principal")[-1], flags=re.M)
            datos = [f for f in filas if not set(f) <= set("-| ")][1:2]
            return (f"El resultado principal es: {datos[0].replace(' | ', ', ')}." if datos
                    else "No hubo ventas para lo que preguntaste.") + "\nRecomendación: revisa el detalle en la tabla."
        if rol == "limpiador":
            perfil = json.loads(usuario.split("\n", 1)[1])
            return json.dumps({"mapeo": {p["columna"]: MAPEO_FORMATO_DISTINTO[p["columna"]] for p in perfil
                                         if p["columna"] in MAPEO_FORMATO_DISTINTO}, "ignoradas": ["Notas"]})
        if rol == "limpiador_resumen":
            return "Revisé tu archivo y corregí los problemas que encontré. Ya puedes hacer preguntas."
        return "{}"
