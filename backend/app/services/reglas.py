"""Reglas de negocio e integridad con un mensaje que se entiende (docs/04 §10-E).

Cuando algo no se puede aplicar, la respuesta tiene que decir **qué regla se violó y qué
hacer**, no «error». Cada regla tiene un código estable, un título, un mensaje y una guía
para resolverlo. El **mensaje es configurable desde el panel** (Configuración → Mensajes de
error; se guarda en `config.mensajes_reglas`); el código y la regla en sí no cambian.

El payload de error es `detail = {codigo, mensaje, titulo, como_resolver}`: la app y el panel
lo muestran tal cual. Para agregar una regla: una entrada en `REGLAS` y, si la dispara la
base, su nombre de constraint en `POR_CONSTRAINT`.
"""

import json
import re
from dataclasses import dataclass

import asyncpg
import pydantic_core


@dataclass(frozen=True)
class Regla:
    codigo: str
    titulo: str
    mensaje: str  # por defecto; editable en el panel
    como_resolver: str
    status: int = 422


REGLAS: dict[str, Regla] = {
    r.codigo: r
    for r in [
        Regla(
            "pack_minimo",
            "Pack de 2 o más",
            "El pack tiene que ser de 2 unidades o más: «pack de 1» es igual a una unidad suelta.",
            "Dejá el pack vacío si es una sola unidad, o poné la cantidad real (2 o más).",
        ),
        Regla(
            "tamano_positivo",
            "Tamaño mayor a cero",
            "El tamaño tiene que ser un número mayor a cero.",
            "Corregí el tamaño o dejalo vacío (junto con la unidad).",
        ),
        Regla(
            "tamano_con_unidad",
            "Tamaño y unidad juntos",
            "El tamaño y la unidad van juntos: o están los dos o no está ninguno.",
            "Completá el que falta, o vaciá los dos.",
        ),
        Regla(
            "unidad_invalida",
            "Unidades permitidas",
            "La unidad tiene que ser g, kg, ml, l o u.",
            "Elegí una de esas unidades; si el producto está en otra, convertila.",
        ),
        Regla(
            "ean_formato",
            "EAN de 8 a 14 dígitos",
            "El EAN tiene que ser un número de 8 a 14 dígitos, sin espacios ni letras.",
            "Revisá el código de barras.",
        ),
        Regla(
            "ean_duplicado",
            "EAN único",
            "Ya existe un producto con ese EAN.",
            "Corregí el producto existente en vez de darlo de alta de nuevo.",
            409,
        ),
        Regla(
            "campo_bloqueado",
            "Campo bloqueado contra el ETL",
            "Ese campo está bloqueado: lo corrigió una persona y el ETL no lo pisa.",
            "Desbloquealo desde la ficha del producto si querés que un proceso lo vuelva a tocar.",
            409,
        ),
        Regla(
            "sugerencia_pendiente",
            "Una sugerencia pendiente por producto",
            "Ya tenés una sugerencia pendiente para ese producto.",
            "Esperá a que la revisen, o mandá una nueva (reemplaza a la anterior).",
            409,
        ),
        Regla(
            "sugerencia_incoherente",
            "Sugerencia bien formada",
            "La sugerencia no se puede registrar así: le falta algo que la base exige "
            "(un rechazo necesita nota, y un cambio no puede estar vacío).",
            "Completá la nota o el cambio y reintentá.",
        ),
        Regla(
            "dato_invalido",
            "Dato que la base no admite",
            "Algún dato no cumple una regla de integridad de la base de datos.",
            "Revisá los datos enviados; si no ves cuál es, avisá con el código de la regla.",
        ),
        Regla(
            "conflicto_de_datos",
            "Dato repetido",
            "Ese dato ya existe y tiene que ser único.",
            "Usá el existente o cambiá el valor.",
            409,
        ),
        Regla(
            "etl_parametro_invalido",
            "Parámetro del ETL inválido",
            "Uno de los parámetros del formulario no cumple lo que pide ese ETL.",
            "Corregí el campo indicado: la ayuda del formulario dice qué espera.",
        ),
        Regla(
            "etl_archivo_vacio",
            "Archivo vacío",
            "El archivo que subiste está vacío.",
            "Elegí un archivo con contenido.",
        ),
        Regla(
            "etl_archivo_grande",
            "Archivo demasiado grande",
            "El archivo supera el máximo de 25 MB que acepta el panel.",
            "Comprimilo (.csv.gz) o partilo; los archivos pesados se cargan con el worker local.",
            413,
        ),
        Regla(
            "etl_archivo_inexistente",
            "El archivo ya no está",
            "Ese archivo ya no existe: se borra al importar de verdad o a las 24 h.",
            "Subilo de nuevo.",
        ),
        Regla(
            "etl_ya_terminada",
            "La ejecución ya terminó",
            "Esa ejecución ya terminó, no se puede cancelar.",
            "Si hace falta, lanzá otra.",
            409,
        ),
        Regla(
            "evento_tipo_desconocido",
            "Tipo de evento conocido",
            "Ese tipo de evento no existe o la app no lo puede mandar.",
            "Mandá solo tipos del registro (producto.escaneado, app.abierta); los demás los "
            "registra el backend o todavía no existen.",
            400,
        ),
        Regla(
            "evento_datos_invalidos",
            "Datos del evento",
            "Los datos del evento no cumplen lo que pide ese tipo: faltan campos, hay campos "
            "de más (no se aceptan ubicación ni texto libre) o un valor tiene mal formato.",
            "Corregí el campo indicado según el tipo de evento; se descartó todo el lote.",
        ),
        Regla(
            "zona_invalida",
            "Zona horaria conocida",
            "Esa zona horaria no existe: tiene que ser un nombre de la base de zonas (IANA), "
            "como America/Buenos_Aires.",
            "Usá un nombre con el formato Continente/Ciudad (America/Buenos_Aires, UTC, "
            "Europe/Madrid); no valen siglas como ART o EST.",
        ),
        Regla(
            "periodo_invalido",
            "Período del dashboard",
            "El período no sirve: «desde» tiene que ser anterior a «hasta» y no puede dar más de "
            "1000 barras en el gráfico.",
            "Elegí un rango más corto o una granularidad más gruesa (por ejemplo día en vez de "
            "hora).",
        ),
        Regla(
            "cron_invalido",
            "Expresión cron válida",
            "La programación no es una expresión cron válida de 5 campos (minuto hora día mes "
            "día-de-la-semana), en hora UTC.",
            "Ejemplo: «0 6 * * *» es todos los días a las 06:00 UTC (03:00 en Buenos Aires). "
            "Se aceptan *, listas (1,15), rangos (1-5) y pasos (*/15).",
        ),
        Regla(
            "almacen_fallo",
            "Almacén de exportaciones",
            "El almacén de exportaciones no respondió bien: no se pudo guardar, releer o comparar "
            "el archivo de prueba.",
            "Revisá las variables EXPORT_S3_* (o ETL_EXPORT_DIR) y que el servicio esté arriba; "
            "corré «make almacen-probar» para ver el detalle. Mientras falle, los eventos no se "
            "tocan.",
            502,
        ),
        Regla(
            "exportacion_inexistente",
            "Exportación inexistente",
            "Esa exportación no existe o su archivo ya no está en el almacén.",
            "Recargá la lista; si el archivo se borró del almacén a mano, queda solo el registro.",
            404,
        ),
        Regla(
            "programacion_inexistente",
            "Programación inexistente",
            "Esa programación no existe.",
            "Recargá la lista de programaciones.",
            404,
        ),
        Regla(
            "alias_no_permitido",
            "Cambiar el alias todavía no está habilitado",
            "Por ahora tu tipo de cuenta no puede cambiar el alias.",
            "Se va a ir abriendo de a poco; mientras tanto seguí usando el que tenés.",
            403,
        ),
        Regla(
            "alias_invalido",
            "Formato del alias",
            "El alias tiene que tener entre 3 y 24 caracteres: letras, números, espacio, punto, "
            "guion o guion bajo, sin símbolos raros y sin empezar ni terminar con un separador.",
            "Probá con otro, por ejemplo «Juan P.» o «lucia_88».",
        ),
        Regla(
            "alias_reservado",
            "Alias reservado",
            "Ese alias está reservado (se parece a un rol o al sistema).",
            "Elegí otro que no empiece con «anon-» ni diga «admin», «moderador», «soporte»…",
        ),
        Regla(
            "alias_bloqueado",
            "Alias no permitido",
            "Ese alias no está permitido.",
            "Elegí otro.",
        ),
        Regla(
            "alias_en_uso",
            "Alias en uso",
            "Ese alias ya lo tiene otra persona (no distinguimos mayúsculas de minúsculas).",
            "Elegí otro; si lo soltó alguien, se libera al cambiarlo.",
            409,
        ),
        Regla(
            "limite_alias",
            "Demasiados cambios de alias",
            "Ya cambiaste el alias muchas veces hoy.",
            "Esperá hasta mañana para cambiarlo de nuevo.",
            429,
        ),
        Regla(
            "error_interno",
            "Error interno",
            "Algo falló del lado del servidor y no pudimos completar la acción.",
            "Reintentá; si se repite, avisá con la referencia (está en los logs del backend).",
            500,
        ),
    ]
}

