import 'package:material_ui/material_ui.dart';

import '../data/price_repository.dart';

/// Color del semáforo de frescura (verde → amarillo → rojo, Doc 1).
Color colorFrescura(PrecioVigente p) {
  if (p.vencido) return Colors.grey.shade700;
  return switch (p.frescura) {
    'verde' => Colors.green.shade700,
    'amarillo' => Colors.amber.shade800,
    _ => Colors.red.shade700,
  };
}

/// Texto corto del estado de frescura.
String etiquetaFrescura(PrecioVigente p) {
  if (p.vencido) return 'Vencido';
  return switch (p.frescura) {
    'verde' => 'Fresco',
    'amarillo' => 'Reciente',
    _ => 'Viejo',
  };
}

/// Cómo se ordena la lista de precios. «Reputación» y «patrocinado» se suman
/// cuando existan en el backend (ver docs/04, §5).
enum OrdenPrecios {
  precio('Precio'),
  cercania('Cercanía'),
  frescura('Frescura');

  const OrdenPrecios(this.etiqueta);

  final String etiqueta;
}

/// Ordena sin tocar la lista original. El precio es el desempate de todos.
List<PrecioVigente> ordenarPrecios(
  List<PrecioVigente> precios,
  OrdenPrecios orden,
) {
  int porPrecio(PrecioVigente a, PrecioVigente b) =>
      double.parse(a.precio).compareTo(double.parse(b.precio));
  final copia = [...precios];
  switch (orden) {
    case OrdenPrecios.precio:
      copia.sort(porPrecio);
    case OrdenPrecios.cercania:
      copia.sort((a, b) {
        final c = (a.distanciaM ?? double.infinity).compareTo(
          b.distanciaM ?? double.infinity,
        );
        return c != 0 ? c : porPrecio(a, b);
      });
    case OrdenPrecios.frescura:
      copia.sort((a, b) {
        final c = a.edadDias.compareTo(b.edadDias);
        return c != 0 ? c : porPrecio(a, b);
      });
  }
  return copia;
}
