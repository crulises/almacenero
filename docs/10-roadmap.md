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

| Release | Qué trae | Estado |
|---|---|---|
| **0.1.x** | Todo lo de v0.0.2 ya mergeado (roles, geofence, ETL, precios vigentes y mapa, anti-spam, panel de admin, moderación, catálogo normalizado, CSV curado, ETL desde el panel, dashboard 19a/19b/19c) **más el corte 20**: volver a la ficha tras cargar, «Escanear otro», Recientes y «Sé el primero» | en curso; **se cierra con el corte 20** y se prueba solo, en local |
| **0.2.x** | «Precios por refrescar» (cola priorizada por consultas, karma ponderado por frescura), validación colaborativa, línea «ahorrás X% yendo a Y» en la ficha | planificado |
| **0.3.x** | Perfil (karma, historial propio, gamificación) y **lista de compras** en un tab propio | planificado |
| **0.4.x** | Seguir productos y notificaciones (pocas, con tope) | planificado |
| **Sin versión asignada** | Deploy a Fly y Cloudflare (corte 10, PR #19, pausado), proveedor de tiles propio, apertura de registros y alta de locales, patrocinio, iOS, offline y sync | hitos aparte |

El **deploy no está atado a una versión de la app**: el dueño prefiere probar mucho en local antes de
abrirlo. El `applicationId` `dev.crulises.almacenero`, Fly y Cloudflare siguen decididos.

## Detalle por release

### 0.1.x — cierre con el corte 20
Ver `docs/superpowers/specs/2026-11-25-flujo-carga-recientes-design.md`. Nada más entra en el 0.1.x
salvo que el dueño lo pida mientras prueba.

### 0.2.x — confianza y frescura
- **Precios por refrescar:** lista de productos del local donde estás con precio de más de N días,
  priorizada por lo que más se consulta (`eventos` del corte 19b). Refrescar da más karma que
  recargar algo fresco.
- **Validación colaborativa y cola** (hoy fuera de alcance en el Doc 1).
- **Línea de ahorro en la ficha:** «ahorrás 12% yendo a X», solo con mínimos de datos, frescura y
  descontando la distancia (3 km para ahorrar unos pesos no es negocio). No acumula nada.

### 0.3.x — perfil y listas
- Perfil con karma, historial propio y lo que haga falta de gamificación.
- Lista de compras en un tab propio y qué local conviene para toda la lista, con los mismos mínimos
  de datos y frescura. Puede mostrar el ahorro **de la lista contra comprar todo en un solo local**
  (se calcula solo con precios); no hay ahorro acumulado.

### 0.4.x — seguir productos
- Seguir un producto y avisar cuando baja. Pide notificaciones (push), por eso va después y con tope
  para no hacer spam.

## Ideas anotadas, sin lugar todavía
- «Precio relativo al promedio» por zona (Doc 4, §11.6).
- Precios de referencia de fuentes oficiales para arrancar la zona: habría que revisar el Doc 1 y la
  licencia antes de proponerlo.
