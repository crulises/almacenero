"""Eventos de producto (docs/04 §11.2): registro de tipos y guardado.

Cada tipo declara qué `datos` acepta (esquema Pydantic), si lo puede mandar la app o solo el
backend (`desde_app`) y si cuenta como «actividad» del usuario (hoy ninguno: la definición de
«usuario activo» del dashboard no cambia, docs/04 §11.1). Agregar un tipo = una entrada en
`TIPOS`, sin migración.

Privacidad: el evento lleva el id del usuario y nada más personal. Nada de ubicación ni texto
libre; los esquemas rechazan campos de más (`extra="forbid"`) y los tipos nuevos se revisan con
ese criterio antes de entrar al registro.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

import asyncpg
from pydantic import BaseModel, ConfigDict, Field

MAX_POR_LOTE = 50


class DatosVacios(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DatosEscaneo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ean: str = Field(pattern=r"^\d{8,14}$")
    encontrado: bool
    # Cómo se llegó al código: con la cámara o tipeándolo. Opcional por las apps ya instaladas.
    via: Literal["camara", "manual"] | None = None


class DatosAppAbierta(BaseModel):
    """Qué celular y en qué condiciones abrió la app (docs/04 §11.2). Todo opcional: si el
    celular no pudo leer algo, llega el resto. Sin nada que identifique a la persona: ni red por
    nombre (SSID), ni ubicación, ni batería, ni identificadores del aparato."""

    model_config = ConfigDict(extra="forbid")
    app_version: str | None = Field(default=None, max_length=40)
    android: str | None = Field(default=None, max_length=20)  # «14»
    sdk: int | None = Field(default=None, ge=1, le=100)
    marca: str | None = Field(default=None, max_length=40)
    modelo: str | None = Field(default=None, max_length=60)
    idioma: str | None = Field(default=None, max_length=20)  # «es-AR»
    red: Literal["wifi", "movil", "ethernet", "otra", "ninguna"] | None = None


@dataclass(frozen=True)
class TipoEvento:
    datos: type[BaseModel]
    desde_app: bool = True
    cuenta_como_actividad: bool = False
    # (entidad, entidad_ref) para agrupar sin abrir el json.
    entidad: Callable[[BaseModel], tuple[str | None, str | None]] = lambda d: (None, None)


TIPOS: dict[str, TipoEvento] = {
    "producto.escaneado": TipoEvento(
        DatosEscaneo,
        entidad=lambda d: ("producto", d.ean),  # type: ignore[attr-defined]
    ),
    "app.abierta": TipoEvento(DatosAppAbierta),
}


def tipo_aceptado(tipo: str) -> TipoEvento | None:
    """El tipo registrado que la app puede mandar, o None (desconocido o solo del backend)."""
    t = TIPOS.get(tipo)
    return t if t is not None and t.desde_app else None


@dataclass(frozen=True)
class EventoListo:
    tipo: str
    entidad: str | None
    entidad_ref: str | None
    datos: dict


def preparar(tipo: TipoEvento, nombre: str, datos: dict, cliente: datetime | None) -> EventoListo:
    """Valida `datos` con el esquema del tipo (puede levantar ValidationError)."""
    validos = tipo.datos.model_validate(datos)
    entidad, ref = tipo.entidad(validos)
    final = validos.model_dump(mode="json", exclude_none=True)
    if cliente is not None:
        # El reloj del celular miente: se guarda aparte y nunca se usa para agrupar.
        final["ocurrio_en_cliente"] = cliente.isoformat()
    return EventoListo(nombre, entidad, ref, final)


async def guardar(conn: asyncpg.Connection, usuario_id, lote: list[EventoListo]) -> int:
    import json

    await conn.executemany(
        "insert into eventos (tipo, usuario_id, entidad, entidad_ref, datos) "
        "values ($1, $2, $3, $4, $5::jsonb)",
        [(e.tipo, usuario_id, e.entidad, e.entidad_ref, json.dumps(e.datos)) for e in lote],
    )
    return len(lote)
