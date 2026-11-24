"""Registro de ETL: cada uno se define con la **descripción de sus parámetros** (docs/04 §10-A).

El panel pide la lista (`GET /v1/admin/etl`) y dibuja el formulario a partir de ella; el backend
valida lo que llega contra la misma definición (`validar`). Agregar un ETL es agregar una
`Definicion` en `etl/definiciones.py`: ni el panel ni la API cambian.

Tipos de parámetro: `texto`, `entero`, `booleano`, `opcion` (una de `opciones`), `fecha`
(AAAA-MM-DD) y `archivo` (se sube por el panel y llega al ETL como una ruta temporal).
"""

import datetime
import importlib
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

TIPOS = ("texto", "entero", "booleano", "opcion", "fecha", "archivo", "nombre_archivo")
MAX_TEXTO = 500


@dataclass(frozen=True)
class Param:
    nombre: str
    tipo: str
    obligatorio: bool = False
    ayuda: str = ""
    default: Any = None
    opciones: tuple[str, ...] = ()


@dataclass(frozen=True)
class Definicion:
    clave: str
    titulo: str
    descripcion: str
    ejecutor: str  # `web`: subproceso del backend (liviano). `local`: worker del dueño (pesado).
    parametros: tuple[Param, ...]
    ejecutar: Callable  # async (parametros: dict, ctx) -> dict | None  (el reporte)
    # Parámetro booleano que, si vale true, consume (borra) el archivo subido al terminar.
    # None: el archivo se borra siempre al terminar. Así «validar en seco» no lo pierde.
    consume_archivo_con: str | None = None
    extra: dict = field(default_factory=dict)


class ParametroInvalido(ValueError):
    def __init__(self, nombre: str, mensaje: str):
        super().__init__(f"{nombre}: {mensaje}")
        self.nombre = nombre
        self.mensaje = mensaje


def _convertir(p: Param, v: Any) -> Any:
    if p.tipo == "entero":
        if isinstance(v, bool) or not (
            isinstance(v, int) or (isinstance(v, str) and v.strip().lstrip("-").isdigit())
        ):
            raise ParametroInvalido(p.nombre, "tiene que ser un número entero")
        return int(v)
    if p.tipo == "booleano":
        if isinstance(v, bool):
            return v
        if isinstance(v, str) and v.lower() in ("true", "false"):
            return v.lower() == "true"
        raise ParametroInvalido(p.nombre, "tiene que ser sí o no")
    if p.tipo == "opcion":
        if v not in p.opciones:
            raise ParametroInvalido(p.nombre, f"tiene que ser una de: {', '.join(p.opciones)}")
        return v
    if p.tipo == "fecha":
        try:
            return datetime.date.fromisoformat(str(v)).isoformat()
        except ValueError:
            raise ParametroInvalido(p.nombre, "tiene que ser una fecha AAAA-MM-DD") from None
    if p.tipo == "nombre_archivo":
        from etl.comun.rutas import NombreInvalido, validar_nombre

        try:
            return validar_nombre(str(v))
        except NombreInvalido as e:
            raise ParametroInvalido(p.nombre, str(e)) from None
    # texto y archivo (el id del archivo subido, que la API resuelve y comprueba)
    if not isinstance(v, str):
        raise ParametroInvalido(p.nombre, "tiene que ser un texto")
    v = v.strip()
    if len(v) > MAX_TEXTO:
        raise ParametroInvalido(p.nombre, f"es demasiado largo (máximo {MAX_TEXTO} caracteres)")
    return v


def validar(defn: Definicion, payload: dict[str, Any]) -> dict[str, Any]:
    """Valida el formulario contra la definición. -> parámetros con tipos y defaults aplicados."""
    conocidos = {p.nombre for p in defn.parametros}
    for nombre in payload:
        if nombre not in conocidos:
            raise ParametroInvalido(nombre, f"{defn.clave} no tiene ese parámetro")
    salida: dict[str, Any] = {}
    for p in defn.parametros:
        v = payload.get(p.nombre)
        if v is None or v == "":
            if p.obligatorio:
                raise ParametroInvalido(p.nombre, "es obligatorio")
            v = p.default
            if v is None:
                continue
        salida[p.nombre] = _convertir(p, v)
    return salida


def describir(defn: Definicion) -> dict[str, Any]:
    """Lo que ve el panel: la definición sin el código."""
    return {
        "clave": defn.clave,
        "titulo": defn.titulo,
        "descripcion": defn.descripcion,
        "ejecutor": defn.ejecutor,
        "consume_archivo_con": defn.consume_archivo_con,
        "parametros": [
            {
                "nombre": p.nombre,
                "tipo": p.tipo,
                "obligatorio": p.obligatorio,
                "ayuda": p.ayuda,
                "default": p.default,
                "opciones": list(p.opciones),
            }
            for p in defn.parametros
        ],
    }


def _definiciones() -> dict[str, Definicion]:
    """Las del repo, más las de un módulo extra si `ETL_DEFINICIONES_EXTRA` lo nombra (los tests
    lo usan para probar el ejecutor con ETL de mentira; los subprocesos lo heredan)."""
    from etl.definiciones import DEFINICIONES

    extra = os.environ.get("ETL_DEFINICIONES_EXTRA")
    if not extra:
        return DEFINICIONES
    return {**DEFINICIONES, **importlib.import_module(extra).DEFINICIONES}


def todas() -> list[Definicion]:
    return list(_definiciones().values())


def obtener(clave: str) -> Definicion | None:
    return _definiciones().get(clave)
