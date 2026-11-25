import 'package:almacenero/data/api_client.dart';
import 'package:almacenero/data/user_repository.dart';
import 'package:almacenero/ui/alias_editable.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:material_ui/material_ui.dart';

Me _me({bool puede = true, String alias = 'anon-abc123'}) =>
    Me(id: 'u1', alias: alias, karma: 0, puedeCambiarAlias: puede);

void main() {
  test('Me lee puede_cambiar_alias; sin el campo (backend viejo) es false', () {
    final me = Me.fromJson({
      'id': 'u1',
      'alias': 'a',
      'karma': 0,
      'puede_cambiar_alias': true,
    });
    expect(me.puedeCambiarAlias, isTrue);
    expect(
      Me.fromJson({'id': 'u1', 'alias': 'a', 'karma': 0}).puedeCambiarAlias,
      isFalse,
    );
  });

  group('AliasEditable', () {
    late List<String> guardados;
    Future<String> Function(String) onGuardar = (a) async => a;

    Future<void> montar(WidgetTester tester, Me me) async {
      guardados = [];
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: AliasEditable(
              me: me,
              onGuardar: (a) {
                guardados.add(a);
                return onGuardar(a);
              },
            ),
          ),
        ),
      );
    }

    setUp(() => onGuardar = (a) async => a);

    testWidgets('sin permiso no hay lápiz', (tester) async {
      await montar(tester, _me(puede: false));
      expect(find.text('anon-abc123'), findsOneWidget);
      expect(find.byIcon(Icons.edit), findsNothing);
    });

    testWidgets('el lápiz vuelve editable el alias y al salir del campo se '
        'guarda', (tester) async {
      await montar(tester, _me());
      expect(find.byType(TextField), findsNothing);

      await tester.tap(find.byIcon(Icons.edit));
      await tester.pump();
      expect(find.byType(TextField), findsOneWidget);
      expect(find.text('anon-abc123'), findsOneWidget); // arranca con el actual

      await tester.enterText(find.byType(TextField), '  Lucía P.  ');
      FocusManager.instance.primaryFocus?.unfocus();
      await tester.pumpAndSettle();

      expect(guardados, ['Lucía P.']);
      expect(find.byType(TextField), findsNothing);
      expect(find.text('Lucía P.'), findsOneWidget);
    });

    testWidgets('confirmar con el teclado guarda una sola vez', (tester) async {
      await montar(tester, _me());
      await tester.tap(find.byIcon(Icons.edit));
      await tester.pump();
      await tester.enterText(find.byType(TextField), 'Pedro');
      await tester.testTextInput.receiveAction(TextInputAction.done);
      await tester.pumpAndSettle();
      expect(guardados, ['Pedro']);
    });

    testWidgets('si no cambió, no se manda nada', (tester) async {
      await montar(tester, _me());
      await tester.tap(find.byIcon(Icons.edit));
      await tester.pump();
      FocusManager.instance.primaryFocus?.unfocus();
      await tester.pumpAndSettle();
      expect(guardados, isEmpty);
      expect(find.text('anon-abc123'), findsOneWidget);
    });

    testWidgets(
      'si el servidor lo rechaza vuelve al alias anterior y explica',
      (tester) async {
        onGuardar = (_) => throw ApiException(
          'Unprocessable',
          statusCode: 409,
          detail: {
            'codigo': 'alias_en_uso',
            'mensaje': 'Ese alias ya lo tiene otra persona.',
            'como_resolver': 'Elegí otro.',
          },
        );
        await montar(tester, _me());
        await tester.tap(find.byIcon(Icons.edit));
        await tester.pump();
        await tester.enterText(find.byType(TextField), 'Pedro');
        FocusManager.instance.primaryFocus?.unfocus();
        await tester.pumpAndSettle();

        expect(find.text('anon-abc123'), findsOneWidget);
        expect(find.text('Pedro'), findsNothing);
        expect(
          find.textContaining('Ese alias ya lo tiene otra persona.'),
          findsOneWidget,
        );
      },
    );

    testWidgets('un error de red también vuelve atrás y avisa', (tester) async {
      onGuardar = (_) => throw ApiException('sin red');
      await montar(tester, _me());
      await tester.tap(find.byIcon(Icons.edit));
      await tester.pump();
      await tester.enterText(find.byType(TextField), 'Pedro');
      FocusManager.instance.primaryFocus?.unfocus();
      await tester.pumpAndSettle();
      expect(find.text('anon-abc123'), findsOneWidget);
      expect(
        find.textContaining('No se pudo cambiar el alias'),
        findsOneWidget,
      );
    });
  });
}
