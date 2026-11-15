import 'package:almacenero/app_deps.dart';
import 'package:almacenero/data/api_client.dart';
import 'package:almacenero/data/local_repository.dart';
import 'package:almacenero/data/price_repository.dart';
import 'package:almacenero/data/product_repository.dart';
import 'package:almacenero/data/user_repository.dart';
import 'package:almacenero/main.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:material_ui/material_ui.dart';

const _aceite = Producto(
  id: 'p1',
  ean: '7790070411112',
  nombre: 'Aceite de girasol',
  marca: 'Ejemplo',
  tamanoValor: 900,
  tamanoUnidad: 'ml',
);

const _local = Local(id: 'l1', nombre: 'Local del admin');

/// Backend de mentira: el karma sube con cada precio cargado, como en el real.
class _Backend {
  int karma = 0;
  final cargas = <({String ean, String localId, String precio})>[];
  Object? errorAlCargar;

  AppDeps deps({Future<Producto> Function(String)? loadProducto}) => AppDeps(
    loadMe: () async => Me(id: 'u1', alias: 'anon-abc123', karma: karma),
    loadProducto: loadProducto ?? (_) async => _aceite,
    loadLocales: () async => [_local],
    cargarPrecio: ({required ean, required localId, required precio}) async {
      final error = errorAlCargar;
      if (error != null) {
        errorAlCargar = null; // falla una sola vez
        throw error;
      }
      cargas.add((ean: ean, localId: localId, precio: precio));
      karma++;
      return PrecioCargado(precioId: 'pr${cargas.length}', karma: karma);
    },
  );
}

Future<void> _buscar(WidgetTester tester, String ean) async {
  await tester.enterText(find.byType(TextField), ean);
  await tester.tap(find.byTooltip('Buscar'));
  await tester.pumpAndSettle();
}

final _botonCargar = find.widgetWithText(FilledButton, 'Cargar precio');

Future<void> _irAlFormulario(WidgetTester tester) async {
  await _buscar(tester, _aceite.ean);
  await tester.tap(_botonCargar);
  await tester.pumpAndSettle();
}

Future<void> _enviarPrecio(WidgetTester tester, String precio) async {
  await tester.enterText(find.byType(TextField), precio);
  await tester.tap(_botonCargar);
  await tester.pumpAndSettle();
}

