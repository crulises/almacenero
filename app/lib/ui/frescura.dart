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
