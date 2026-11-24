"""Explicación en lenguaje llano de lo que hace el normalizador (Doc 7), para que un reporte de
ETL diga QUÉ transformaciones se aplicaron y POR QUÉ un producto bajó de puntaje, en vez de
mostrar solo totales. Es texto de presentación: la lógica vive en `normalizar.py`.

`TRANSFORMACIONES` va en el orden en que se aplican. El normalizador emite ids; los que llevan
detalle usan `id:detalle` (p. ej. `abreviatura_expandida:p/`); `base()` saca el detalle.
"""

# id -> (título, qué hace, ejemplo)
TRANSFORMACIONES: dict[str, tuple[str, str, str]] = {
    "limpieza_texto": (
        "Limpieza de texto",
        "Saca espacios de más, caracteres de control y puntuación suelta al final.",
        "'Leche  Entera .' → 'Leche Entera'",
    ),
    "codigo_erp": (
        "Código interno al principio",
        "Quita el código de sistema (ceros y número) pegado antes del nombre.",
        "'000123 Leche Entera' → 'Leche Entera'",
    ),
    "sufijo_envase_sepa": (
        "Sufijo de envase de SEPA",
        "Convierte el sufijo tipo BOT-750-ml. en presentación (botella) y tamaño (750 ml).",
        "'Agua Serrana BOT-750-ml.' → 'Agua Serrana' + botella + 750 ml",
    ),
    "tamano_del_nombre": (
        "Tamaño sacado del nombre",
        "Detecta el tamaño escrito en el nombre (500ml, X 30 Grs, 2.25 lt) y lo pasa al campo "
        "tamaño; el nombre queda sin él.",
        "'Aceite 900 cc' → 'Aceite' + 900 ml",
    ),
    "pack_detectado": (
        "Pack detectado",
        "Si el nombre dice «6 x 330 ml», guarda el pack (6) y el tamaño total.",
        "'Gaseosa 6x330ml' → pack 6",
    ),
    "marca_placeholder": (
        "Marca de relleno descartada",
        "«S/d», «sin marca», «genérico», «n/a» no son marcas: se deja el campo vacío.",
        "marca 'S/d' → sin marca",
    ),
    "razon_social_a_fabricante": (
        "Razón social como fabricante",
        "Una razón social (S.A., S.R.L.) no es la marca: se guarda como fabricante y se "
        "busca la marca en el nombre.",
        "marca 'Alimentos Ricos S.A.' → fabricante",
    ),
    "marca_canonica": (
        "Marca unificada",
        "Une las variantes de escritura de una marca a su forma canónica "
        "(diccionario de marcas) o la pasa a «Título».",
        "'LUCCHETTI' / 'lucchetti' → 'Lucchetti'",
    ),
    "marca_desde_nombre": (
        "Marca encontrada en el nombre",
        "La fuente no traía marca, pero el nombre contiene una marca conocida.",
        "'Lavandina Ayudin 1 L' → marca 'Ayudin'",
    ),
    "marca_fuera_del_nombre": (
        "Marca sacada del nombre",
        "El nombre no repite la marca (ya está en su propio campo).",
        "'Aceite Cocinero Girasol' + marca Cocinero → 'Aceite Girasol'",
    ),
    "mayusculas": (
        "Capitalización",
        "Nombres todo en MAYÚSCULAS o minúsculas pasan a «Título» (con de/la/con en minúscula).",
        "'ACEITE DE GIRASOL' → 'Aceite de Girasol'",
    ),
    "envase_a_presentacion": (
        "Envase pasado a presentación",
        "Una palabra de envase en el nombre (botella, sachet, caja) pasa al campo presentación.",
        "'Leche Entera Sachet 1 L' → 'Leche Entera' + sachet",
    ),
    "abreviatura_expandida": (
        "Abreviaturas expandidas",
        "Expande abreviaturas inequívocas (diccionario): p/ → para, c/ → con, s/ → sin, "
        "gat. → gatillo… Las ambiguas (desc, ch) NO se tocan sin contexto: quedan «dudoso».",
        "'Limpiador p/ pisos' → 'Limpiador para pisos'",
    ),
}

# motivo -> qué significa (por qué un producto baja de puntaje o queda dudoso/descartado)
MOTIVOS: dict[str, str] = {
    "sin_tamano": "no tiene tamaño (−20 puntos de los posibles)",
    "sin_marca": "no tiene marca (−20 puntos de los posibles)",
    "nombre_corto": "el nombre tiene una sola palabra",
    "muy_incompleto": "sin marca, sin tamaño y con 2 palabras o menos: se descarta (no se muestra)",
    "nombre_inservible": "el nombre no sirve (sin letras, fecha/hora, muy corto): se descarta",
    "abreviado": "quedó una abreviatura ambigua sin resolver: dudoso, a revisar",
    "tamano_en_conflicto": "el tamaño del campo y el del nombre no coinciden: dudoso (−20)",
    "tamano_campo_corregido": "el campo traía un tamaño inverosímil: se usó el del nombre",
    "tamano_ambiguo": "el nombre trae varios tamaños distintos y no se pudo elegir",
    "marca_en_nombre": "la marca sigue apareciendo dentro del nombre (−5)",
    "fabricante_como_marca": "la fuente puso una razón social como marca",
    "no_latino": "el nombre no está en escritura latina (no se capitaliza)",
}

ESTADOS: dict[str, str] = {
    "completo": "puntaje 75 o más: marca, tamaño y nombre completos",
    "parcial": "puntaje 40-74: usable, le falta algún dato",
    "dudoso": "puntaje menor a 40, o conflicto de tamaño o abreviatura sin resolver: a revisar",
    "descartado": "demasiado incompleto o inservible: se guarda pero no se muestra",
}


def base(id_: str) -> str:
    """`abreviatura_expandida:p/` -> `abreviatura_expandida`."""
    return id_.split(":", 1)[0]


def reglas_en_orden() -> str:
    """Las reglas que aplica el normalizador, en el orden en que se aplican."""
    lineas = []
    for n, (titulo, que, ejemplo) in enumerate(TRANSFORMACIONES.values(), 1):
        lineas.append(f"  {n:>2}. {titulo}: {que}\n      ej.: {ejemplo}")
    return "\n".join(lineas)
