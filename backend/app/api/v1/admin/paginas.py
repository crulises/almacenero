"""Modelo de página compartido por los listados (evita import circular con __init__)."""

from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class Pagina(BaseModel, Generic[T]):
    total: int
    items: list[T]
