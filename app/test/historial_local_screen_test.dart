import 'package:almacenero/app_deps.dart';
import 'package:almacenero/data/api_client.dart';
import 'package:almacenero/data/location_service.dart';
import 'package:almacenero/data/price_repository.dart';
import 'package:almacenero/data/product_repository.dart';
import 'package:almacenero/data/user_repository.dart';
import 'package:almacenero/ui/grafico_precios.dart';
import 'package:almacenero/ui/historial_local_screen.dart';
import 'package:almacenero/ui/product_screen.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:material_ui/material_ui.dart';

const _aceite = Producto(
  id: 'p1',
  ean: '7790070411112',
  nombre: 'Aceite de girasol',
  marca: 'Ejemplo',
);
const _aca = Ubicacion(lat: -34.6, lng: -58.4, precisionM: 10);

const _cerca = LocalDelProducto(
  localId: 'l1',
  localNombre: 'Super Uno',
  lat: -34.601,
  lng: -58.401,
  distanciaM: 120,
  ultimoPrecio: '900.00',
);
const _otro = LocalDelProducto(
  localId: 'l2',
  localNombre: 'Kiosco Dos',
  lat: -34.61,
  lng: -58.41,
  distanciaM: 1400,
  ultimoPrecio: '1000.00',
);
const _sinPrecios = LocalDelProducto(
  localId: 'l3',
  localNombre: 'Almacen Tres',
  lat: -34.62,
  lng: -58.42,
  distanciaM: 80,
);

PrecioHistorial _h(String local, String precio, int dia) => PrecioHistorial(
  id: '$local-$precio',
  localId: local,
  localNombre: local,
  precio: precio,
  fecha: DateTime(2026, 11, dia, 12),
);

class _Falso {
  List<LocalDelProducto> locales = [_cerca, _otro];
  final historiales = <String, List<PrecioHistorial>>{
    'l1': [_h('l1', '900.00', 20), _h('l1', '1000.00', 10)],
    'l2': [_h('l2', '1000.00', 15)],
    'l3': [],
  };
  Object? errorLocales;
  bool sinGps = false;
  final pedidosHistorial = <String>[];
  Ubicacion? ubicacionPedida;
  String? escaneo;

  AppDeps deps() => AppDeps(
    pantallaEscaneo: () => _Escaner(escaneo),
    loadMe: () async =>
        const Me(id: 'u', alias: 'a', karma: 0, escalon: Escalon.normal),
    loadProducto: (_) async => _aceite,
    obtenerUbicacion: () async {
      if (sinGps) throw const UbicacionException(UbicacionError.otro);
      return _aca;
    },
    abrirAjustes: () async {},
    loadLocalesCerca: (_) async => const [],
    crearLocal: ({required nombre, direccion, required ubicacion}) =>
        throw UnimplementedError(),
    cargarPrecio: ({
      required ean,
      required localId,
      required precio,
      required ubicacion,
    }) => throw UnimplementedError(),
    loadHistorial: (_) async => const [],
    loadVigentes: (_, {ubicacion, referencia = false}) async => const [],
    loadLocalesDelProducto: (ean, {ubicacion}) async {
      ubicacionPedida = ubicacion;
      final e = errorLocales;
      if (e != null) {
        errorLocales = null;
        throw e;
      }
      return locales;
    },
    loadHistorialLocal: (ean, localId) async {
      pedidosHistorial.add(localId);
      return historiales[localId] ?? [];
    },
  );
}

class _Escaner extends StatefulWidget {
  const _Escaner(this.ean);
  final String? ean;
  @override
  State<_Escaner> createState() => _EscanerState();
}

class _EscanerState extends State<_Escaner> {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) Navigator.of(context).pop(widget.ean);
    });
  }

  @override
  Widget build(BuildContext context) => const Scaffold(body: Text('escáner'));
}

/// Una «ficha» de mentira debajo, para que haya a dónde volver.
Future<void> _abrir(WidgetTester tester, _Falso f) async {
  final deps = f.deps();
  await tester.pumpWidget(
    MaterialApp(
      home: Builder(
        builder: (context) => Scaffold(
          body: Center(
            child: TextButton(
              onPressed: () => Navigator.of(context).push(
                MaterialPageRoute<void>(
                  builder: (_) =>
                      HistorialLocalScreen(producto: _aceite, deps: deps),
                ),
              ),
              child: const Text('inicio'),
            ),
          ),
        ),
      ),
    ),
  );
  await tester.tap(find.text('inicio'));
  await tester.pumpAndSettle();
}

