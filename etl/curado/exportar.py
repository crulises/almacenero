"""Arma el CSV curado desde las fuentes crudas (OFF y SEPA), en la máquina del dueño.

No toca la base: lee los archivos, pasa cada fila por el normalizador (Doc 7) y deja un CSV
`catalogo_curado_v1` que se puede importar donde sea (`python -m etl.curado.importar`). Es
reproducible: mismas fuentes + misma versión del normalizador = mismo `sha256` de contenido.

    python -m etl.curado.exportar NOMBRE [--off OFF.csv.gz] [--sepa A.zip B.zip]
        [--paises en:argentina,...] [--sepa-min-filas N]

Por EAN gana la fuente de más prioridad (SEPA > OFF, como en el catálogo) y la otra completa
lo que falte. `fuente_origen` dice de cuál salió cada fila (`sepa`, `off` o `sepa+off`).
"""

import argparse
import hashlib
import json
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path

from etl.comun.catalogo import Producto, Reporte, normalizar_con_traza, normalizar_producto
from etl.comun.normalizar import NORMALIZADOR_VERSION
from etl.comun.paquete import leeme_de
from etl.comun.rutas import NombreInvalido, ruta_de_salida
from etl.curado import leeme
from etl.curado.formato import FORMATO, escribir, producto_a_fila
from etl.off.__main__ import abrir, filas, transformar
from etl.sepa.__main__ import Agrupador, leer_productos_zip

# De mayor a menor: es la prioridad por defecto del catálogo sin `curado` ni `manual`.
PRIORIDAD = ("sepa", "off")


@dataclass
class ResultadoExport:
    sha256: str
    cabecera: dict[str, str]
    filas: int = 0
    por_origen: Counter = field(default_factory=Counter)
    descartadas: Counter = field(default_factory=Counter)
    reglas: str = ""  # qué reglas del normalizador se aplicaron (también va en el LEEME.txt)

    def texto(self) -> str:
        lineas = [f"Filas escritas: {self.filas}", f"sha256 del contenido: {self.sha256}"]
        lineas += [f"  de {o}: {n}" for o, n in self.por_origen.most_common()]
        lineas += [f"  descartadas por {m}: {n}" for m, n in self.descartadas.most_common()]
        if self.reglas:
            lineas += ["", self.reglas]
        return "\n".join(lineas)


def _sha256_archivo(ruta: Path) -> str:
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        for bloque in iter(lambda: f.read(1 << 20), b""):
            h.update(bloque)
    return h.hexdigest()


def _combinar(candidatos: dict[str, Producto]) -> Producto:
    """La fuente de mayor prioridad manda; las demás completan lo que le falta."""
    ordenadas = [candidatos[f] for f in PRIORIDAD if f in candidatos]
    base = ordenadas[0]
    for otra in ordenadas[1:]:
        tamano = base if base.tamano_valor else otra  # valor y unidad siempre juntos
        base = replace(
            base,
            marca=base.marca or otra.marca,
            tamano_valor=tamano.tamano_valor,
            tamano_unidad=tamano.tamano_unidad,
            imagen_url=base.imagen_url or otra.imagen_url,
            pack_cantidad=base.pack_cantidad or otra.pack_cantidad,
            presentacion=base.presentacion or otra.presentacion,
        )
    return base


def _normalizar(p: Producto, reporte: Reporte) -> Producto:
    """Normaliza lo que dice una fuente y anota qué reglas se aplicaron (para el LEEME)."""
    nuevo, _, salida = normalizar_con_traza(p)
    reporte.trazas.agregar(salida, p.nombre, nuevo.nombre)
    return nuevo


def _leer_off(
    ruta: Path, paises: frozenset[str] | None, reporte: Reporte, limite: int | None
) -> Iterator[Producto]:
    with abrir(ruta) as archivo:
        for fila in filas(archivo):
            if limite is not None and reporte.leidas >= limite:
                return
            reporte.leidas += 1
            p = transformar(fila, reporte, paises)
            if p:
                yield p


