"""Prepara todo lo necesario para ejecutar DataVoz.

1. Genera los datos sintéticos (si no existen).
2. Limpia y carga las ventas, el catálogo, el inventario y las promociones en DuckDB.
3. Construye el índice RAG en ChromaDB (diccionario, reglas, catálogo y ejemplos).

Uso:
    python scripts/preparar_base.py           # solo lo que falte
    python scripts/preparar_base.py --forzar  # reconstruye la base
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from datavoz.datos import construir_base_ejemplo  # noqa: E402
from datavoz.rag import obtener_base  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--forzar", action="store_true", help="reconstruye la base aunque ya exista")
    args = ap.parse_args()
    resumen = construir_base_ejemplo(forzar=args.forzar)
    print("Base de datos lista:", resumen)
    print("Documentos en el índice RAG:", obtener_base().coleccion.count())


if __name__ == "__main__":
    main()
