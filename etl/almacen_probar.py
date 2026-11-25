"""`make almacen-probar`: ida y vuelta con el almacén configurado (S3 o disco)."""

import sys

from etl.comun import almacen


def main() -> int:
    try:
        alm = almacen.desde_entorno()
        destino = getattr(alm, "bucket", None) or getattr(alm, "carpeta", "")
        print(f"Almacén: {alm.nombre} ({destino})")
        r = almacen.probar(alm)
    except Exception as e:  # noqa: BLE001 - se informa cualquier falla de configuración o de red
        print(f"FALLÓ: {e}")
        print("Los eventos no se tocan mientras el almacén no pase esta prueba.")
        return 1
    print(f"OK: se guardó, se releyó y coincide ({r['bytes']} bytes, sha256 {r['sha256'][:12]}…)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
