import '../data/price_repository.dart';

/// Un precio del historial con cuánto cambió respecto del anterior en el mismo local.
class PuntoHistorial {
  const PuntoHistorial({required this.precio, this.variacionPct});

  final PrecioHistorial precio;

  /// `(actual − anterior) / anterior × 100`; nulo para el precio más viejo.
  final double? variacionPct;
}

/// Calcula la variación de cada precio contra el anterior **en el tiempo** (no depende de
/// cómo llegue la lista) y devuelve el más nuevo primero.
List<PuntoHistorial> conVariacion(List<PrecioHistorial> precios) {
  // El desempate por posición mantiene estable el orden de dos precios en el mismo instante.
  final indexados = [for (var i = 0; i < precios.length; i++) (i, precios[i])]
    ..sort((a, b) {
      final c = a.$2.fecha.compareTo(b.$2.fecha);
      // Con la misma fecha, el que llegó antes en la lista (más nuevo) va después.
      return c != 0 ? c : b.$1.compareTo(a.$1);
    });
  final puntos = <PuntoHistorial>[];
  double? anterior;
  for (final (_, p) in indexados) {
    final actual = double.parse(p.precio);
    puntos.add(
      PuntoHistorial(
        precio: p,
        variacionPct: anterior == null
            ? null
            : (actual - anterior) / anterior * 100,
      ),
    );
    anterior = actual;
  }
  return puntos.reversed.toList();
}

/// «subió 8%», «bajó 12%», «sin cambios» (menos de 0,5 %) o nada si no hay con qué comparar.
String etiquetaVariacion(double? pct) {
  if (pct == null) return '';
  if (pct.abs() < 0.5) return 'sin cambios';
  final n = pct.abs().round();
  return pct > 0 ? 'subió $n%' : 'bajó $n%';
}

/// Rango del eje vertical del gráfico, lineal.
class RangoEje {
  const RangoEje(this.min, this.max);

  final double min;
  final double max;
}

/// Mínimo y máximo reales, ampliados un 10 % del rango a cada lado. Si no hay rango (un
/// solo valor o todos iguales) usa ±10 % del valor: nunca divide por cero.
RangoEje rangoEje(List<double> valores) {
  final min = valores.reduce((a, b) => a < b ? a : b);
  final max = valores.reduce((a, b) => a > b ? a : b);
  final rango = max - min;
  final margen = rango == 0
      ? (min.abs() == 0 ? 1.0 : min.abs() * 0.1)
      : rango * 0.1;
  return RangoEje(min - margen, max + margen);
}
