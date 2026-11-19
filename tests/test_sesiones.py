"""Sesiones guardadas en disco (SQLite): se cierran, se reabren con su memoria y se pueden borrar."""

import pytest

from datavoz import sesiones
from datavoz.config import obtener_config
from datavoz.sistema import SesionDataVoz


@pytest.fixture
def carpeta_sesiones(tmp_path):
    cfg = obtener_config()
    original = cfg.dir_sesiones
    sesiones.reiniciar_para_pruebas()
    cfg.dir_sesiones = tmp_path
    yield tmp_path
    sesiones.reiniciar_para_pruebas()
    cfg.dir_sesiones = original


def test_sesion_se_guarda_y_se_reabre(base_ejemplo, oraculo, carpeta_sesiones, tmp_path):
    s = SesionDataVoz(persistente=True, dir_trazas=tmp_path / "trazas")
    s.preguntar("¿Cuántas unidades vendí de refresco de cola de 600 ml en junio?")
    s.preguntar("¿Y en diciembre?")
    sesion_id = s.sesion_id

    catalogo = sesiones.listar()
    assert [x["id"] for x in catalogo] == [sesion_id]
    assert catalogo[0]["turnos"] == 2
    assert catalogo[0]["nombre"].startswith("¿Cuántas unidades vendí de refresco")

    # "Cerrar la app": se crea un objeto nuevo con el mismo id
    reabierta = SesionDataVoz(sesion_id=sesion_id, persistente=True, dir_trazas=tmp_path / "trazas")
    memoria = reabierta.estado()
    assert len(memoria["historial"]) == 2
    assert memoria["dashboard"] == []  # un solo número no genera tarjeta
    assert memoria["contexto"]["ultimo_sql"]
    r = reabierta.preguntar("¿Y del de 2 litros?")          # la memoria sigue funcionando
    assert r["resultado"]["filas"][0][0] == 47
    assert sesiones.obtener(sesion_id)["turnos"] == 3


def test_renombrar_y_eliminar(base_ejemplo, oraculo, carpeta_sesiones, tmp_path):
    s = SesionDataVoz(persistente=True, dir_trazas=tmp_path / "trazas")
    s.preguntar("¿Cuánto vendí en total en diciembre?")
    sesiones.renombrar(s.sesion_id, "Cierre de diciembre")
    assert sesiones.obtener(s.sesion_id)["nombre"] == "Cierre de diciembre"
    sesiones.eliminar(s.sesion_id)
    assert sesiones.listar() == []
    assert SesionDataVoz(sesion_id=s.sesion_id, persistente=True).estado()["historial"] == []


def test_sesion_sin_preguntas_no_se_guarda(base_ejemplo, carpeta_sesiones):
    SesionDataVoz(persistente=True)
    assert sesiones.listar() == []
