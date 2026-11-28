# ruff: noqa: E501
"""Respaldo y restauración de la base (formato `respaldo_v1`), en Python puro.

Sirve para el panel (ETL `respaldo_crear` / `respaldo_restaurar`) y para `make db-dump` /
`make db-restore`: el mismo código, sin `pg_dump` (que el contenedor del backend no tiene) y sin
las trampas de restaurar un dump viejo sobre un esquema nuevo (ver docs/03, «Recuperar la base»).

Un respaldo es un `.zip` con `manifest.json`, `LEEME.txt` y `datos/<tabla>.csv` (una por tabla de
`public`, sin `spatial_ref_sys`, sin los archivos subidos al panel ni el historial de ejecuciones
de ETL; los eventos solo si se pide). Se guarda en el **almacén de exportaciones** (disco o S3,
`etl/comun/almacen.py`) bajo `respaldo/`, y se vuelve a leer para verificarlo.

Restaurar **reemplaza** los datos de las tablas que trae el respaldo. Por eso:
- sin `aplicar` es un simulacro (compara y no escribe nada);
- con `aplicar` hace antes un respaldo de seguridad (`respaldo/antes-de-restaurar-*.zip`) y exige
  la palabra `RESTAURAR`;
- todo ocurre en UNA transacción: si falla algo o los conteos no coinciden, queda como estaba.

Compatible con respaldos de un esquema anterior: lee las columnas por nombre (las que ya no
existen se ignoran, las nuevas toman su default), carga en orden de claves foráneas, habilita los
GUC de los triggers de protección (`app.*_write`) y renombra los alias repetidos que hoy rompen el
índice único. No incluye `auth.users`: tras restaurar en una instalación nueva, las cuentas
anónimas de los celulares se recrean solas y los admins se crean con `make admin-crear`.
"""

import argparse
import asyncio
import hashlib
import io
import json
import re
import sys
import tempfile
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import asyncpg

from etl.comun import almacen as alm
from etl.comun.catalogo import conectar as _conectar_env

FORMATO = "respaldo_v1"
PREFIJO = "respaldo"
PALABRA = "RESTAURAR"
# Tablas que nunca van al respaldo: PostGIS, archivos subidos al panel (blobs temporales) y la
# bitácora de ejecuciones de ETL (la ejecución en curso es la que está corriendo esto).
EXCLUIDAS = frozenset({"spatial_ref_sys", "etl_archivos", "etl_ejecuciones"})
SOLO_CON_EVENTOS = frozenset({"eventos", "eventos_exportaciones"})
# `config` se fusiona (las claves nuevas vienen de las migraciones); no se vacía.
FUSIONAR = frozenset({"config"})
# Tablas que un trigger llena solo al cargar otra: se vacían antes de cargar su propio contenido.
LLENA_UN_TRIGGER = frozenset({"usuarios_alias_historial"})
GUCS = ("app.rol_write", "app.karma_write", "app.catalogo_write", "app.estado_write")

_SALIDA_NOMBRE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")


class RespaldoError(RuntimeError):
    pass


async def conectar(url: str | None = None) -> asyncpg.Connection:
    if url:
        return await asyncpg.connect(url, server_settings={"timezone": "UTC"})
    return await _conectar_env()


def _q(ident: str) -> str:
    return '"' + ident.replace('"', '""') + '"'


# ------------------------------------------------------------------ esquema


async def _tablas(conn: asyncpg.Connection) -> list[str]:
    filas = await conn.fetch(
        "select tablename from pg_tables where schemaname = 'public' order by 1"
    )
    return [f["tablename"] for f in filas]


async def _columnas(conn: asyncpg.Connection, tabla: str) -> dict[str, str]:
    """nombre -> tipo, sin columnas generadas."""
    filas = await conn.fetch(
        """select a.attname, format_type(a.atttypid, a.atttypmod) as tipo
             from pg_attribute a
            where a.attrelid = ('public.' || quote_ident($1))::regclass
              and a.attnum > 0 and not a.attisdropped and a.attgenerated = ''
            order by a.attnum""",
        tabla,
    )
    return {f["attname"]: f["tipo"] for f in filas}


