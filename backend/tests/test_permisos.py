from types import SimpleNamespace

from app.services.permisos import puede


def test_un_usuario_comun_no_verifica_locales_ni_los_crea_directo():
    u = SimpleNamespace(rol="usuario")
    assert puede(u, "precio.cargar")
    assert puede(u, "local.proponer")
    assert not puede(u, "local.crear")
    assert not puede(u, "local.verificar")


def test_un_admin_puede_todo_lo_conocido():
    a = SimpleNamespace(rol="admin")
    for cap in ("precio.cargar", "local.proponer", "local.crear", "local.verificar"):
        assert puede(a, cap)


def test_rol_o_capacidad_desconocidos_no_dan_permiso():
    assert not puede(SimpleNamespace(rol="inventado"), "precio.cargar")
    assert not puede(SimpleNamespace(rol="admin"), "capacidad.inventada")
