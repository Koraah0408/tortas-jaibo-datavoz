"""Verificador de cifras del Narrador y comparador de resultados de la evaluación."""

from datavoz.verificacion import calcular_hechos, extraer_numeros, verificar_texto
from metricas import comparar_resultados, puntuar_grafica, similitud_transcripcion

RES = {"columnas": ["producto", "unidades"], "filas": [["Refresco 3 L sabor uva", 12], ["Agua mineral 600 ml", 33]],
       "n_filas": 2}


def test_extrae_numeros_y_omite_nombres_de_producto():
    nums = extraer_numeros("El Refresco 3 L sabor uva vendió 12 unidades ($1,234.50), 64 % menos.",
                           ignorar=["Refresco 3 L sabor uva"])
    assert [n["valor"] for n in nums] == [12, 1234.5, 64]
    assert nums[2]["porcentaje"]


def test_cifras_reales_y_derivadas_se_verifican():
    hechos = calcular_hechos(RES)
    texto = "El refresco de uva vendió 12 unidades, 63.6 % menos que el agua mineral (33)."
    v = verificar_texto(texto, [RES], hechos, "¿qué se vendió menos?", ["Refresco 3 L sabor uva", "Agua mineral 600 ml"])
    assert v["ok"], v


def test_cifra_inventada_se_detecta():
    v = verificar_texto("Se vendieron 250 unidades en total.", [RES], calcular_hechos(RES), "pregunta")
    assert not v["ok"] and "250" in v["no_verificadas"][0]


def test_comparador_tolera_formato_ancho_y_redondeo():
    ref = {"columnas": ["mes", "ventas"], "filas": [[11, 53467.0], [12, 78203.5]], "n_filas": 2}
    gen = {"columnas": ["noviembre", "diciembre", "cambio_pct"], "filas": [[53467.004, 78203.5, 46.3]], "n_filas": 1}
    assert comparar_resultados(gen, ref, comparar=["ventas"])[0]


def test_comparador_ranking_ordenado():
    ref = {"columnas": ["producto", "u"], "filas": [["A", 10], ["B", 8]], "n_filas": 2}
    bien = {"columnas": ["producto", "unidades"], "filas": [["A", 10], ["B", 8], ["C", 5]], "n_filas": 3}
    mal = {"columnas": ["producto", "unidades"], "filas": [["B", 8], ["A", 10]], "n_filas": 2}
    assert comparar_resultados(bien, ref, clave="producto", ordenado=True)[0]
    assert not comparar_resultados(mal, ref, clave="producto", ordenado=True)[0]


def test_comparador_rechaza_volcado_de_tabla():
    ref = {"columnas": ["u"], "filas": [[1]], "n_filas": 1}
    gen = {"columnas": ["u"], "filas": [[i] for i in range(100)], "n_filas": 100}
    assert not comparar_resultados(gen, ref)[0]


def test_rubrica_grafica():
    assert puntuar_grafica("pastel", ["pastel"], ["barras"], True) == 5
    assert puntuar_grafica("barras", ["pastel"], ["barras"], True) == 4
    assert puntuar_grafica("lineas", ["pastel"], ["barras"], True) == 2
    assert puntuar_grafica(None, ["pastel"], [], False) == 1


def test_similitud_transcripcion_normaliza_numeros():
    assert similitud_transcripcion("¿Cuántas unidades de huevo de doce piezas?",
                                   "¿Cuántas unidades de huevo de 12 piezas?") == 1.0


def test_extraer_json_repara_comillas_escapadas():
    from datavoz.utilidades import extraer_json
    # Respuesta real de Gemini: escapa las comillas simples del SQL con barra invertida (no es JSON válido)
    texto = (r'{"sql": "SELECT MIN(fecha_inicio) FROM promociones\n WHERE promocion ILIKE \'%2x1 en papas%\'",'
             r' "explicacion": "fechas de la promoción", "consultas_apoyo": []}')
    r = extraer_json(texto)
    assert "ILIKE '%2x1 en papas%'" in r["sql"] and "\n" in r["sql"]


def test_extraer_json_acepta_saltos_de_linea_literales():
    from datavoz.utilidades import extraer_json
    # Respuesta real de Gemini: el SQL viene en varias líneas con saltos de línea sin escapar
    texto = '{\n  "sql": "WITH promo AS (\n    SELECT MIN(fecha_inicio) FROM promociones\n  )\n  SELECT * FROM promo",\n  "explicacion": "x"\n}'
    r = extraer_json(texto)
    assert r["sql"].startswith("WITH promo AS (") and r["sql"].count("\n") == 3