async def _orden_fk(conn: asyncpg.Connection, tablas: list[str]) -> list[str]:
    """Padres antes que hijos (ignora autorreferencias)."""
    filas = await conn.fetch(
        """select c.conrelid::regclass::text as hijo, c.confrelid::regclass::text as padre
             from pg_constraint c
            where c.contype = 'f' and c.conrelid <> c.confrelid
              and c.connamespace = 'public'::regnamespace"""
    )
    dep: dict[str, set[str]] = {t: set() for t in tablas}
    for f in filas:
        h, p = f["hijo"].replace("public.", ""), f["padre"].replace("public.", "")
        if h in dep and p in dep:
            dep[h].add(p)
    salida: list[str] = []
    while dep:
        listas = sorted(k for k, v in dep.items() if not (v - set(salida)))
        if not listas:
            raise RespaldoError(f"ciclo de claves foráneas entre: {sorted(dep)}")
        salida += listas
        for k in listas:
            del dep[k]
    return salida


async def _migracion(conn: asyncpg.Connection) -> str | None:
    if not await conn.fetchval("select to_regclass('supabase_migrations.schema_migrations')"):
        return None
    return await conn.fetchval("select max(version) from supabase_migrations.schema_migrations")


# ------------------------------------------------------------------ crear


@dataclass
class ResultadoCrear:
    clave: str
    bytes: int
    sha256: str
    almacen: str
    tablas: dict[str, int]
    migracion: str | None

    def texto(self) -> str:
        filas = "\n".join(f"  {t:<28}{n:>9}" for t, n in self.tablas.items())
        return (
            f"Respaldo {self.clave}  ({self.bytes / 1e6:.1f} MB, almacén: {self.almacen}, "
            f"esquema {self.migracion})\nsha256 {self.sha256}\n{filas}"
        )


LEEME = """Respaldo de la base de Almacenero ({generado})

Formato: {formato}. Esquema (última migración): {migracion}.
Contenido: datos/<tabla>.csv por cada tabla de `public` (ver manifest.json: filas y sha256).

PRIVACIDAD: lleva ids y emails de usuarios, alias, dispositivos y auditoría. Es un archivo
PRIVADO: no se sube al repositorio (que es público) ni se comparte.

Restaurar:  make db-restore ARCHIVO=<este .zip> [APLICAR=1 CONFIRMAR=RESTAURAR]
            o el ETL «Restaurar un respaldo» del panel. Primero se corre en simulacro.
No incluye auth.users (las cuentas anónimas se recrean solas; los admins con make admin-crear).
"""


def _nombre(nombre: str) -> str:
    nombre = (nombre or "respaldo").strip()
    if nombre.endswith(".zip"):
        nombre = nombre[:-4]
    if not _SALIDA_NOMBRE.match(nombre) or ".." in nombre:
        raise RespaldoError("el nombre: solo letras, números, punto y guion, sin carpetas")
    return nombre


async def crear(
    url: str | None = None,
    *,
    nombre: str = "respaldo",
    con_eventos: bool = False,
    almacen: alm.Almacen | None = None,
    log=print,
) -> ResultadoCrear:
    almacen = almacen or alm.desde_entorno()
    nombre = _nombre(nombre)
    ahora = datetime.now(timezone.utc)
    conn = await conectar(url)
    try:
        async with conn.transaction(isolation="repeatable_read", readonly=True):  # foto consistente
            todas = await _tablas(conn)
            tablas = [
                t
                for t in todas
                if t not in EXCLUIDAS and (con_eventos or t not in SOLO_CON_EVENTOS)
            ]
            migracion = await _migracion(conn)
            manifest: dict = {
                "formato": FORMATO,
                "generado": ahora.isoformat(),
                "migracion": migracion,
                "con_eventos": con_eventos,
                "tablas": {},
            }
            with tempfile.TemporaryDirectory() as tmp:
                ruta_zip = Path(tmp) / "respaldo.zip"
                with zipfile.ZipFile(ruta_zip, "w", zipfile.ZIP_DEFLATED) as z:
                    for t in tablas:
                        cols = list(await _columnas(conn, t))
                        csv_path = Path(tmp) / f"{t}.csv"
                        sel = ", ".join(_q(c) for c in cols)
                        with open(csv_path, "wb") as f:
                            await conn.copy_from_query(
                                f"select {sel} from public.{_q(t)}",
                                output=f,
                                format="csv",
                                header=True,
                            )
                        h = hashlib.sha256(csv_path.read_bytes()).hexdigest()
                        n = await conn.fetchval(f"select count(*) from public.{_q(t)}")
                        manifest["tablas"][t] = {
                            "filas": n,
                            "columnas": cols,
                            "sha256": h,
                        }
                        z.write(csv_path, f"datos/{t}.csv")
                        csv_path.unlink()
                        log(f"  {t}: {n} filas")
                    z.writestr(
                        "manifest.json",
                        json.dumps(manifest, indent=1, ensure_ascii=False),
                    )
                    z.writestr(
                        "LEEME.txt",
                        LEEME.format(
                            generado=ahora.isoformat(timespec="seconds"),
                            formato=FORMATO,
                            migracion=migracion,
                        ),
                    )
                datos = ruta_zip.read_bytes()
    finally:
        await conn.close()
    clave = f"{PREFIJO}/{nombre}-{ahora:%Y%m%dT%H%M%SZ}.zip"
    await asyncio.to_thread(almacen.asegurar)
    await asyncio.to_thread(alm.verificar, almacen, clave, datos)  # sube, relee y compara
    return ResultadoCrear(
        clave,
        len(datos),
        alm.sha256(datos),
        almacen.nombre,
        {t: m["filas"] for t, m in manifest["tablas"].items()},
        migracion,
    )


