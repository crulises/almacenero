"""Almacén de exportaciones (docs/04 §11.4): dónde queda un archivo que el sistema exporta solo.

Una interfaz mínima —guardar, leer, listar, borrar— con dos implementaciones: **S3** (cualquier
almacenamiento S3-compatible: el Storage de Supabase, SeaweedFS, MinIO, R2...) y **disco** (el worker local y
los tests). Mudarse de un S3 a otro es cambiar variables de entorno, no código:

    EXPORT_S3_ENDPOINT   URL de la API S3 (p. ej. http://127.0.0.1:54321/storage/v1/s3)
    EXPORT_S3_BUCKET     nombre del bucket (se crea solo si no existe y el servicio lo permite)
    EXPORT_S3_KEY / EXPORT_S3_SECRET   credenciales S3
    EXPORT_S3_REGION     opcional (por defecto «us-east-1»)

Sin esas variables se usa el disco (`ETL_EXPORT_DIR`). El código que escribe (`eventos_exportar`)
no sabe cuál es: siempre sube, **vuelve a leer** y compara tamaño y sha256 antes de dar algo por
guardado (`verificar`), así que un almacén nuevo se prueba con `probar()` antes de depender de él.

Es sincrónico a propósito (boto3 lo es): el backend lo llama con `asyncio.to_thread`.
"""

import hashlib
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol


class AlmacenError(RuntimeError):
    """El almacén no pudo guardar, leer o verificar un archivo."""


@dataclass(frozen=True)
class Objeto:
    clave: str
    tamano: int
    modificado: datetime


class Almacen(Protocol):
    nombre: str  # «s3» | «disco»: se anota en `eventos_exportaciones`

    def asegurar(self) -> None: ...
    def guardar(self, clave: str, datos: bytes) -> None: ...
    def leer(self, clave: str) -> bytes: ...
    def listar(self, prefijo: str = "") -> list[Objeto]: ...
    def borrar(self, clave: str) -> None: ...


def _clave_valida(clave: str) -> str:
    """Una clave es una ruta relativa con `/`: sin `..`, sin barra inicial ni caracteres raros."""
    partes = clave.split("/")
    if not clave or clave.startswith("/") or any(p in ("", ".", "..") for p in partes):
        raise AlmacenError(f"clave inválida: {clave!r}")
    if any(not all(c.isascii() and (c.isalnum() or c in "._-") for c in p) for p in partes):
        raise AlmacenError(f"clave inválida (solo letras, números, . _ - y /): {clave!r}")
    return clave


class AlmacenDisco:
    nombre = "disco"

    def __init__(self, carpeta: Path):
        self.carpeta = Path(carpeta)

    def _ruta(self, clave: str) -> Path:
        return self.carpeta / _clave_valida(clave)

    def asegurar(self) -> None:
        self.carpeta.mkdir(parents=True, exist_ok=True)

    def guardar(self, clave: str, datos: bytes) -> None:
        ruta = self._ruta(clave)
        ruta.parent.mkdir(parents=True, exist_ok=True)
        tmp = ruta.with_name(ruta.name + ".tmp")
        tmp.write_bytes(datos)
        tmp.replace(ruta)  # nunca queda un archivo a medio escribir con el nombre final

    def leer(self, clave: str) -> bytes:
        try:
            return self._ruta(clave).read_bytes()
        except FileNotFoundError:
            raise AlmacenError(f"no existe {clave}") from None

    def listar(self, prefijo: str = "") -> list[Objeto]:
        if not self.carpeta.exists():
            return []
        salida = []
        for p in sorted(self.carpeta.rglob("*")):
            if not p.is_file() or p.name.endswith(".tmp"):
                continue
            clave = p.relative_to(self.carpeta).as_posix()
            if clave.startswith(prefijo):
                st = p.stat()
                salida.append(
                    Objeto(clave, st.st_size, datetime.fromtimestamp(st.st_mtime, timezone.utc))
                )
        return salida

    def borrar(self, clave: str) -> None:
        self._ruta(clave).unlink(missing_ok=True)


