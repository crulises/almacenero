import 'package:almacenero/data/api_client.dart';
import 'package:almacenero/data/product_repository.dart';
import 'package:almacenero/data/user_repository.dart';
import 'package:almacenero/main.dart';
import 'package:material_ui/material_ui.dart';
import 'package:flutter_test/flutter_test.dart';

const _aceite = Producto(
  id: 'p1',
  ean: '7790070411112',
  nombre: 'Aceite de girasol',
  marca: 'Ejemplo',
  tamanoValor: 900,
  tamanoUnidad: 'ml',
);

Future<Me> _me() async => const Me(id: 'u1', alias: 'anon-abc123', karma: 3);

Future<Producto> _noEncontrado(String ean) =>
    Future.error(ApiException('Error 404', statusCode: 404));

Widget _app({
  Future<Me> Function()? loadMe,
  Future<Producto> Function(String)? loadProducto,
}) => AlmaceneroApp(
  loadMe: loadMe ?? _me,
  loadProducto: loadProducto ?? (_) async => _aceite,
);

Future<void> _buscar(WidgetTester tester, String ean) async {
  await tester.enterText(find.byType(TextField), ean);
  await tester.tap(find.byTooltip('Buscar'));
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('muestra alias y karma del usuario', (tester) async {
    await tester.pumpWidget(_app());
    expect(find.text('Almacenero'), findsOneWidget);

    await tester.pumpAndSettle();
    expect(find.text('anon-abc123'), findsOneWidget);
    expect(find.text('Karma: 3'), findsOneWidget);
  });

  testWidgets('si falla, ofrece reintentar y se recupera', (tester) async {
    var llamadas = 0;
    await tester.pumpWidget(
      _app(
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

  testWidgets('búsqueda manual: muestra la ficha del producto', (tester) async {
    String? buscado;
    await tester.pumpWidget(
      _app(
        loadProducto: (ean) async {
          buscado = ean;
          return _aceite;
        },
      ),
    );
    await tester.pumpAndSettle();

    await _buscar(tester, ' 7790070411112 ');
    expect(buscado, '7790070411112');
    expect(find.text('Aceite de girasol'), findsOneWidget);
    expect(find.text('Ejemplo · 900 ml'), findsOneWidget);
    expect(find.text('EAN 7790070411112'), findsOneWidget);
  });

  testWidgets('código inválido: no busca y marca el error', (tester) async {
    var llamadas = 0;
    await tester.pumpWidget(
      _app(
        loadProducto: (_) async {
          llamadas++;
          return _aceite;
        },
      ),
    );
    await tester.pumpAndSettle();

    await _buscar(tester, '123');
    expect(find.text('Ingresá entre 8 y 14 dígitos'), findsOneWidget);
    expect(llamadas, 0);
  });

  testWidgets('producto fuera del catálogo: lo avisa, sin reintentar', (
    tester,
  ) async {
    await tester.pumpWidget(_app(loadProducto: _noEncontrado));
    await tester.pumpAndSettle();

    await _buscar(tester, '7799999999999');
    expect(
      find.text('Este producto todavía no está en el catálogo.'),
      findsOneWidget,
    );
    expect(find.text('Reintentar'), findsNothing);
  });

  testWidgets('EAN de balanza: explica que no está habilitado', (tester) async {
    await tester.pumpWidget(
      _app(
        loadProducto: (_) =>
            Future.error(ApiException('Error 422', statusCode: 422)),
      ),
    );
    await tester.pumpAndSettle();

    await _buscar(tester, '2000000012345');
    expect(find.textContaining('código interno de balanza'), findsOneWidget);
  });
}
