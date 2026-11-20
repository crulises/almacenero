"""Armado de listados con filtros opcionales y paginación, con parámetros posicionales."""

from typing import Any


class Consulta:
    """Acumula condiciones `where` con sus parámetros ($1, $2, ...)."""

    def __init__(self) -> None:
        self.args: list[Any] = []
        self.condiciones: list[str] = []

    def param(self, valor: Any) -> str:
        self.args.append(valor)
        return f"${len(self.args)}"

    def donde(self, plantilla: str, valor: Any) -> None:
        """`plantilla` lleva `{}` donde va el parámetro."""
        self.condiciones.append(plantilla.format(self.param(valor)))

    @property
    def where(self) -> str:
        return ("where " + " and ".join(self.condiciones)) if self.condiciones else ""


def escapar_like(texto: str) -> str:
    return texto.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