# Nombre de constraint de la base -> regla. Lo que no figura cae en `dato_invalido`.
POR_CONSTRAINT: dict[str, str] = {
    "productos_canonicos_pack_cantidad_check": "pack_minimo",
    "productos_canonicos_tamano_valor_check": "tamano_positivo",
    "productos_canonicos_check": "tamano_con_unidad",
    "productos_canonicos_tamano_unidad_check": "unidad_invalida",
    "productos_canonicos_ean_check": "ean_formato",
    "sugerencias_catalogo_ean_check": "ean_formato",
    "productos_canonicos_ean_key": "ean_duplicado",
    "sugerencias_pendiente_uidx": "sugerencia_pendiente",
    "sugerencias_catalogo_check1": "sugerencia_incoherente",
    "sugerencias_catalogo_check2": "sugerencia_incoherente",
    "sugerencias_catalogo_cambios_check": "sugerencia_incoherente",
}

CLAVE_CONFIG = "mensajes_reglas"
_TRIGGER_BLOQUEADO = re.compile(r"bloquead[oa]")


def regla_de(exc: BaseException) -> Regla:
    """La regla que explica este error de Postgres."""
    constraint = getattr(exc, "constraint_name", None)
    if constraint in POR_CONSTRAINT:
        return REGLAS[POR_CONSTRAINT[constraint]]
    if isinstance(exc, asyncpg.RaiseError) and _TRIGGER_BLOQUEADO.search(str(exc)):
        return REGLAS["campo_bloqueado"]
    if isinstance(exc, asyncpg.UniqueViolationError):
        return REGLAS["conflicto_de_datos"]
    return REGLAS["dato_invalido"]


