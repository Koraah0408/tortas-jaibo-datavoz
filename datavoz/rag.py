"""RAG con ChromaDB: diccionario de datos, reglas del negocio, catálogo y ejemplos pregunta–SQL.

El índice se construye a partir de los archivos de ``conocimiento/`` y del
catálogo de productos. Se reconstruye solo si cambia el contenido (huella SHA-1).
Los embeddings se calculan localmente (modelo ONNX de ChromaDB), por lo que el
RAG no consume cuota del modelo de lenguaje.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from .config import obtener_config
from .utilidades import normalizar

logging.getLogger("chromadb").setLevel(logging.ERROR)

COLECCION = "conocimiento_datavoz"
# Reordenamiento híbrido: cuánto baja la distancia coseno cada palabra clave compartida
PESO_TITULO = 0.06   # por palabra en el título (pregunta del ejemplo o nombre de la sección)
PESO_TEXTO = 0.08    # por la fracción de palabras de la pregunta que aparecen en el texto


@dataclass
class Documento:
    id: str
    texto: str
    tipo: str      # diccionario | regla | ejemplo | catalogo
    fuente: str
    titulo: str = ""
    dominio: str = "abarrotes"  # negocio al que pertenece: abarrotes (datos de ejemplo) | jaibo


def _secciones_markdown(ruta: Path, tipo: str, dominio: str = "abarrotes") -> list[Documento]:
    texto = ruta.read_text(encoding="utf-8")
    docs = []
    for i, bloque in enumerate(re.split(r"\n(?=## )", texto)):
        bloque = bloque.strip()
        if not bloque.startswith("## "):
            continue
        titulo = bloque.splitlines()[0][3:].strip()
        docs.append(Documento(f"{dominio}-{tipo}-{i}", bloque, tipo, ruta.name, titulo, dominio))
    return docs


def _paquete(d: Path, dominio: str) -> list[Documento]:
    """Diccionario, reglas y ejemplos pregunta–SQL de un negocio."""
    docs = _secciones_markdown(d / "diccionario_datos.md", "diccionario", dominio)
    docs += _secciones_markdown(d / "reglas_negocio.md", "regla", dominio)
    ejemplos = yaml.safe_load((d / "ejemplos_sql.yaml").read_text(encoding="utf-8"))
    for i, ej in enumerate(ejemplos):
        docs.append(Documento(f"{dominio}-ejemplo-{i}", f"Pregunta: {ej['pregunta']}\nSQL:\n{ej['sql'].strip()}",
                              "ejemplo", "ejemplos_sql.yaml", ej["pregunta"], dominio))
    return docs


def cargar_documentos(dir_conocimiento: Path | None = None, catalogo=None) -> list[Documento]:
    """Conocimiento de cada negocio: abarrotes (datos de ejemplo) y Tortas Jaibo (conocimiento/jaibo)."""
    cfg = obtener_config()
    d = Path(dir_conocimiento or cfg.dir_conocimiento)
    docs = _paquete(d, "abarrotes")
    if (d / "jaibo" / "diccionario_datos.md").exists():
        docs += _paquete(d / "jaibo", "jaibo")
    if catalogo is not None and len(catalogo):
        for i, (cat, grupo) in enumerate(catalogo.groupby("categoria")):
            lineas = [f"- {r.producto} (precio de lista ${r.precio_lista:.2f})" for r in grupo.itertuples()]
            docs.append(Documento(f"abarrotes-catalogo-{i}", f"## Catálogo · categoría {cat}\nProductos de la "
                                  f"categoría '{cat}':\n" + "\n".join(lineas), "catalogo", "productos",
                                  f"Catálogo {cat}", "abarrotes"))
    return docs


class BaseConocimiento:
    """Envoltura sobre una colección persistente de ChromaDB."""

    def __init__(self, ruta: Path | None = None):
        import chromadb
        from chromadb.config import Settings

        cfg = obtener_config()
        self.ruta = Path(ruta or cfg.dir_chroma)
        self.ruta.mkdir(parents=True, exist_ok=True)
        self.cliente = chromadb.PersistentClient(path=str(self.ruta),
                                                 settings=Settings(anonymized_telemetry=False))
        self.coleccion = self.cliente.get_or_create_collection(COLECCION, metadata={"hnsw:space": "cosine"})

    def huella_actual(self) -> str | None:
        return (self.coleccion.metadata or {}).get("huella")

    def indexar(self, documentos: list[Documento], forzar: bool = False) -> bool:
        """Indexa los documentos si cambiaron. Devuelve True si reconstruyó el índice."""
        huella = hashlib.sha1("\n".join(d.id + d.dominio + d.texto for d in documentos).encode("utf-8")).hexdigest()
        if not forzar and self.huella_actual() == huella and self.coleccion.count() == len(documentos):
            return False
        self.cliente.delete_collection(COLECCION)
        self.coleccion = self.cliente.create_collection(COLECCION, metadata={"hnsw:space": "cosine", "huella": huella})
        self.coleccion.add(ids=[d.id for d in documentos], documents=[d.texto for d in documentos],
                           metadatas=[{"tipo": d.tipo, "fuente": d.fuente, "titulo": d.titulo, "dominio": d.dominio}
                                      for d in documentos])
        return True

    def buscar(self, consulta: str, tipos: list[str] | None = None, k: int = 4, dominio: str | None = None) -> list[dict]:
        if self.coleccion.count() == 0:
            return []
        condiciones = ([{"tipo": {"$in": tipos}}] if tipos else []) + ([{"dominio": dominio}] if dominio else [])
        filtro = condiciones[0] if len(condiciones) == 1 else ({"$and": condiciones} if condiciones else None)
        # Búsqueda híbrida: el modelo de embeddings local (MiniLM) entiende poco español, así que se piden
        # más candidatos y se reordenan premiando las palabras clave que comparten con la pregunta
        try:
            r = self.coleccion.query(query_texts=[consulta], n_results=max(k * 3, 12), where=filtro)
        except Exception as e:  # otro proceso reconstruyó el índice: se vuelve a abrir la colección por nombre
            if "does not exist" not in str(e):
                raise
            self.coleccion = self.cliente.get_or_create_collection(COLECCION, metadata={"hnsw:space": "cosine"})
            r = self.coleccion.query(query_texts=[consulta], n_results=max(k * 3, 12), where=filtro)
        q = set(_tokens(consulta))
        candidatos = []
        for doc, meta, dist in zip(r["documents"][0], r["metadatas"][0], r["distances"][0]):
            titulo = meta.get("titulo", "")
            en_titulo = len(q & set(_tokens(titulo)))
            en_texto = len(q & set(_tokens(doc))) / max(1, len(q))
            puntaje = float(dist) - PESO_TITULO * en_titulo - PESO_TEXTO * en_texto
            candidatos.append((puntaje, {"texto": doc, "tipo": meta["tipo"], "titulo": titulo,
                                         "fuente": meta.get("fuente", ""), "distancia": round(float(dist), 4)}))
        candidatos.sort(key=lambda c: c[0])
        return [c[1] for c in candidatos[:k]]


_base: BaseConocimiento | None = None


def obtener_base() -> BaseConocimiento:
    global _base
    if _base is None:
        _base = BaseConocimiento()
    return _base


def asegurar_indice(catalogo=None) -> bool:
    """Construye el índice si no existe o cambió el conocimiento."""
    return obtener_base().indexar(cargar_documentos(catalogo=catalogo))


# ---------------------------------------------------------------------------
# Búsqueda de productos (léxica, sobre los productos reales de la base activa)
# ---------------------------------------------------------------------------
_PALABRAS_VACIAS = set("""de del la el los las un una unos unas en y o que se me mi mis por para con sin al a
cual cuales cuanto cuantos cuanta cuantas como cuando donde fue fueron vendio vendieron vendi vende venden
mas menos producto productos ventas venta vendido vendidos vendida mes meses dia dias semana ano anio total
este esta ese esa eso lo le les su sus hay hubo tuvo tienda dinero unidades piezas cree crees paso porque
por que y en tambien solo cada entre comparado compara contra vs year mejor peor""".split())


def _tokens(texto: str) -> list[str]:
    toks = re.findall(r"[a-z0-9ñ]+", normalizar(texto))
    salida = []
    for t in toks:
        if t in _PALABRAS_VACIAS or (len(t) < 3 and not t.isdigit()):
            continue
        if len(t) > 4 and t.endswith("es") and not t.endswith("ces"):
            t = t[:-2]
        elif len(t) > 3 and t.endswith("s"):
            t = t[:-1]
        salida.append(t)
    return salida


def buscar_categorias(pregunta: str, categorias: list[str]) -> list[str]:
    """Categorías que menciona la pregunta (por la primera palabra: «bebidas», «cervezas», «lácteos»...)."""
    q = set(_tokens(pregunta))
    encontradas = []
    for c in categorias:
        tc = _tokens(c)
        if tc and tc[0] in q:
            encontradas.append(c)
    return encontradas


def buscar_productos(pregunta: str, productos: list[str], k: int = 6, categorias: list[str] | None = None) -> list[str]:
    """Devuelve los nombres exactos de productos que la pregunta parece mencionar.

    Las palabras que nombran una categoría («bebida», «botanas»...) no cuentan como producto,
    para que «¿qué bebida se vendió menos?» no se confunda con «Bebida isotónica 600 ml».
    """
    q = set(_tokens(pregunta))
    q -= {str(n) for n in range(1900, 2100)}
    for c in buscar_categorias(pregunta, categorias or []):
        q.discard(_tokens(c)[0])
    if not q:
        return []
    puntajes = []
    for p in productos:
        tp = set(_tokens(p))
        coincidencias = sum(1 for t in q if any(x == t or (len(t) >= 4 and x.startswith(t)) or
                                                 (len(x) >= 4 and t.startswith(x)) for x in tp))
        if coincidencias:
            puntajes.append((coincidencias, -len(p), p))
    if not puntajes:
        return []
    puntajes.sort(reverse=True)
    maximo = puntajes[0][0]
    umbral = maximo if maximo >= 2 else 1
    return [p for s, _, p in puntajes if s >= umbral][:k]


# ---------------------------------------------------------------------------
# Grupos de productos del negocio ("tortas" = Barda, Pierna, Mixta, Torta de barbacoa…)
# ---------------------------------------------------------------------------
_grupos_cache: dict[str, list[dict]] = {}


def grupos_del_negocio(dominio: str) -> list[dict]:
    if dominio not in _grupos_cache:
        ruta = obtener_config().dir_conocimiento / dominio / "grupos_productos.yaml"
        _grupos_cache[dominio] = yaml.safe_load(ruta.read_text(encoding="utf-8")) if ruta.exists() else []
    return _grupos_cache[dominio]


def _coincide_patron(nombre: str, patron: str) -> bool:
    partes = [re.escape(normalizar(p)) for p in patron.split("%")]
    return re.fullmatch(".*".join(partes), normalizar(nombre)) is not None


def buscar_grupos(pregunta: str, productos: list[str], dominio: str) -> list[dict]:
    """Grupos del negocio que menciona la pregunta, resueltos contra los productos que existen en la base.

    Si una palabra está contenida en otra más específica que también aparece (p. ej. "pan" dentro
    de "pan mega"), solo se usa el grupo más específico.
    """
    texto = f" {normalizar(pregunta)} "
    encontrados = []
    for g in grupos_del_negocio(dominio):
        palabras = [p for p in g.get("palabras", []) if re.search(rf"\b{re.escape(normalizar(p))}\b", texto)]
        if not palabras:
            continue
        miembros = [p for p in productos if any(_coincide_patron(p, pat) for pat in g.get("patrones", []))]
        if miembros:
            encontrados.append({"grupo": g["grupo"], "palabra": max(palabras, key=len), "productos": miembros,
                                "nota": g.get("nota", ""), "excluye": g.get("excluye", [])})
    # Si la pregunta nombra un producto concreto que contiene la palabra del grupo ("Mega barda" ⊃ "mega",
    # "Tacos de barbacoa" ⊃ "barbacoa"), manda el producto y no el grupo
    nombrados = [normalizar(p) for p in productos if re.search(rf"\b{re.escape(normalizar(p))}\b", texto)]
    excluidos = {e for g in encontrados for e in g.get("excluye", [])}
    return [g for g in encontrados
            if g["grupo"] not in excluidos
            if not any(o is not g and g["palabra"] in o["palabra"] and len(o["palabra"]) > len(g["palabra"])
                       for o in encontrados)
            and not any(len(n) > len(g["palabra"]) and re.search(rf"\b{re.escape(g['palabra'])}\b", n)
                        for n in nombrados)]