def listar(almacen: alm.Almacen | None = None) -> list[alm.Objeto]:
    almacen = almacen or alm.desde_entorno()
    return sorted(almacen.listar(f"{PREFIJO}/"), key=lambda o: o.modificado, reverse=True)


# --------------------------------------------------------------- restaurar


@dataclass
class ResultadoRestaurar:
    aplicado: bool
    migracion_respaldo: str | None
    migracion_actual: str | None
    tablas: dict[str, dict] = field(default_factory=dict)
    avisos: list[str] = field(default_factory=list)
    seguridad: str | None = None

    def texto(self) -> str:
        t = [
            ("RESTAURADO" if self.aplicado else "SIMULACRO (no se escribió nada)")
            + f" · esquema del respaldo {self.migracion_respaldo}, actual {self.migracion_actual}",
            f"  {'tabla':<28}{'en el respaldo':>15}{'ahora':>10}",
        ]
        for n, d in self.tablas.items():
            t.append(f"  {n:<28}{d['respaldo']:>15}{d['ahora']:>10}")
        if self.seguridad:
            t.append(f"Respaldo de seguridad previo: {self.seguridad}")
        t += [f"AVISO: {a}" for a in self.avisos]
        if not self.aplicado:
            t.append("\nPara restaurar de verdad: aplicar + confirmar con la palabra " + PALABRA)
        return "\n".join(t)


def _leer_zip(datos: bytes) -> tuple[zipfile.ZipFile, dict]:
    try:
        z = zipfile.ZipFile(io.BytesIO(datos))
        manifest = json.loads(z.read("manifest.json"))
    except (zipfile.BadZipFile, KeyError, json.JSONDecodeError) as e:
        raise RespaldoError(f"no es un respaldo de Almacenero válido ({e})") from e
    if manifest.get("formato") != FORMATO:
        raise RespaldoError(
            f"formato desconocido: {manifest.get('formato')!r} (se esperaba {FORMATO})"
        )
    return z, manifest


def cargar_bytes(archivo: str, almacen: alm.Almacen | None = None) -> bytes:
    """`archivo` es una ruta local o `almacen:<clave>`."""
    if archivo.startswith("almacen:"):
        return (almacen or alm.desde_entorno()).leer(archivo[len("almacen:") :])
    p = Path(archivo)
    if not p.is_file():
        raise RespaldoError(f"no existe {archivo}")
    return p.read_bytes()


