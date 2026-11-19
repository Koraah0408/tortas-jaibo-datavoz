import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "evaluacion"))


@pytest.fixture(scope="session")
def base_ejemplo():
    from datavoz.datos import construir_base_ejemplo
    from datavoz.config import obtener_config
    construir_base_ejemplo()
    return str(obtener_config().ruta_db)


@pytest.fixture
def oraculo():
    """Instala el LLM simulado durante la prueba y lo retira al final."""
    from datavoz.llm import establecer_simulador
    from simulador import OraculoLLM
    o = OraculoLLM(sql_erroneo_primero={"S02"}, sql_semantico_malo_primero={"M01"}, json_roto_primero={"S05"})
    establecer_simulador(o)
    yield o
    establecer_simulador(None)


@pytest.fixture(autouse=True)
def costos_de_plantilla(monkeypatch):
    """Las pruebas usan la plantilla de costos, nunca el archivo real del dueño (data/jaibo/costos.yaml)."""
    if not __import__("os").getenv("JAIBO_COSTOS"):
        monkeypatch.setenv("JAIBO_COSTOS", str(RAIZ / "conocimiento" / "jaibo" / "costos.ejemplo.yaml"))
