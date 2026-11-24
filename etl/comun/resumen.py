"""Resumen legible de lo que hizo el normalizador sobre un conjunto de productos: qué reglas se
aplicaron, a cuántos y con qué ejemplo, y por qué los productos bajan de puntaje. Lo usan
`make catalogo-calidad` y `make catalogo-renormalizar` (y por lo tanto el log del panel)."""

from collections import Counter

from etl.comun.normalizar import Salida
from etl.comun.reglas_texto import MOTIVOS, TRANSFORMACIONES, base

EJEMPLOS_POR_REGLA = 2


def _pct(n: int, total: int) -> str:
    return f"{100 * n / max(total, 1):.1f}".replace(".", ",") + " %"


class Trazas:
    """Acumula las transformaciones que registra `Salida.transformaciones`."""

    def __init__(self) -> None:
        self.afectados = 0
        self.por_regla: Counter = Counter()
        self.detalle: dict[str, Counter] = {}
        self.ejemplos: dict[str, list[tuple[str, str]]] = {}

    def agregar(self, salida: Salida, antes: str, despues: str) -> None:
        if not salida.transformaciones:
            return
        self.afectados += 1
        for t in salida.transformaciones:
            regla = base(t)
            self.por_regla[regla] += 1
            if ":" in t:
                self.detalle.setdefault(regla, Counter())[t.split(":", 1)[1]] += 1
            lista = self.ejemplos.setdefault(regla, [])
            if len(lista) < EJEMPLOS_POR_REGLA and antes != despues:
                lista.append((antes, despues))

    def texto(self, total: int) -> str:
        """`total`: cuántos productos se miraron (para el porcentaje)."""
        if not self.afectados:
            return (
                "Transformaciones: ninguna. Con estas reglas el catálogo ya está normalizado: "
                "no hay nada que cambiar."
            )
        lineas = [f"Transformaciones aplicadas ({self.afectados} productos afectados de {total}):"]
        for regla, (titulo, *_) in TRANSFORMACIONES.items():
            n = self.por_regla.get(regla)
            if not n:
                continue
            lineas.append(f"  {titulo}: {n} productos ({_pct(n, total)})")
            if regla in self.detalle:
                top = ", ".join(f"{k} ({v})" for k, v in self.detalle[regla].most_common(8))
                lineas.append(f"      abreviaturas más usadas: {top}")
            for antes, despues in self.ejemplos.get(regla, []):
                lineas.append(f"      ej.: {antes!r} → {despues!r}")
        return "\n".join(lineas)


def explicar_motivos(motivos: Counter | dict, total: int) -> str:
    """Los motivos de puntaje, de más a menos frecuente, con qué significa cada uno."""
    lineas = []
    for m, n in sorted(motivos.items(), key=lambda kv: -kv[1]):
        lineas.append(f"  {m}: {n} ({_pct(n, total)}) — {MOTIVOS.get(m, 'sin descripción')}")
    return "\n".join(lineas)