void main() {
  late _Backend backend;

  setUp(() => backend = _Backend());

  Future<void> abrir(WidgetTester tester, {AppDeps? deps}) async {
    await tester.pumpWidget(AlmaceneroApp(deps: deps ?? backend.deps()));
    await tester.pumpAndSettle();
  }

  group('inicio', () {
    testWidgets('muestra alias y karma del usuario', (tester) async {
      backend.karma = 3;
      await abrir(tester);
      expect(find.text('Almacenero'), findsOneWidget);
      expect(find.text('anon-abc123'), findsOneWidget);
      expect(find.text('Karma: 3'), findsOneWidget);
    });

    testWidgets('si falla, ofrece reintentar y se recupera', (tester) async {
      var llamadas = 0;
      await abrir(
        tester,
        deps: AppDeps(
          loadMe: () async {
            llamadas++;
            if (llamadas == 1) throw Exception('sin red');
            return const Me(id: 'u1', alias: 'anon-abc123', karma: 0);
          },
          loadProducto: (_) async => _aceite,
          loadLocales: () async => [_local],
          cargarPrecio: ({required ean, required localId, required precio}) =>
              throw UnimplementedError(),
        ),
      );
      expect(find.text('No pudimos conectar con el servidor'), findsOneWidget);

      await tester.tap(find.text('Reintentar'));
      await tester.pumpAndSettle();
      expect(find.text('anon-abc123'), findsOneWidget);
    });
  });

  group('buscar producto', () {
    testWidgets('búsqueda manual: muestra la ficha', (tester) async {
      String? buscado;
      await abrir(
        tester,
        deps: backend.deps(
          loadProducto: (ean) async {
            buscado = ean;
            return _aceite;
          },
        ),
      );

      await _buscar(tester, ' 7790070411112 ');
      expect(buscado, '7790070411112');
      expect(find.text('Aceite de girasol'), findsOneWidget);
      expect(find.text('Ejemplo · 900 ml'), findsOneWidget);
      expect(find.text('EAN 7790070411112'), findsOneWidget);
    });

    testWidgets('código inválido: no busca y marca el error', (tester) async {
      var llamadas = 0;
      await abrir(
        tester,
        deps: backend.deps(
          loadProducto: (_) async {
            llamadas++;
            return _aceite;
          },
        ),
      );

      await _buscar(tester, '123');
      expect(find.text('Ingresá entre 8 y 14 dígitos'), findsOneWidget);
      expect(llamadas, 0);
    });

    testWidgets('fuera del catálogo: lo avisa y no ofrece cargar precio', (
      tester,
    ) async {
      await abrir(
        tester,
        deps: backend.deps(
          loadProducto: (_) =>
              Future.error(ApiException('Error 404', statusCode: 404)),
        ),
      );

      await _buscar(tester, '7799999999999');
      expect(
        find.text('Este producto todavía no está en el catálogo.'),
        findsOneWidget,
      );
      expect(find.text('Reintentar'), findsNothing);
      expect(_botonCargar, findsNothing);
    });

    testWidgets('EAN de balanza: explica que no está habilitado', (
      tester,
    ) async {
      await abrir(
        tester,
        deps: backend.deps(
          loadProducto: (_) =>
              Future.error(ApiException('Error 422', statusCode: 422)),
        ),
      );

      await _buscar(tester, '2000000012345');
      expect(find.textContaining('código interno de balanza'), findsOneWidget);
    });
  });

  group('cargar precio', () {
    testWidgets('carga el precio y el karma sube, también en el inicio', (
      tester,
    ) async {
      await abrir(tester);
      expect(find.text('Karma: 0'), findsOneWidget);

      await _irAlFormulario(tester);
      expect(find.text('Aceite de girasol'), findsOneWidget);
      expect(find.text('en Local del admin'), findsOneWidget);

      await _enviarPrecio(
        tester,
        '1234,5',
      ); // coma decimal, como se escribe acá

      expect(backend.cargas, hasLength(1));
      expect(backend.cargas.single.ean, '7790070411112');
      expect(backend.cargas.single.localId, 'l1');
      expect(backend.cargas.single.precio, '1234.50');
      expect(find.text('¡Precio cargado!'), findsOneWidget);
      expect(find.text('Tu karma ahora es 1'), findsOneWidget);

      await tester.tap(find.text('Listo'));
      await tester.pumpAndSettle();
      expect(find.text('Karma: 1'), findsOneWidget); // el inicio se refrescó
      // y queda listo para el próximo producto
      expect(
        tester.widget<TextField>(find.byType(TextField)).controller!.text,
        '',
      );
    });

    testWidgets('precio inválido: no se envía y marca el error', (
      tester,
    ) async {
      await abrir(tester);
      await _irAlFormulario(tester);

      for (final malo in ['', '0', 'abc', '10,999', '-5']) {
        await _enviarPrecio(tester, malo);
        expect(
          find.text('Ingresá un precio mayor a 0 (ej. 1234,50)'),
          findsOneWidget,
          reason: '"$malo" debería rechazarse',
        );
      }
      expect(backend.cargas, isEmpty);
      expect(backend.karma, 0);
    });

    testWidgets('si falla la red, avisa y deja reintentar', (tester) async {
      backend.errorAlCargar = ApiException('Sin conexión');
      await abrir(tester);
      await _irAlFormulario(tester);

      await _enviarPrecio(tester, '500');
      expect(
        find.text('No pudimos cargar el precio. Probá de nuevo.'),
        findsOneWidget,
      );
      expect(find.text('¡Precio cargado!'), findsNothing);
      expect(backend.karma, 0);

      await tester.tap(_botonCargar); // el precio sigue escrito
      await tester.pumpAndSettle();
      expect(find.text('¡Precio cargado!'), findsOneWidget);
      expect(backend.karma, 1);
    });

    testWidgets('si el servidor no encuentra el producto, lo explica', (
      tester,
    ) async {
      backend.errorAlCargar = ApiException('Error 404', statusCode: 404);
      await abrir(tester);
      await _irAlFormulario(tester);

      await _enviarPrecio(tester, '500');
      expect(find.textContaining('No encontramos el producto'), findsOneWidget);
    });
  });
}
