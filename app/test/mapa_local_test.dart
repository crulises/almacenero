import 'package:almacenero/data/location_service.dart';
import 'package:almacenero/ui/mapa_local.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:material_ui/material_ui.dart';

Future<void> _montar(WidgetTester tester, {Ubicacion? usuario}) =>
    tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: SizedBox(
            height: 240,
            child: MapaLocal(
              localLat: -34.6,
              localLng: -58.4,
              usuario: usuario,
            ),
          ),
        ),
      ),
    );

void main() {
  testWidgets('con ubicación muestra «Vos» y «Local»', (tester) async {
    await _montar(tester, usuario: const Ubicacion(lat: -34.601, lng: -58.401));

    expect(find.text('Vos'), findsOneWidget);
    expect(find.text('Local'), findsOneWidget);
  });

  testWidgets('sin ubicación solo «Local»', (tester) async {
    await _montar(tester);

    expect(find.text('Vos'), findsNothing);
    expect(find.text('Local'), findsOneWidget);
  });
}
