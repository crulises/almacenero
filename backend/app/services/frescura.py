"""Frescura de un precio: la inflación envejece los precios rápido (Doc 1).

verde → amarillo → rojo según la antigüedad, con umbrales en `config`
(`umbral_verde_dias`, `umbral_amarillo_dias`). Más viejo que
`ventana_frescura_dias` se marca además como `vencido`.
"""


def clasificar(edad_dias: int, umbral_verde: int, umbral_amarillo: int) -> str:
    if edad_dias <= umbral_verde:
        return "verde"
    if edad_dias <= umbral_amarillo:
        return "amarillo"
    return "rojo"
