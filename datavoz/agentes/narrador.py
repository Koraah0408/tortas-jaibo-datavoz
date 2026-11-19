"""Agente Narrador: explica el resultado en lenguaje sencillo y verifica que no invente cifras."""

from __future__ import annotations

from ..herramientas import buscar_diccionario_tool
from ..llm import ErrorLLM, invocar_llm
from ..utilidades import formato_numero, tabla_markdown
from ..verificacion import calcular_hechos, hechos_a_texto, verificar_texto
from . import prompts
from .base import EstadoDataVoz, nodo


def _textos_a_ignorar(resultados: list[dict]) -> list[str]:
    """Valores de texto de los resultados (nombres de productos con números, p. ej. 'Refresco 3 L')."""
    textos = set()
    for r in resultados:
        for fila in r.get("filas") or []:
            for v in fila:
                if isinstance(v, str) and any(ch.isdigit() for ch in v) and len(v) > 3:
                    textos.add(v)
    return list(textos)


def respuesta_de_respaldo(estado: EstadoDataVoz) -> str:
    """Respuesta sin LLM (si se agotó la cuota): describe el resultado con las cifras exactas."""
    r = estado.get("resultado") or {}
    columnas, filas = r.get("columnas") or [], r.get("filas") or []
    if not filas:
        return "No encontré ventas que cumplan con lo que preguntaste en el periodo disponible."
    if len(filas) == 1:
        partes = [f"{c.replace('_', ' ')}: {formato_numero(v) if isinstance(v, (int, float)) else v}"
                  for c, v in zip(columnas, filas[0])]
        return "Resultado: " + "; ".join(partes) + "."
    lineas = []
    for f in filas[:5]:
        lineas.append(", ".join(f"{formato_numero(v) if isinstance(v, (int, float)) else v}" for v in f))
    return (f"Encontré {len(filas)} resultados. Los primeros son: " + " | ".join(lineas) +
            ". (Explicación automática no disponible en este momento.)")


@nodo("Narrador", "explicar_y_verificar")
def narrador(estado: EstadoDataVoz) -> dict:
    pregunta = estado.get("pregunta_completa") or estado.get("pregunta") or ""
    resultado = estado.get("resultado") or {}
    apoyo = [a for a in (estado.get("consultas_apoyo") or []) if not a.get("error")]
    resultados = [resultado] + apoyo
    hechos = calcular_hechos(resultado)
    for i, a in enumerate(apoyo, 1):
        hechos += calcular_hechos(a, etiqueta=f"[apoyo {i}] ")
    datos = estado.get("datos") or {}
    reglas = buscar_diccionario_tool.invoke({"consulta": pregunta, "tipos": ["regla"], "k": 2,
                                             "dominio": datos.get("dominio") or "abarrotes"})

    bloques = [f"Negocio: {datos.get('negocio') or 'pequeño negocio'}.",
               f"Pregunta del dueño: {pregunta}",
               f"Qué se calculó: {estado.get('explicacion_sql') or '-'}",
               "Resultado principal" + (" (VACÍO: no hubo datos)" if not resultado.get("filas") else "") + ":\n" +
               tabla_markdown(resultado.get("columnas") or [], resultado.get("filas") or [], 25)]
    for i, a in enumerate(apoyo, 1):
        bloques.append(f"Dato de apoyo {i} ({a.get('proposito')}):\n" +
                       tabla_markdown(a.get("columnas") or [], a.get("filas") or [], 15))
    bloques.append("Hechos calculados (cifras que puedes usar):\n" + hechos_a_texto(hechos[:40]))
    bloques.append("Reglas del negocio relevantes:\n" + "\n\n".join(r["texto"] for r in reglas))
    usuario = "\n\n".join(bloques)

    ignorar = _textos_a_ignorar(resultados)
    from ..seguridad import valores_sospechosos
    sospechosos = valores_sospechosos(*resultados)
    intentos = []
    texto = None
    try:
        texto = invocar_llm("narrador", prompts.NARRADOR, usuario, json_salida=False)
        verif = verificar_texto(texto, resultados, hechos, pregunta, ignorar)
        intentos.append({"texto": texto, "verificacion": verif})
        if not verif["ok"]:
            correccion = (usuario + "\n\nTu respuesta anterior mencionó cifras que NO están en los datos: "
                          f"{', '.join(verif['no_verificadas'])}. Reescríbela usando solo cifras de los datos o de "
                          "los hechos calculados (puedes omitir esas cifras).")
            texto = invocar_llm("narrador", prompts.NARRADOR, correccion, json_salida=False)
            verif = verificar_texto(texto, resultados, hechos, pregunta, ignorar)
            intentos.append({"texto": texto, "verificacion": verif})
            if not verif["ok"]:
                texto += ("\n\n_Nota: algunas cifras de esta explicación no se pudieron verificar contra los datos; "
                          "revisa la tabla de resultados._")
    except ErrorLLM as e:
        texto = respuesta_de_respaldo(estado)
        verif = verificar_texto(texto, resultados, hechos, pregunta, ignorar)
        intentos.append({"texto": texto, "verificacion": verif, "error_llm": str(e)})
    return {"respuesta": texto, "verificacion": verif,
            "_detalle": {"intentos_redaccion": len(intentos), "datos_que_parecen_instruccion": sospechosos, "verificacion": verif, "hechos_calculados": len(hechos),
                         "reglas_rag": [r["titulo"] for r in reglas]}}