class AlmacenS3:
    nombre = "s3"

    def __init__(self, endpoint: str, bucket: str, key: str, secret: str, region: str):
        import boto3
        from botocore.config import Config

        self.bucket = bucket
        self._s3 = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=key,
            aws_secret_access_key=secret,
            region_name=region,
            # path-style: funciona igual con Supabase, SeaweedFS y la mayoría de los S3-compatibles
            config=Config(s3={"addressing_style": "path"}, retries={"max_attempts": 3}),
        )

    def asegurar(self) -> None:
        """Crea el bucket si no existe (en local y en el S3 alternativo). Si el servicio no deja crearlo,
        el bucket se crea a mano y esto solo verifica que se pueda leer."""
        from botocore.exceptions import ClientError

        try:
            self._s3.head_bucket(Bucket=self.bucket)
            return
        except ClientError as e:
            codigo = str(e.response.get("Error", {}).get("Code", ""))
            if codigo not in ("404", "NoSuchBucket", "NotFound"):
                raise AlmacenError(f"no se puede acceder al bucket «{self.bucket}»: {e}") from e
        try:
            self._s3.create_bucket(Bucket=self.bucket)
        except ClientError as e:
            raise AlmacenError(
                f"el bucket «{self.bucket}» no existe y no se pudo crear ({e}): "
                "crealo a mano en el servicio de almacenamiento"
            ) from e

    def guardar(self, clave: str, datos: bytes) -> None:
        self._s3.put_object(Bucket=self.bucket, Key=_clave_valida(clave), Body=datos)

    def leer(self, clave: str) -> bytes:
        from botocore.exceptions import ClientError

        try:
            return self._s3.get_object(Bucket=self.bucket, Key=_clave_valida(clave))["Body"].read()
        except ClientError as e:
            raise AlmacenError(f"no se pudo leer {clave}: {e}") from e

    def listar(self, prefijo: str = "") -> list[Objeto]:
        salida: list[Objeto] = []
        token = None
        while True:
            args = {"Bucket": self.bucket, "Prefix": prefijo}
            if token:
                args["ContinuationToken"] = token
            r = self._s3.list_objects_v2(**args)
            salida += [
                Objeto(o["Key"], o["Size"], o["LastModified"]) for o in r.get("Contents", [])
            ]
            if not r.get("IsTruncated"):
                return salida
            token = r["NextContinuationToken"]

    def borrar(self, clave: str) -> None:
        self._s3.delete_object(Bucket=self.bucket, Key=_clave_valida(clave))


def desde_entorno(env: dict[str, str] | None = None) -> Almacen:
    """S3 si están las variables `EXPORT_S3_*`; si no, el disco (`ETL_EXPORT_DIR`)."""
    env = os.environ if env is None else env
    endpoint = (env.get("EXPORT_S3_ENDPOINT") or "").strip()
    if not endpoint:
        from etl.comun.rutas import dir_exports

        return AlmacenDisco(dir_exports())
    faltan = [
        v for v in ("EXPORT_S3_BUCKET", "EXPORT_S3_KEY", "EXPORT_S3_SECRET") if not env.get(v)
    ]
    if faltan:
        raise AlmacenError(f"EXPORT_S3_ENDPOINT está definido pero faltan: {', '.join(faltan)}")
    return AlmacenS3(
        endpoint,
        env["EXPORT_S3_BUCKET"],
        env["EXPORT_S3_KEY"],
        env["EXPORT_S3_SECRET"],
        env.get("EXPORT_S3_REGION") or "us-east-1",
    )


def sha256(datos: bytes) -> str:
    return hashlib.sha256(datos).hexdigest()


def verificar(almacen: Almacen, clave: str, datos: bytes) -> None:
    """Guarda `datos`, los **vuelve a leer** y compara tamaño y sha256. Si algo no coincide, lanza
    `AlmacenError`: quien llama NO debe dar por guardado lo exportado (ni borrar el original)."""
    almacen.guardar(clave, datos)
    leido = almacen.leer(clave)
    if len(leido) != len(datos):
        raise AlmacenError(f"{clave}: se guardaron {len(datos)} bytes y al releer hay {len(leido)}")
    if sha256(leido) != sha256(datos):
        raise AlmacenError(f"{clave}: el contenido al releer no coincide (sha256 distinto)")


def probar(almacen: Almacen) -> dict:
    """Ida y vuelta con un archivo de prueba (`make almacen-probar` y el botón del panel): se corre
    al configurar un almacén nuevo y antes de activar una programación. Deja el almacén como
    estaba. Lanza `AlmacenError` si algo falla."""
    almacen.asegurar()
    clave = f"_prueba/prueba-{uuid.uuid4().hex}.txt"
    datos = f"almacenero · prueba del almacén · {uuid.uuid4()}\n".encode()
    verificar(almacen, clave, datos)
    almacen.borrar(clave)
    if any(o.clave == clave for o in almacen.listar("_prueba/")):
        raise AlmacenError(f"{clave}: el archivo de prueba no se pudo borrar")
    return {"almacen": almacen.nombre, "bytes": len(datos), "sha256": sha256(datos)}
