import 'package:material_ui/material_ui.dart';

import '../app_deps.dart';
import 'product_screen.dart';

/// «Escanear otro»: lee otro código sin pasar por el inicio y abre su ficha. Cancelar deja
/// todo como estaba.
///
/// Desde la ficha, la reemplaza (un solo «atrás» lleva al inicio, por muchos que se escaneen
/// seguidos). Con [desdeHistorial] vuelve primero al inicio y apila la ficha nueva ahí: si no,
/// «atrás» caería en la ficha anterior.
Future<void> escanearOtro(
  BuildContext context,
  AppDeps deps, {
  bool desdeHistorial = false,
}) async {
  final nav = Navigator.of(context);
  final ean = await nav.push<String>(
    MaterialPageRoute<String>(builder: (_) => deps.pantallaEscaneo()),
  );
  if (ean == null || !context.mounted) return;
  final ruta = MaterialPageRoute<void>(
    builder: (_) => ProductScreen(ean: ean, deps: deps, via: 'camara'),
  );
  if (desdeHistorial) {
    nav.popUntil((r) => r.isFirst);
    await nav.push(ruta);
  } else {
    await nav.pushReplacement(ruta);
  }
}