async def restaurar(
    archivo: str,
    url: str | None = None,
    *,
    aplicar: bool = False,
    confirmacion: str = "",
    almacen: alm.Almacen | None = None,
    log=print,
) -> ResultadoRestaurar:
    datos = await asyncio.to_thread(cargar_bytes, archivo, almacen)
    z, manifest = _leer_zip(datos)
    for t, m in manifest["tablas"].items():  # integridad del archivo antes de tocar nada
        if hashlib.sha256(z.read(f"datos/{t}.csv")).hexdigest() != m["sha256"]:
            raise RespaldoError(f"{t}: el contenido no coincide con su sha256 (archivo dañado)")
    if aplicar and confirmacion != PALABRA:
        raise RespaldoError(
            f"para restaurar de verdad hay que escribir {PALABRA} en la confirmación"
        )

    conn = await conectar(url)
    try:
        existentes = set(await _tablas(conn))
        res = ResultadoRestaurar(
            aplicado=False,
            migracion_respaldo=manifest.get("migracion"),
            migracion_actual=await _migracion(conn),
        )
        tablas = [t for t in manifest["tablas"] if t in existentes]
        for t in manifest["tablas"]:
            if t not in existentes:
                res.avisos.append(f"{t}: ya no existe en el esquema actual; se ignora")
        if (
            res.migracion_respaldo
            and res.migracion_actual
            and res.migracion_respaldo > res.migracion_actual
        ):
            raise RespaldoError(
                f"el respaldo es de un esquema MÁS NUEVO ({res.migracion_respaldo}) que esta base "
                f"({res.migracion_actual}): aplicá las migraciones (make migrate) y reintentá"
            )
        for t in tablas:
            ahora = await conn.fetchval(f"select count(*) from public.{_q(t)}")
            res.tablas[t] = {"respaldo": manifest["tablas"][t]["filas"], "ahora": ahora}
            actuales = await _columnas(conn, t)
            for c in manifest["tablas"][t]["columnas"]:
                if c not in actuales:
                    res.avisos.append(f"{t}.{c}: la columna ya no existe; se ignora")
        if not aplicar:
            return res

        # --- de verdad: antes, un respaldo de seguridad (si falla, no se toca nada)
        seg = await crear(
            url,
            nombre="antes-de-restaurar",
            con_eventos=True,
            almacen=almacen,
            log=lambda *_: None,
        )
        res.seguridad = seg.clave
        log(f"Respaldo de seguridad: {seg.clave}")

        orden = await _orden_fk(conn, tablas)
        async with conn.transaction():
            await conn.execute(
                "select " + ", ".join(f"set_config('{g}', 'on', true)" for g in GUCS)
            )
            # lo de afuera del respaldo que apunta a lo que se reemplaza: se desengancha
            externas = await conn.fetch(
                """select c.conrelid::regclass::text as tabla, a.attname, a.attnotnull
                     from pg_constraint c
                     join pg_attribute a on a.attrelid = c.conrelid and a.attnum = c.conkey[1]
                    where c.contype = 'f' and c.connamespace = 'public'::regnamespace
                      and c.confrelid::regclass::text = any($1::text[])
                      and not (c.conrelid::regclass::text = any($1::text[]))
                      and array_length(c.conkey, 1) = 1""",
                [*tablas, *("public." + t for t in tablas)],
            )
            for e in externas:
                tab = e["tabla"]
                if e["attnotnull"]:
                    await conn.execute(f"delete from {tab}")
                else:
                    await conn.execute(f"update {tab} set {_q(e['attname'])} = null")
            referenciadas = {
                f["t"].replace("public.", "")
                for f in await conn.fetch(
                    """select distinct confrelid::regclass::text as t from pg_constraint
                        where contype = 'f' and conrelid <> confrelid
                          and connamespace = 'public'::regnamespace"""
                )
            }
            for t in reversed(orden):
                if t not in FUSIONAR:
                    await _vaciar(conn, t, referenciadas)
            for t in orden:
                await _cargar_tabla(conn, z, t, manifest["tablas"][t], log)
            for t in tablas:
                n = await conn.fetchval(f"select count(*) from public.{_q(t)}")
                if t in FUSIONAR:
                    continue
                if n != manifest["tablas"][t]["filas"]:
                    raise RespaldoError(
                        f"{t}: se cargaron {n} filas y el respaldo tenía {manifest['tablas'][t]['filas']}"
                    )
            for sec in await conn.fetch(
                """select s.relname as seq, c.relname as tabla, a.attname as col
                     from pg_class s join pg_depend d on d.objid = s.oid and d.deptype in ('a','i')
                     join pg_class c on c.oid = d.refobjid
                     join pg_attribute a on a.attrelid = c.oid and a.attnum = d.refobjsubid
                    where s.relkind = 'S' and s.relnamespace = 'public'::regnamespace"""
            ):
                await conn.execute(
                    f"select setval('public.{_q(sec['seq'])}', "
                    f"coalesce((select max({_q(sec['col'])}) from public.{_q(sec['tabla'])}), 1), "
                    f"exists (select 1 from public.{_q(sec['tabla'])}))"
                )
        res.aplicado = True
        for t in tablas:
            res.tablas[t]["ahora"] = await conn.fetchval(f"select count(*) from public.{_q(t)}")
        await conn.execute("analyze")
        return res
    finally:
        await conn.close()


