import 'package:almacenero/main.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  testWidgets('muestra la pantalla inicial', (tester) async {
    await tester.pumpWidget(const AlmaceneroApp());
    expect(find.text('Almacenero'), findsOneWidget);
    expect(find.text('Escaneá un producto para empezar'), findsOneWidget);
  });
}
