import 'package:almacenero/data/user_repository.dart';
import 'package:almacenero/main.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  testWidgets('muestra alias y karma del usuario', (tester) async {
    await tester.pumpWidget(
      AlmaceneroApp(
        loadMe: () async => const Me(id: 'u1', alias: 'anon-abc123', karma: 3),
      ),
    );
    expect(find.text('Almacenero'), findsOneWidget);

    await tester.pumpAndSettle();
    expect(find.text('anon-abc123'), findsOneWidget);
    expect(find.text('Karma: 3'), findsOneWidget);
  });

  testWidgets('si falla, ofrece reintentar y se recupera', (tester) async {
    var llamadas = 0;
    await tester.pumpWidget(
      AlmaceneroApp(
        loadMe: () async {
          llamadas++;
          if (llamadas == 1) throw Exception('sin red');
          return const Me(id: 'u1', alias: 'anon-abc123', karma: 0);
        },
      ),
    );
    await tester.pumpAndSettle();
    expect(find.text('No pudimos conectar con el servidor'), findsOneWidget);

    await tester.tap(find.text('Reintentar'));
    await tester.pumpAndSettle();
    expect(find.text('anon-abc123'), findsOneWidget);
  });
}
