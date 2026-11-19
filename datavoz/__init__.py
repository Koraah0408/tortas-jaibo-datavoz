"""DataVoz · Háblale a tus datos.

Sistema multiagente (LangGraph) que convierte preguntas en lenguaje natural,
por texto o voz, en consultas SQL de solo lectura, gráficas y explicaciones
para una tienda de abarrotes.
"""

import sys

__version__ = "1.0.0"

# En Windows la consola usa cp1252; forzamos UTF-8 para acentos y símbolos.
for _flujo in (sys.stdout, sys.stderr):
    if hasattr(_flujo, "reconfigure"):
        try:
            _flujo.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # pragma: no cover
            pass