async def _vaciar(conn, t: str, referenciadas: set[str]) -> None:
    """Las tablas que nadie referencia (y las de solo agregar, que bloquean el DELETE) se vacían con
    TRUNCATE; el resto con DELETE (TRUNCATE no puede con una tabla referenciada por otra)."""
    if t in referenciadas:
        await conn.execute(f"delete from public.{_q(t)}")
    else:
        await conn.execute(f"truncate public.{_q(t)}")


async def _cargar_tabla(conn, z: zipfile.ZipFile, t: str, meta: dict, log) -> None:
    actuales = await _columnas(conn, t)
    cols = [c for c in meta["columnas"] if c in actuales]
    if not cols:
        return
    with tempfile.TemporaryDirectory() as tmp:
        ruta = Path(tmp) / f"{t}.csv"
        ruta.write_bytes(z.read(f"datos/{t}.csv"))
        # staging todo-texto: tolera columnas que sobran y las identidades (overriding system value)
        todas = meta["columnas"]
        await conn.execute(
            "create temp table _stg ("
            + ", ".join(f"{_q(c)} text" for c in todas)
            + ") on commit drop"
        )
        await conn.copy_to_table("_stg", source=str(ruta), columns=todas, format="csv", header=True)
    if t == "usuarios" and "alias" in todas and "created_at" in todas:
        # índice único de alias (posterior a respaldos viejos): el más viejo conserva el nombre
        await conn.execute(
            """update _stg s set alias = left(s.alias, 43) || '-' || left(s.id, 6)
                 from (select id, row_number() over (partition by lower(alias)
                                                     order by created_at::timestamptz, id) n
                         from _stg where alias !~* '^anon-') d
                where s.id = d.id and d.n > 1"""
        )
    if t in LLENA_UN_TRIGGER:
        await _vaciar(conn, t, set())
    lista = ", ".join(_q(c) for c in cols)
    casts = ", ".join(f"{_q(c)}::{actuales[c]}" for c in cols)
    if t in FUSIONAR:
        claves = [c for c in ("clave", "rubro") if c in cols]
        sets = ", ".join(f"{_q(c)} = excluded.{_q(c)}" for c in cols if c not in claves)
        await conn.execute(
            f"insert into public.{_q(t)} ({lista}) overriding system value select {casts} from _stg "
            f"on conflict (clave, coalesce(rubro, '')) do update set {sets}"
        )
    else:
        await conn.execute(
            f"insert into public.{_q(t)} ({lista}) overriding system value select {casts} from _stg"
        )
    await conn.execute("drop table _stg")
    log(f"  {t}: cargadas")


# -------------------------------------------------------------------- CLI


def _main() -> int:
    ap = argparse.ArgumentParser(prog="python -m etl.respaldo")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("crear", help="respalda la base al almacén de exportaciones")
    c.add_argument("--nombre", default="respaldo")
    c.add_argument("--con-eventos", action="store_true")
    sub.add_parser("listar", help="lista los respaldos del almacén")
    r = sub.add_parser("restaurar", help="simulacro por defecto; --aplicar --confirmar RESTAURAR")
    r.add_argument("archivo", help="ruta a un .zip o almacen:<clave>")
    r.add_argument("--aplicar", action="store_true")
    r.add_argument("--confirmar", default="")
    a = ap.parse_args()
    try:
        if a.cmd == "crear":
            print(asyncio.run(crear(nombre=a.nombre, con_eventos=a.con_eventos)).texto())
        elif a.cmd == "listar":
            for o in listar():
                print(f"{o.modificado:%Y-%m-%d %H:%M}  {o.tamano / 1e6:8.1f} MB  almacen:{o.clave}")
        else:
            print(
                asyncio.run(
                    restaurar(a.archivo, aplicar=a.aplicar, confirmacion=a.confirmar)
                ).texto()
            )
    except (RespaldoError, alm.AlmacenError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(_main())