def exportar(
    salida: Path,
    off: Path | None = None,
    sepa: list[Path] | None = None,
    paises: frozenset[str] | None = None,
    sepa_min_filas: int = 1,
    limite_off: int | None = None,
) -> ResultadoExport:
    reporte = Reporte()
    por_fuente: dict[str, dict[str, Producto]] = {"off": {}, "sepa": {}}
    if off:
        for p in _leer_off(off, paises, reporte, limite_off):
            por_fuente["off"][p.ean] = _normalizar(p, reporte)
    if sepa:
        agrupador = Agrupador(reporte)
        for ruta in sepa:
            with open(ruta, "rb") as f:
                for fila in leer_productos_zip(f, reporte.descartadas):
                    agrupador.agregar(fila)
        for p in agrupador.productos():
            if json.loads(p.datos).get("filas", 1) >= sepa_min_filas:
                por_fuente["sepa"][p.ean] = _normalizar(p, reporte)

    resultado_filas: list[dict[str, str]] = []
    por_origen: Counter = Counter()
    for e in sorted(set(por_fuente["off"]) | set(por_fuente["sepa"])):
        candidatos = {f: d[e] for f, d in por_fuente.items() if e in d}
        # Se normaliza de nuevo lo combinado: así cada fila es punto fijo del normalizador.
        p = normalizar_producto(_combinar(candidatos))[0]
        origen = "+".join(f for f in PRIORIDAD if f in candidatos)
        por_origen[origen] += 1
        resultado_filas.append(producto_a_fila(p, origen))

    entradas = [r for r in [off, *(sepa or [])] if r]
    cabecera = {
        "generado": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "normalizador": str(NORMALIZADOR_VERSION),
        "fuentes": ", ".join(f"{r.name}:{_sha256_archivo(r)}" for r in entradas) or "(ninguna)",
        "paises": ",".join(sorted(paises)) if paises else "(todos)",
        "sepa_min_filas": str(sepa_min_filas),
    }
    descartadas = Counter(reporte.descartadas)
    total_normalizados = len(por_fuente["off"]) + len(por_fuente["sepa"])
    secciones = [
        ("Qué es", leeme.seccion_que_es(FORMATO, len(resultado_filas), por_origen, cabecera)),
        (
            "Qué se hizo con los datos",
            leeme.seccion_reglas(
                reporte.trazas,
                total_normalizados,
                f"{total_normalizados} productos tal como los dicen las fuentes (antes de "
                "combinarlas por EAN)",
            ),
        ),
        (
            "Qué se descartó",
            "\n".join(f"  {m}: {n}" for m, n in descartadas.most_common()) or "  nada",
        ),
        ("Columnas", leeme.seccion_columnas(FORMATO)),
        ("Cómo importarlo", leeme.seccion_importar()),
    ]
    sha = escribir(
        salida,
        resultado_filas,
        cabecera,
        leeme=leeme_de("Catálogo curado — armado desde fuentes", secciones),
    )
    return ResultadoExport(
        sha,
        {**cabecera, "contenido_sha256": sha},
        len(resultado_filas),
        por_origen,
        descartadas,
        reglas=reporte.trazas.texto(total_normalizados),
    )


def _publicar(destino) -> str:
    """Además del disco del worker, deja el export en el almacén (S3) si hay uno configurado."""
    from etl.comun.almacen import AlmacenError, publicar_archivo

    try:
        return publicar_archivo(destino)
    except AlmacenError as e:
        return f"AVISO: no se pudo subir al almacén ({e}). El archivo local está intacto."


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("salida", help="nombre del export (sin extensión); va a ETL_EXPORT_DIR")
    ap.add_argument("--off", type=Path, help="volcado CSV de OFF (.csv o .csv.gz)")
    ap.add_argument("--sepa", type=Path, nargs="*", default=[], help="zip(s) diario(s) de SEPA")
    ap.add_argument("--paises", default="", help="tags de OFF separados por coma; vacío = todos")
    ap.add_argument("--sepa-min-filas", type=int, default=1, help="mínimo de filas por EAN")
    ap.add_argument("--limite-off", type=int, help="solo las primeras N filas de OFF")
    args = ap.parse_args()
    for ruta in [args.off, *args.sepa]:
        if ruta and not ruta.exists():
            raise SystemExit(f"No existe {ruta}.")
    if not args.off and not args.sepa:
        raise SystemExit("Hace falta al menos una fuente: --off y/o --sepa.")
    paises = frozenset(p.strip() for p in args.paises.split(",") if p.strip()) or None
    try:
        destino = ruta_de_salida(args.salida)
    except NombreInvalido as e:
        raise SystemExit(f"SALIDA: {e}") from None
    r = exportar(destino, args.off, args.sepa, paises, args.sepa_min_filas, args.limite_off)
    print(f"Escrito {destino}\n{r.texto()}")
    print(_publicar(destino))


if __name__ == "__main__":
    main()
