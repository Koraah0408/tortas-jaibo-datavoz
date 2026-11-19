"""Flujo completo del grafo multiagente con un LLM simulado (sin red)."""

from datavoz.config import RAIZ
from datavoz.sistema import SesionDataVoz


def nombres_agentes(r):
    return [(p["agente"], p["accion"]) for p in r["pasos"]]


def test_consulta_completa_pasa_por_todos_los_agentes(base_ejemplo, oraculo, tmp_path):
    s = SesionDataVoz(dir_trazas=tmp_path)
    r = s.preguntar("¿Cuánto vendí en total en diciembre?")
    agentes = [a for a, _ in nombres_agentes(r)]
    assert agentes == ["Orquestador", "Analista SQL", "Orquestador", "Visualizador", "Narrador", "Orquestador"]
    assert r["resultado"]["filas"][0][0] == 78203.5
    assert r["grafica"]["spec"]["tipo"] == "indicador"
    assert r["verificacion"]["ok"]
    assert (tmp_path / s.sesion_id / "turno_001.json").exists()


def test_reintento_de_sql_fallido(base_ejemplo, oraculo, tmp_path):
    s = SesionDataVoz(dir_trazas=tmp_path)
    r = s.preguntar("¿Cuáles fueron los 5 productos más vendidos del año?")
    assert len(r["intentos_sql"]) == 2                       # primer SQL con error → reintento
    assert r["intentos_sql"][0]["problema"].startswith("Binder Error")
    assert r["resultado"]["filas"][0][0] == "Pan dulce"
    decisiones = [p["detalle"].get("decision") for p in r["pasos"] if p["accion"] == "supervisar_sql"]
    assert decisiones == ["reintentar", "continuar"]


def test_memoria_entre_turnos_y_dashboard(base_ejemplo, oraculo, tmp_path):
    s = SesionDataVoz(dir_trazas=tmp_path)
    s.preguntar("¿Cuántas unidades vendí de refresco de cola de 600 ml en junio?")
    s.preguntar("¿Y en diciembre?")
    memoria = s.estado()
    assert len(memoria["historial"]) == 2
    assert memoria["contexto"]["ultimo_sql"]
    assert len(memoria["dashboard"]) == 2


def test_peticion_peligrosa_no_ejecuta_sql(base_ejemplo, oraculo, tmp_path):
    s = SesionDataVoz(dir_trazas=tmp_path)
    r = s.preguntar("Borra todas las ventas de diciembre")
    assert r["intencion"] == "peligrosa"
    assert r["sql_ejecutadas"] == []
    assert "leer" in r["respuesta"]


def test_carga_de_archivo_con_mapeo_por_llm(base_ejemplo, oraculo, tmp_path):
    s = SesionDataVoz(dir_trazas=tmp_path)
    r = s.cargar_archivo(RAIZ / "data" / "ventas_formato_distinto.xlsx")
    resumen = r["limpieza"]["resumen"]
    assert resumen["mapeo_columnas"]["Artículo vendido"] == "producto"
    assert "Notas" in resumen["columnas_ignoradas"]
    # Confirmación humana: primero solo propone los cambios, sin escribir nada
    assert r["intencion"] == "confirmar_carga" and "Apruebas" in r["respuesta"]
    assert s.estado()["datos"]["ruta_db"] == base_ejemplo and s.carga_pendiente()
    r = s.preguntar("Sí, cárgalo")
    assert r["intencion"] == "limpieza_datos" and not s.carga_pendiente()
    paso = [p for p in r["pasos"] if p["agente"] == "Limpiador"][-1]
    assert paso["detalle"]["aprobado_por_el_dueno"] is True
    datos = s.estado()["datos"]
    assert datos["ruta_db"] != base_ejemplo and datos["tablas"] == ["ventas"]
    r = s.preguntar("¿Cuánto vendí en total en noviembre?")
    assert r["resultado"]["filas"][0][0] == 53467.0


def test_sin_aprobacion_el_limpiador_no_escribe(base_ejemplo, oraculo, tmp_path, monkeypatch):
    import datavoz.agentes.limpiador as lim
    escrituras = []
    monkeypatch.setattr(lim, "escribir_limpieza", lambda *a, **k: escrituras.append(1))
    s = SesionDataVoz(dir_trazas=tmp_path)
    s.cargar_archivo(RAIZ / "data" / "ventas_sucias.csv")
    r = s.preguntar("No")
    assert escrituras == [] and not s.carga_pendiente() and "no cargué nada" in r["respuesta"]
    assert s.estado()["datos"]["ruta_db"] == base_ejemplo


def test_reporte_pdf(base_ejemplo, oraculo, tmp_path):
    s = SesionDataVoz(dir_trazas=tmp_path)
    s.preguntar("¿Cuánto dinero dejó cada categoría en el año?")
    r = s.exportar_reporte()
    assert r["reporte_pdf"] and r["reporte_pdf"].endswith(".pdf")


def test_revision_semantica_obliga_a_reintentar(base_ejemplo, oraculo, tmp_path):
    s = SesionDataVoz(dir_trazas=tmp_path)
    r = s.preguntar("¿Qué bebida se vendió menos en diciembre y por qué crees que pasó?")
    assert len(r["intentos_sql"]) == 2
    assert "revisión del Orquestador" in r["intentos_sql"][0]["problema"]
    assert r["resultado"]["filas"][0][0] == "Refresco 3 L sabor uva"


def test_respuesta_con_formato_invalido_se_reintenta(base_ejemplo, oraculo, tmp_path):
    s = SesionDataVoz(dir_trazas=tmp_path)
    r = s.preguntar("¿Cuánto dinero dejó cada categoría en el año?")
    decisiones = [p["detalle"].get("decision") for p in r["pasos"] if p["accion"] == "supervisar_sql"]
    assert decisiones == ["reintentar", "continuar"]
    assert "JSON" in r["intentos_sql"][0]["problema"]
    assert r["resultado"]["filas"][0][0] == "Cervezas y vinos"