async def mensajes(conn: asyncpg.Pool | asyncpg.Connection) -> dict[str, str]:
    """Los mensajes editados desde el panel (código -> texto)."""
    valor = await conn.fetchval(
        "select valor::text from config where clave = $1 and rubro is null", CLAVE_CONFIG
    )
    return json.loads(valor) if valor else {}


def detalle(regla: Regla, editados: dict[str, str], **extra: object) -> dict:
    """El `detail` de la respuesta: código, mensaje (el editado, si lo hay) y cómo resolverlo."""
    return {
        "codigo": regla.codigo,
        "titulo": regla.titulo,
        "mensaje": (editados.get(regla.codigo) or "").strip() or regla.mensaje,
        "como_resolver": regla.como_resolver,
        **extra,
    }


_TEXTO_CAMPO = {
    "greater_than": "tiene que ser mayor a {gt}",
    "greater_than_equal": "tiene que ser {ge} o más",
    "less_than_equal": "tiene que ser {le} o menos",
}


def _problema(e: dict) -> dict:
    ctx = e.get("ctx") or {}
    plantilla = _TEXTO_CAMPO.get(e.get("type", ""))
    texto = plantilla.format(**ctx) if plantilla else e.get("msg", "no es válido")
    return {"campo": ".".join(str(x) for x in e.get("loc", ())), "problema": texto}


def problemas(exc: pydantic_core.ValidationError) -> list[dict]:
    return [_problema(e) for e in exc.errors()]


async def explicar(conn: asyncpg.Pool | asyncpg.Connection, exc: BaseException) -> str:
    """El error como una frase (regla + cómo resolverlo), para listas de fallas en masa."""
    if isinstance(exc, asyncpg.PostgresError):
        regla = regla_de(exc)
    else:
        regla = REGLAS["dato_invalido"]
    d = detalle(regla, await mensajes(conn))
    extra = ""
    if isinstance(exc, pydantic_core.ValidationError):
        extra = " (" + "; ".join(f"{p['campo']} {p['problema']}" for p in problemas(exc)) + ")"
    return f"{d['mensaje']}{extra} {d['como_resolver']}"
