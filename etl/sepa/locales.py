"""ETL de SEPA / Precios Claros: sucursales -> `locales`.

El zip diario trae, por comercio, `comercio.csv` (la bandera: «Carrefour», «Día»…) y
`sucursales.csv` (nombre, calle, número, coordenadas, provincia). Se cargan las
sucursales que tengan **nombre, calle y coordenadas válidas** (el número de puerta no
hace falta). Entran con `verificado = false`, `creado_por = null` y `fuente = 'sepa'`;
el vínculo `local_fuentes` guarda `id_comercio-id_bandera-id_sucursal`. Si ya hay un
local parecido a pocos metros (por ejemplo el mismo comercio cargado desde OSM), no se
crea otro: se le agrega el vínculo.

    python -m etl.sepa.locales ARCHIVO.zip [...] [--provincia misiones]

Datos: Secretaría de Comercio / Precios Claros (SEPA), CC BY 4.0.
"""

import argparse
import asyncio
import io
import re
import sys
import zipfile
from collections import Counter
from collections.abc import Iterator
from pathlib import Path

from etl.comun.catalogo import conectar
from etl.comun.locales import Local, ReporteLocales, fusionar_locales
from etl.comun.provincias import codigo_provincia
from etl.sepa.__main__ import _filas_csv, iniciales

FUENTE = "sepa"
# «Sucursal 1», «Local 12», «Suc. 3», «12»: no dicen dónde está, no aportan al nombre.
_GENERICO = re.compile(r"^(sucursal|suc\.?|local|sede)?\s*(n[°ºo.]?\s*)?\d*$", re.IGNORECASE)
# Argentina continental e Islas: caja grande, solo para descartar basura (0,0 o invertidas).
_LAT = (-56.0, -21.0)
_LNG = (-74.0, -53.0)


def _clave(fila: dict[str, str]) -> tuple[str, str]:
    return ((fila.get("id_comercio") or "").strip(), (fila.get("id_bandera") or "").strip())


def leer_sucursales_zip(
    binario: io.BufferedIOBase, invalidos: Counter | None = None
) -> Iterator[dict[str, str]]:
    """Filas de `sucursales.csv` con el nombre de la bandera agregado como
    `bandera`. Mismo recorrido tolerante que `leer_productos_zip`."""
    try:
        z = zipfile.ZipFile(binario)
    except zipfile.BadZipFile:
        if invalidos is not None:
            invalidos["zip_interno_invalido"] += 1
        return
    with z:
        nombres = [n for n in z.namelist() if not n.endswith("/")]
        for nombre in nombres:
            if nombre.endswith(".zip"):
                with z.open(nombre) as interno:
                    yield from leer_sucursales_zip(io.BytesIO(interno.read()), invalidos)
        comercio = next((n for n in nombres if n.endswith("comercio.csv")), None)
        sucursales = next((n for n in nombres if n.endswith("sucursales.csv")), None)
        if comercio is None or sucursales is None:
            return
        banderas: dict[tuple[str, str], str] = {}
        with z.open(comercio) as f:
            for fila in _filas_csv(f):
                clave = _clave(fila)
                banderas[clave] = (fila.get("comercio_bandera_nombre") or "").strip()
        with z.open(sucursales) as f:
            for fila in _filas_csv(f):
                clave = _clave(fila)
                fila["bandera"] = banderas.get(clave, "")
                yield fila


def _numero(valor: str | None) -> float | None:
    try:
        return float((valor or "").strip().replace(",", "."))
    except ValueError:
        return None


def nombre_local(bandera: str, sucursal: str) -> str:
    """Bandera + nombre de la sucursal si dice algo («Carrefour Acassuso»); si es
    genérico («Sucursal 3») o ya repite la bandera, solo la bandera."""
    bandera = " ".join(bandera.split())
    sucursal = " ".join(sucursal.split())
    if not bandera:
        nombre = sucursal
    elif _GENERICO.match(sucursal) or bandera.lower() in sucursal.lower():
        nombre = sucursal if bandera.lower() in sucursal.lower() else bandera
    else:
        nombre = f"{iniciales(bandera)} {iniciales(sucursal)}"
    return iniciales(nombre)


def transformar(
    fila: dict[str, str], reporte: ReporteLocales, provincia: str | None
) -> Local | None:
    """Una fila de sucursales -> `Local`, o None si se descarta (y se cuenta por qué)."""
    reporte.leidos += 1
    if provincia and (fila.get("sucursales_provincia") or "").strip().upper() != provincia:
        reporte.descartados["otra_provincia"] += 1
        return None
    nombre = nombre_local(fila.get("bandera", ""), fila.get("sucursales_nombre") or "")
    if len(nombre) < 2 or _GENERICO.match(nombre):
        reporte.descartados["sin_nombre"] += 1
        return None
    calle = " ".join((fila.get("sucursales_calle") or "").split())
    if len(calle) < 2:
        reporte.descartados["sin_calle"] += 1
        return None
    lat = _numero(fila.get("sucursales_latitud"))
    lng = _numero(fila.get("sucursales_longitud"))
    if lat is None or lng is None or not (_LAT[0] <= lat <= _LAT[1] and _LNG[0] <= lng <= _LNG[1]):
        reporte.descartados["sin_coordenadas"] += 1
        return None
    numero = (fila.get("sucursales_numero") or "").strip()
    localidad = " ".join((fila.get("sucursales_localidad") or "").split())
    direccion = iniciales(calle) + (f" {numero}" if numero and numero != "0" else "")
    if localidad:
        direccion += f", {iniciales(localidad)}"
    ref = "-".join(
        (fila.get(k) or "").strip() for k in ("id_comercio", "id_bandera", "id_sucursal")
    )
    return Local(
        fuente=FUENTE,
        ref=ref,
        nombre=nombre,
        direccion=direccion,
        lat=lat,
        lng=lng,
        datos={
            "bandera": fila.get("bandera") or None,
            "nombre": (fila.get("sucursales_nombre") or "").strip() or None,
            "tipo": (fila.get("sucursales_tipo") or "").strip() or None,
            "calle": calle,
            "numero": numero or None,
            "localidad": localidad or None,
            "provincia": (fila.get("sucursales_provincia") or "").strip() or None,
        },
    )


async def cargar(rutas: list[Path], provincia: str | None = None) -> ReporteLocales:
    reporte = ReporteLocales()
    provincia = codigo_provincia(provincia) if provincia else None
    locales: dict[str, Local] = {}  # por ref: la misma sucursal viene en varios zips diarios
    for ruta in rutas:
        with open(ruta, "rb") as f:
            for fila in leer_sucursales_zip(f, reporte.descartados):
                local = transformar(fila, reporte, provincia)
                if local is not None:
                    locales[local.ref] = local
        print(f"  ... {ruta.name}: {reporte.leidos} sucursales", file=sys.stderr, flush=True)
    conn = await conectar()
    try:
        await fusionar_locales(conn, locales.values(), reporte)
    finally:
        await conn.close()
    return reporte


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("archivos", type=Path, nargs="+", help="zip(s) diario(s) de SEPA")
    ap.add_argument(
        "--provincia",
        help="solo esta provincia (slug o código, p. ej. misiones o AR-N); sin esto, todo el país",
    )
    args = ap.parse_args()
    for a in args.archivos:
        if not a.exists():
            raise SystemExit(f"No existe {a}. Ver `make etl-sepa-descargar`.")
    print(asyncio.run(cargar(args.archivos, args.provincia)).texto())


if __name__ == "__main__":
    main()
