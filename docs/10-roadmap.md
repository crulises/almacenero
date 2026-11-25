# Roadmap de releases

Estado: **propuesto y acordado con el dueño el 2026-11-25**. Es una guía, no un contrato: a medida
que se pruebe, se pueden incluir o excluir features de un release con retoques chicos. Ante una
duda de comportamiento gana el Doc 1; ante una duda técnica, el Doc 2. Los cortes de cada release
se detallan en su plan (`docs/04`) y en los diseños de `docs/superpowers/specs/`.

> «v0.0.1» y «v0.0.2» son nombres históricos de planes (ver Doc 2, «Versionado de releases»). El
> próximo release es **0.1.x**.

## Principios del producto (valen para todos los releases)

1. **La app es una guía, no un tracker financiero.** Dice cuánto sale algo en un lugar y en otro,
   con lo que se sabe. No hay «lo compré acá», ni ahorro acumulado, ni cifras sobre los gastos de
   nadie. Cada decisión se toma con precios, no con suposiciones sobre lo que se compró.
2. **El orden de los precios no se vende.** Si algún día hay patrocinios, el mapa, el «Más barato» y
   cualquier sugerencia de dónde comprar se calculan **solo con precios**; el patrocinio vive aparte,
   siempre marcado (ver `docs/04` §5). Un patrocinio nunca altera una recomendación.
3. **Nunca mostrar vacío.** Un producto sin precio invita a cargarlo («Sé el primero en cargarlo»,
   con bonus de karma).
4. **Mostrar el límite de lo que se sabe.** La frescura y la distancia se ven siempre («visto hace
   3 días», «a 120 km»). Un consejo con pocos datos o muy viejos no se da.
5. **Sin fricción ni spam.** Pocas notificaciones, con tope; el usuario aprecia la app, no la sufre.
6. **Densidad antes que cantidad.** Con pocos usuarios importan pocos locales bien cubiertos y
   frescos, no muchos datos dispersos.

## Releases

Cada release tiene su plan, con la misma estructura que `docs/04-plan-v0.1.md`.

| Release | Plan | Qué trae | Estado |
|---|---|---|---|
| **0.1.x** | `docs/04-plan-v0.1.md` | Roles y alta de local, geofence, ETL, precios vigentes y mapa, anti-spam, panel de admin, moderación, catálogo normalizado, CSV curado, ETL desde el panel, dashboard (19a/19b/19c) y el **corte 20** (volver a la ficha, «Escanear otro», Recientes, «Sé el primero») | **cerrado** (2026-11-25) |
| **0.2.x** | `docs/04-plan-v0.2.md` | Cuentas ligables (email y Google), precios por refrescar, validación colaborativa, línea de ahorro en la ficha | próximo; se define al arrancar |
| **0.3.x** | `docs/04-plan-v0.3.md` | Perfil, lista de compras, gamificación con recompensas, precio relativo al promedio | planificado |
| **0.4.x** | `docs/04-plan-v0.4.md` | Seguir productos y notificaciones (pocas, con tope) | planificado |
| **0.5.x** | `docs/04-plan-v0.5.md` | Modo offline y sync, productos pesables y genéricos | planificado |
| **0.6.x** | `docs/04-plan-v0.6.md` | Apertura al público: deploy (Fly + Cloudflare), tiles propios, registro y alta de locales abiertos, patrocinio y orden por reputación, iOS con Apple ID, política de privacidad | planificado |
| **Sin fecha** | — | Opiniones y calidad de producto | sin diseño |

El **deploy no está atado a una versión de la app** y puede adelantarse si el dueño quiere probar en
serio sin abrir los registros. El `applicationId` `dev.crulises.almacenero`, Fly y Cloudflare siguen
decididos. Lo que hace segura la apertura (identidad recuperable, validación, anti-spam, tiles propios)
va **antes** de ella.

## Detalle
El detalle de cada release (alcance, decisiones abiertas) vive en su plan `04-plan-v0.X.md`. Esta página
solo fija el orden y los principios.

## Ideas anotadas, sin lugar todavía
- «Precio relativo al promedio» por zona (Doc 4, §11.6).
- Precios de referencia de fuentes oficiales para arrancar la zona: habría que revisar el Doc 1 y la
  licencia antes de proponerlo.
