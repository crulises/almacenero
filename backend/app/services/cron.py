"""Expresiones cron de 5 campos, **interpretadas en UTC** (docs/04 §11.4).

`minuto hora día-del-mes mes día-de-la-semana`, con `*`, listas (`1,15`), rangos (`1-5`) y pasos
(`*/15`, `10-30/5`). Día de la semana: 0-6 con 0 = domingo (el 7 también es domingo). Como en el
cron clásico, si el día del mes **y** el de la semana están restringidos, basta que cuadre uno.
Sin nombres (`mon`, `jan`) ni atajos (`@daily`): una sola forma, fácil de explicar.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone


class CronInvalido(ValueError):
    pass


@dataclass(frozen=True)
class Cron:
    minutos: frozenset[int]
    horas: frozenset[int]
    dias: frozenset[int]
    meses: frozenset[int]
    semana: frozenset[int]  # 0 = domingo
    dia_libre: bool  # día del mes sin restringir
    semana_libre: bool


def _campo(texto: str, minimo: int, maximo: int, nombre: str) -> tuple[frozenset[int], bool]:
    valores: set[int] = set()
    libre = texto == "*"
    for trozo in texto.split(","):
        paso = 1
        if "/" in trozo:
            trozo, _, p = trozo.partition("/")
            if not p.isdigit() or int(p) < 1:
                raise CronInvalido(f"{nombre}: el paso «/{p}» no es un número mayor a 0")
            paso = int(p)
        if trozo == "*":
            desde, hasta = minimo, maximo
        elif "-" in trozo:
            a, _, b = trozo.partition("-")
            if not (a.isdigit() and b.isdigit()):
                raise CronInvalido(f"{nombre}: «{trozo}» no es un rango válido")
            desde, hasta = int(a), int(b)
        elif trozo.isdigit():
            desde = int(trozo)
            hasta = maximo if paso > 1 else desde
        else:
            raise CronInvalido(f"{nombre}: «{trozo}» no es un número, rango ni «*»")
        if desde < minimo or hasta > maximo or desde > hasta:
            raise CronInvalido(f"{nombre}: tiene que estar entre {minimo} y {maximo}")
        valores.update(range(desde, hasta + 1, paso))
    return frozenset(valores), libre


def parsear(texto: str) -> Cron:
    campos = (texto or "").split()
    if len(campos) != 5:
        raise CronInvalido("tiene que tener 5 campos: minuto hora día mes día-de-la-semana")
    minutos, _ = _campo(campos[0], 0, 59, "minuto")
    horas, _ = _campo(campos[1], 0, 23, "hora")
    dias, dia_libre = _campo(campos[2], 1, 31, "día del mes")
    meses, _ = _campo(campos[3], 1, 12, "mes")
    semana, semana_libre = _campo(campos[4], 0, 7, "día de la semana")
    return Cron(
        minutos, horas, dias, meses, frozenset(d % 7 for d in semana), dia_libre, semana_libre
    )


def _cuadra_dia(c: Cron, d: date) -> bool:
    if d.month not in c.meses:
        return False
    del_mes = d.day in c.dias
    de_semana = (d.isoweekday() % 7) in c.semana  # isoweekday: lunes 1 .. domingo 7 -> domingo 0
    if c.dia_libre and c.semana_libre:
        return True
    if c.dia_libre:
        return de_semana
    if c.semana_libre:
        return del_mes
    return del_mes or de_semana


def proxima(texto: str | Cron, despues_de: datetime) -> datetime:
    """El primer instante UTC **posterior** a `despues_de` que cuadra con el cron."""
    c = texto if isinstance(texto, Cron) else parsear(texto)
    t = despues_de.astimezone(timezone.utc).replace(second=0, microsecond=0) + timedelta(minutes=1)
    dia = t.date()
    for _ in range(366 * 5):  # un cron imposible (31 de febrero) no cuelga el ciclo
        if _cuadra_dia(c, dia):
            for h in sorted(c.horas):
                for m in sorted(c.minutos):
                    cand = datetime(dia.year, dia.month, dia.day, h, m, tzinfo=timezone.utc)
                    if cand >= t:
                        return cand
        dia += timedelta(days=1)
    raise CronInvalido("esa combinación de día y mes no ocurre nunca")
