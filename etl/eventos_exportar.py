"""ETL `eventos_exportar` (docs/04 §11.4): saca eventos a un `.zip` en el almacén y, si se pide,
los borra de la base. **El borrado es seguro por construcción:**

1. Se leen los eventos a exportar (filtro opcional por `tipo` y `hasta`) y se **fijan sus ids**.
2. Se arman los `.zip` (CSV + LEEME.txt), partidos cada `eventos_export_filas_por_archivo` filas.
3. Cada parte se sube, **se vuelve a leer** y se compara tamaño y sha256 (`almacen.verificar`).
4. Recién con TODAS las partes verificadas, en **una transacción**, se anotan en
   `eventos_exportaciones` y se borran **solo esos ids** (no «todo lo anterior a N»: un evento que
   se confirmó tarde con un id menor no se pierde).

Si algo falla antes del paso 4 no se borra nada (y los archivos subidos quedan en el almacén, sin
anotar: son inofensivos). Lleva ids de usuario (es el dato a analizar): no se comparte afuera sin
anonimizar, y el LEEME lo dice.
"""

import asyncio
import csv
import io
import json
import zipfile
from dataclasses import dataclass
from datetime import date, datetime, timezone

from etl.comun import almacen as alm
from etl.comun.catalogo import conectar

FILAS_POR_ARCHIVO = 500_000
BORRAR_DE_A = 10_000
COLUMNAS = ("id", "tipo", "ocurrio_en", "usuario_id", "entidad", "entidad_ref", "datos")

LEEME = """Exportación de eventos de Almacenero ({generado})

Archivo: {clave}
Filas: {filas} (ids {id_desde} a {id_hasta}), parte {parte} de {partes}
Filtro: tipo = {tipo}, hasta = {hasta}

Columnas de eventos.csv:
  id           identificador del evento
  tipo         p. ej. producto.escaneado, app.abierta
  ocurrio_en   instante en UTC (ISO-8601 con Z); lo pone el servidor
  usuario_id   uuid del usuario (vacío si la cuenta se dio de baja)
  entidad / entidad_ref   sobre qué fue (p. ej. producto / EAN)
  datos        JSON propio de cada tipo

PRIVACIDAD: este archivo es de ANÁLISIS INTERNO. Lleva ids de usuario; no lo compartas fuera del
proyecto sin anonimizarlo antes.
"""


@dataclass
class Parte:
    clave: str
    datos: bytes
    filas: int
    id_desde: int
    id_hasta: int
    sha256: str


def _iso(t: datetime) -> str:
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def armar_zip(filas: list, clave: str, parte: int, partes: int, tipo, hasta) -> bytes:
    """Un `.zip` determinista (fechas fijas): mismas filas = mismos bytes = mismo sha256."""
    csv_buf = io.StringIO()
    w = csv.writer(csv_buf, lineterminator="\n")
    w.writerow(COLUMNAS)
    for r in filas:
        w.writerow(
            [
                r["id"],
                r["tipo"],
                _iso(r["ocurrio_en"]),
                r["usuario_id"] or "",
                r["entidad"] or "",
                r["entidad_ref"] or "",
                json.dumps(json.loads(r["datos"]), ensure_ascii=False, sort_keys=True),
            ]
        )
    leeme = LEEME.format(
        generado=_iso(datetime.now(timezone.utc)),
        clave=clave,
        filas=len(filas),
        id_desde=filas[0]["id"],
        id_hasta=filas[-1]["id"],
        parte=parte,
        partes=partes,
        tipo=tipo or "todos",
        hasta=hasta or "sin límite",
    )
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for nombre, contenido in (("eventos.csv", csv_buf.getvalue()), ("LEEME.txt", leeme)):
            info = zipfile.ZipInfo(nombre, date_time=(2024, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, contenido.encode())
    return out.getvalue()


async def exportar(p: dict, ctx, almacen=None) -> dict:
    almacen = almacen or alm.desde_entorno()
    tipo = p.get("tipo") or None
    hasta = p.get("hasta") or None
    borrar = bool(p.get("borrar", False))
    conn = await conectar()
    try:
        por_archivo = await conn.fetchval(
            "select valor::text::int from config where clave = 'eventos_export_filas_por_archivo' "
            "and rubro is null"
        )
        por_archivo = int(p.get("filas_por_archivo") or por_archivo or FILAS_POR_ARCHIVO)
        # 1. Los eventos de esta exportación, con sus ids fijados.
        filas = await conn.fetch(
            """
            select id, tipo, ocurrio_en, usuario_id, entidad, entidad_ref, datos::text as datos
              from eventos
             where ($1::text is null or tipo = $1)
               and ($2::date is null or ocurrio_en < (($2::date + 1)::timestamp at time zone 'UTC'))
             order by id
            """,
            tipo,
            None if hasta is None else date.fromisoformat(hasta),
        )
        if not filas:
            ctx.log("No hay eventos que exportar con ese filtro.")
            ctx.filas = 0
            return {"filas": 0, "partes": 0, "borradas": 0}
        ctx.log(f"{len(filas)} eventos (ids {filas[0]['id']} a {filas[-1]['id']}).")
        await asyncio.to_thread(almacen.asegurar)

        # 2 y 3. Armar, subir y verificar cada parte. Nada se borra hasta que todas estén.
        trozos = [filas[i : i + por_archivo] for i in range(0, len(filas), por_archivo)]
        sello = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        partes: list[Parte] = []
        for n, trozo in enumerate(trozos, 1):
            clave = f"eventos/eventos-{sello}-{trozo[0]['id']}-{trozo[-1]['id']}.zip"
            datos = await asyncio.to_thread(armar_zip, trozo, clave, n, len(trozos), tipo, hasta)
            await asyncio.to_thread(alm.verificar, almacen, clave, datos)
            partes.append(
                Parte(clave, datos, len(trozo), trozo[0]["id"], trozo[-1]["id"], alm.sha256(datos))
            )
            ctx.log(f"Parte {n}/{len(trozos)} guardada y verificada: {clave} ({len(datos)} bytes)")

        # 4. Anotar y (si se pidió) borrar, en una sola transacción. Solo los ids exportados.
        borradas = 0
        async with conn.transaction():
            for parte, trozo in zip(partes, trozos, strict=True):
                await conn.execute(
                    """
                    insert into eventos_exportaciones (ejecucion_id, tipo, id_desde, id_hasta,
                        filas, sha256, tamano, clave, almacen, borradas)
                    values ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                    """,
                    ctx.ejecucion_id,
                    tipo,
                    parte.id_desde,
                    parte.id_hasta,
                    parte.filas,
                    parte.sha256,
                    len(parte.datos),
                    parte.clave,
                    almacen.nombre,
                    parte.filas if borrar else 0,
                )
                if borrar:
                    ids = [r["id"] for r in trozo]
                    for i in range(0, len(ids), BORRAR_DE_A):
                        r = await conn.execute(
                            "delete from eventos where id = any($1::bigint[])",
                            ids[i : i + BORRAR_DE_A],
                        )
                        borradas += int(r.split()[-1])
        ctx.filas = len(filas)
        ctx.log(
            f"Listo: {len(partes)} archivo(s), {borradas} eventos borrados"
            if borrar
            else f"Listo: {len(partes)} archivo(s); no se borró nada (borrar = no)."
        )
        return {
            "filas": len(filas),
            "partes": len(partes),
            "borradas": borradas,
            "id_desde": filas[0]["id"],
            "id_hasta": filas[-1]["id"],
            "almacen": almacen.nombre,
            "archivos": [x.clave for x in partes],
        }
    finally:
        await conn.close()