void main() {
  testWidgets(
    'título con el local más cercano y su distancia; producto abajo',
    (tester) async {
      final f = _Falso();
      await _abrir(tester, f);

      expect(find.text('Super Uno'), findsOneWidget);
      expect(find.text('120 m'), findsOneWidget);
      expect(find.text('Aceite de girasol'), findsOneWidget);
      expect(f.ubicacionPedida, isNotNull);
      expect(f.pedidosHistorial, ['l1']);
    },
  );

  testWidgets('abre en «Gráfico»; «Mapa» muestra Vos y Local', (tester) async {
    await _abrir(tester, _Falso());

    expect(find.byType(GraficoPrecios), findsOneWidget);

    await tester.tap(find.text('Mapa'));
    await tester.pumpAndSettle();

    expect(find.text('Vos'), findsOneWidget);
    expect(find.text('Local'), findsOneWidget);
  });

  testWidgets('los tabs van «Gráfico» a la izquierda y «Mapa» a la derecha', (
    tester,
  ) async {
    await _abrir(tester, _Falso());

    final grafico = tester.getTopLeft(find.text('Gráfico')).dx;
    final mapa = tester.getTopLeft(find.text('Mapa')).dx;
    expect(grafico, lessThan(mapa));
  });

  testWidgets('filas con la variación contra el precio anterior', (
    tester,
  ) async {
    await _abrir(tester, _Falso());

    expect(find.text('\$ 900,00'), findsOneWidget);
    expect(find.text('bajó 10%'), findsOneWidget);
    expect(find.text('\$ 1.000,00'), findsOneWidget);
  });

  testWidgets('un solo precio: sin etiqueta de variación', (tester) async {
    final f = _Falso()..locales = [_otro];
    await _abrir(tester, f);

    expect(find.text('\$ 1.000,00'), findsOneWidget);
    expect(find.textContaining('subió'), findsNothing);
    expect(find.textContaining('bajó'), findsNothing);
  });

  testWidgets('cambiar de local pide su historial y cambia el título', (
    tester,
  ) async {
    final f = _Falso();
    await _abrir(tester, f);

    await tester.tap(find.text('Super Uno'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Kiosco Dos').last);
    await tester.pumpAndSettle();

    expect(f.pedidosHistorial, ['l1', 'l2']);
    expect(find.text('Kiosco Dos'), findsOneWidget);
    expect(find.text('1,4 km'), findsOneWidget);
  });

  testWidgets('el selector avisa qué locales no tienen precios', (
    tester,
  ) async {
    final f = _Falso()..locales = [_cerca, _sinPrecios];
    await _abrir(tester, f);

    await tester.tap(find.text('Super Uno'));
    await tester.pumpAndSettle();

    expect(find.textContaining('sin precios'), findsOneWidget);
  });

  testWidgets(
    'local sin precios: mensaje y dos botones; «Ir al inicio» vuelve',
    (tester) async {
      final f = _Falso()..locales = [_sinPrecios];
      await _abrir(tester, f);

      expect(
        find.text('Este local no tiene precios de este producto'),
        findsOneWidget,
      );
      expect(find.text('Escanear'), findsOneWidget);

      await tester.tap(find.text('Ir al inicio'));
      await tester.pumpAndSettle();

      expect(find.text('inicio'), findsOneWidget);
      expect(find.byType(HistorialLocalScreen), findsNothing);
    },
  );

  testWidgets('sin ningún local para elegir: lo dice, con los mismos botones', (
    tester,
  ) async {
    final f = _Falso()..locales = [];
    await _abrir(tester, f);

    expect(
      find.text('No hay locales cercanos con precios de este producto'),
      findsOneWidget,
    );
    expect(find.text('Ir al inicio'), findsOneWidget);
    expect(find.text('Escanear'), findsOneWidget);
  });

  testWidgets('sin GPS: carga igual, sin distancia y sin «Vos»', (
    tester,
  ) async {
    final f = _Falso()
      ..sinGps = true
      ..locales = [
        const LocalDelProducto(
          localId: 'l1',
          localNombre: 'Super Uno',
          lat: -34.6,
          lng: -58.4,
          ultimoPrecio: '900.00',
        ),
      ];
    await _abrir(tester, f);

    expect(f.ubicacionPedida, isNull);
    expect(find.text('Super Uno'), findsOneWidget);
    expect(find.textContaining(' m'), findsNothing);

    await tester.tap(find.text('Mapa'));
    await tester.pumpAndSettle();
    expect(find.text('Vos'), findsNothing);
  });

  testWidgets('falla de red: «Reintentar» recupera', (tester) async {
    final f = _Falso()..errorLocales = ApiException('Sin conexión');
    await _abrir(tester, f);

    expect(find.text('No pudimos cargar el historial.'), findsOneWidget);
    await tester.tap(find.text('Reintentar'));
    await tester.pumpAndSettle();

    expect(find.text('Super Uno'), findsOneWidget);
  });

  testWidgets('«Escanear otro» abre la ficha del código leído', (tester) async {
    final f = _Falso()..escaneo = '7790000000001';
    await _abrir(tester, f);

    await tester.tap(find.text('Escanear otro'));
    await tester.pumpAndSettle();

    expect(find.byType(ProductScreen), findsOneWidget);
    expect(find.byType(HistorialLocalScreen), findsNothing);
    // Un solo «atrás» lleva al inicio.
    await tester.pageBack();
    await tester.pumpAndSettle();
    expect(find.text('inicio'), findsOneWidget);
  });
}
