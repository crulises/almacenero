import 'package:almacenero/data/price_repository.dart';
import 'package:almacenero/ui/grafico_precios.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:material_ui/material_ui.dart';

PrecioHistorial _p(String precio, int dia) => PrecioHistorial(
  id: '$precio-$dia',
  localId: 'l1',
  localNombre: 'Local',
  precio: precio,
  fecha: DateTime(2026, 11, dia, 12),
);

Future<void> _montar(WidgetTester tester, List<PrecioHistorial> precios) =>
    tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: SizedBox(height: 240, child: GraficoPrecios(precios: precios)),
        ),
      ),
    );

void main() {
  testWidgets('dibuja máximo, mínimo y fechas extremas', (tester) async {
    await _montar(tester, [_p('1100.00', 20), _p('900.00', 10)]);

    expect(tester.takeException(), isNull);
    expect(find.text('\$ 1.100'), findsOneWidget);
    expect(find.text('\$ 900'), findsOneWidget);
    expect(find.text('10/11'), findsOneWidget);
    expect(find.text('20/11'), findsOneWidget);
  });

  testWidgets('un solo precio: un punto, sin romper', (tester) async {
    await _montar(tester, [_p('1000.00', 10)]);

    expect(tester.takeException(), isNull);
    expect(find.text('\$ 1.000'), findsOneWidget);
    expect(find.text('10/11'), findsOneWidget);
  });

  testWidgets('todos iguales: línea plana, sin dividir por cero', (
    tester,
  ) async {
    await _montar(tester, [_p('500.00', 1), _p('500.00', 5), _p('500.00', 9)]);

    expect(tester.takeException(), isNull);
    expect(find.text('\$ 500'), findsOneWidget);
  });

  testWidgets('tocar un punto muestra su precio y día; tocar lejos lo saca', (
    tester,
  ) async {
    await _montar(tester, [_p('1100.00', 20), _p('900.00', 10)]);
    final origen = tester.getTopLeft(find.byType(GraficoPrecios));
    final globo = find.byKey(const ValueKey('punto-tocado'));
    expect(globo, findsNothing);

    // El punto más viejo (900) queda en el borde izquierdo del área, abajo:
    // eje 880..1120, área de 204 px a partir de 12.
    await tester.tapAt(origen + const Offset(64, 12 + 220 / 240 * 204));
    await tester.pump();
    expect(globo, findsOneWidget);
    expect(find.text('\$ 900,00 · 10/11'), findsOneWidget);

    await tester.tapAt(origen + const Offset(400, 120));
    await tester.pump();
    expect(globo, findsNothing);
  });
}
