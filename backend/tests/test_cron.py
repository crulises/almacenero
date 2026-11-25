"""Expresiones cron en UTC (services/cron.py)."""

from datetime import datetime, timezone

import pytest

from app.services import cron

U = timezone.utc


def _t(*a):
    return datetime(*a, tzinfo=U)


@pytest.mark.parametrize(
    ("texto", "desde", "esperado"),
    [
        ("0 6 * * *", _t(2026, 11, 24, 5, 59, 30), _t(2026, 11, 24, 6, 0)),
        ("0 6 * * *", _t(2026, 11, 24, 6, 0), _t(2026, 11, 25, 6, 0)),  # siempre posterior
        ("*/15 * * * *", _t(2026, 11, 24, 10, 7), _t(2026, 11, 24, 10, 15)),
        ("30 2 1 * *", _t(2026, 11, 24, 0, 0), _t(2026, 12, 1, 2, 30)),
        ("0 0 * * 0", _t(2026, 11, 24, 0, 0), _t(2026, 11, 29, 0, 0)),  # domingo
        ("0 0 * * 7", _t(2026, 11, 24, 0, 0), _t(2026, 11, 29, 0, 0)),  # 7 también es domingo
        ("0 9 * * 1-5", _t(2026, 11, 28, 12, 0), _t(2026, 11, 30, 9, 0)),  # sábado -> lunes
        ("0 12 1,15 * *", _t(2026, 11, 2, 0, 0), _t(2026, 11, 15, 12, 0)),
        ("0 12 29 2 *", _t(2026, 11, 24, 0, 0), _t(2028, 2, 29, 12, 0)),  # próximo bisiesto
        # día del mes Y de la semana restringidos: cuadra uno u otro (como el cron clásico)
        ("0 0 13 * 5", _t(2026, 11, 1, 0, 0), _t(2026, 11, 6, 0, 0)),
    ],
)
def test_proxima(texto, desde, esperado):
    assert cron.proxima(texto, desde) == esperado


def test_la_hora_es_utc_aunque_llegue_en_otra_zona():
    from datetime import timedelta

    arg = timezone(timedelta(hours=-3))
    # 02:00 en Buenos Aires = 05:00 UTC -> el próximo 06:00 UTC es el mismo día
    assert cron.proxima("0 6 * * *", datetime(2026, 11, 24, 2, 0, tzinfo=arg)) == _t(
        2026, 11, 24, 6, 0
    )


@pytest.mark.parametrize(
    "texto",
    ["", "* * * *", "* * * * * *", "60 * * * *", "* 24 * * *", "* * 0 * *", "* * * 13 *",
     "a * * * *", "*/0 * * * *", "5-1 * * * *", "@daily", "mon * * * *"],
)  # fmt: skip
def test_invalidos(texto):
    with pytest.raises(cron.CronInvalido):
        cron.parsear(texto)


def test_un_cron_imposible_no_cuelga():
    with pytest.raises(cron.CronInvalido):
        cron.proxima("0 0 31 2 *", _t(2026, 1, 1, 0, 0))
