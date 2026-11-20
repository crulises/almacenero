import 'package:almacenero/app_deps.dart';
import 'package:almacenero/data/api_client.dart';
import 'package:almacenero/data/app_info.dart';
import 'package:almacenero/data/auth_repository.dart';
import 'package:almacenero/data/local_repository.dart';
import 'package:almacenero/data/location_service.dart';
import 'package:almacenero/data/price_repository.dart';
import 'package:almacenero/data/product_repository.dart';
import 'package:almacenero/data/user_repository.dart';
import 'package:almacenero/main.dart';
import 'package:flutter_map/flutter_map.dart';
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
const _aca = Ubicacion(lat: -34.6, lng: -58.4, precisionM: 12);

/// Backend de mentira: el karma sube con cada precio cargado, como en el real.
class _Backend {
  int karma = 0;
  final cargas =
      <({String ean, String localId, String precio, Ubicacion ubicacion})>[];
  Object? errorAlCargar;
  Object? errorHistorial;
  Object? errorVigentes;
  final ubicacionesVigentes = <Ubicacion?>[];

  /// Simula que no hay precios en el radio: solo aparecen sin ubicación.
  bool soloLejos = false;
  final vigentes = <PrecioVigente>[];
  Object? errorUbicacion;
  Object? errorAlCrear;
  var ajustesAbiertos = 0;
  Ubicacion? ubicacionPedida;
  final cerca = <Local>[_local];
  final creados = <({String nombre, String? direccion, Ubicacion ubicacion})>[];
  final precios = <PrecioHistorial>[];

  AppDeps deps({Future<Producto> Function(String)? loadProducto}) => AppDeps(
    loadMe: () async => Me(id: 'u1', alias: 'anon-abc123', karma: karma),
    loadProducto: loadProducto ?? (_) async => _aceite,
    obtenerUbicacion: () async {
      final error = errorUbicacion;
      if (error != null) {
        errorUbicacion = null; // falla una sola vez
        throw error;
      }
      return _aca;
    },
    abrirAjustes: () async => ajustesAbiertos++,
    loadLocalesCerca: (u) async {
      ubicacionPedida = u;
      return List.of(cerca);
    },
    crearLocal: ({required nombre, direccion, required ubicacion}) async {
      final error = errorAlCrear;
      if (error != null) {
        errorAlCrear = null; // falla una sola vez
        throw error;
      }
      creados.add((nombre: nombre, direccion: direccion, ubicacion: ubicacion));
      final local = Local(
        id: 'nuevo${creados.length}',
        nombre: nombre,
        verificado: false,
      );
      cerca.insert(0, local);
      return local;
    },
    loadVigentes: (_, {ubicacion}) async {
      ubicacionesVigentes.add(ubicacion);
      if (soloLejos && ubicacion != null) return [];
      final error = errorVigentes;
      if (error != null) {
        errorVigentes = null; // falla una sola vez
        throw error;
      }
      return List.of(vigentes);
    },
    loadHistorial: (_) async {
      final error = errorHistorial;
      if (error != null) {
        errorHistorial = null; // falla una sola vez
        throw error;
      }
      return precios.reversed.toList(); // el más nuevo primero
    },
    cargarPrecio:
        ({
          required ean,
          required localId,
          required precio,
          required ubicacion,
        }) async {
          final error = errorAlCargar;
          if (error != null) {
            errorAlCargar = null; // falla una sola vez
            throw error;
          }
          cargas.add((
            ean: ean,
            localId: localId,
            precio: precio,
            ubicacion: ubicacion,
          ));
          vigentes
            ..removeWhere((v) => v.localId == localId)
            ..add(
              PrecioVigente(
                localId: localId,
                localNombre: 'Local $localId',
                localVerificado: true,
                lat: -34.6,
                lng: -58.4,
                precio: precio,
                fecha: DateTime.now(),
                edadDias: 0,
                frescura: 'verde',
                vencido: false,
              ),
            )
            ..sort((a, b) => a.precio.compareTo(b.precio));
          precios.add(
            PrecioHistorial(
              id: 'pr${cargas.length}',
              localNombre: _local.nombre,
              precio: precio,
              fecha: DateTime.now(),
            ),
          );
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

    testWidgets('pide el código de invitación y reintenta con él', (
      tester,
    ) async {
      String? guardado;
      var rechazar = false;
      await abrir(
        tester,
        deps: AppDeps(
          guardarInvitacion: (c) async => guardado = c,
          loadMe: () async {
            if (guardado == null) throw const InvitacionRequerida();
            if (rechazar) {
              rechazar = false;
              throw const InvitacionRequerida(rechazada: true);
            }
            return const Me(id: 'u1', alias: 'anon-abc123', karma: 0);
          },
          loadProducto: (_) async => _aceite,
          obtenerUbicacion: () async => _aca,
          abrirAjustes: () async {},
          loadLocalesCerca: (_) async => [_local],
          crearLocal: ({required nombre, direccion, required ubicacion}) =>
              throw UnimplementedError(),
          loadHistorial: (_) async => [],
          loadVigentes: (_, {ubicacion}) async => [],
          cargarPrecio: ({
            required ean,
            required localId,
            required precio,
            required ubicacion,
          }) => throw UnimplementedError(),
        ),
      );
      // Es la ÚNICA opción: no hay nada más de la app a la vista.
      expect(find.text('Código de invitación'), findsOneWidget);
      expect(find.text('Escanear código'), findsNothing);
      expect(find.byType(TextField), findsOneWidget);

      await tester.enterText(find.byType(TextField), ' grupo ');
      await tester.tap(find.text('Entrar'));
      await tester.pumpAndSettle();
      expect(guardado, 'grupo');
      expect(find.text('anon-abc123'), findsOneWidget);
      expect(find.text('Escanear código'), findsOneWidget);
    });

    testWidgets('muestra versión, servidor e IP del celular', (tester) async {
      await abrir(
        tester,
        deps: AppDeps(
          loadInfoApp: () async => const InfoApp(
            build: BuildInfo(
              version: '0.0.7',
              commit: 'abc1234',
              compilado: '2026-11-20T17:00',
            ),
            apiUrl: 'http://192.168.1.5:8000',
            ips: [IpLocal(interfaz: 'wlan0', ip: '192.168.1.42')],
            servidor: 'responde (35 ms)',
          ),
          loadMe: () async =>
              const Me(id: 'u1', alias: 'anon-abc123', karma: 0),
          loadProducto: (_) async => _aceite,
          obtenerUbicacion: () async => _aca,
          abrirAjustes: () async {},
          loadLocalesCerca: (_) async => [_local],
          crearLocal: ({required nombre, direccion, required ubicacion}) =>
              throw UnimplementedError(),
          loadHistorial: (_) async => [],
          loadVigentes: (_, {ubicacion}) async => [],
          cargarPrecio: ({
            required ean,
            required localId,
            required precio,
            required ubicacion,
          }) => throw UnimplementedError(),
        ),
      );
      expect(find.text('Versión: 0.0.7 (abc1234)'), findsOneWidget);
      expect(find.text('Servidor: http://192.168.1.5:8000'), findsOneWidget);
      expect(find.text('Estado: responde (35 ms)'), findsOneWidget);
      expect(find.text('IP del celular: 192.168.1.42 (wlan0)'), findsOneWidget);
    });

    testWidgets('si el servidor rechaza el alta, dice la causa real', (
      tester,
    ) async {
      await abrir(
        tester,
        deps: AppDeps(
          loadMe: () async => throw ApiException(
            'Error 403',
            statusCode: 403,
            detail: {'codigo': 'alta_cerrada'},
          ),
          loadProducto: (_) async => _aceite,
          obtenerUbicacion: () async => _aca,
          abrirAjustes: () async {},
          loadLocalesCerca: (_) async => [_local],
          crearLocal: ({required nombre, direccion, required ubicacion}) =>
              throw UnimplementedError(),
          loadHistorial: (_) async => [],
          loadVigentes: (_, {ubicacion}) async => [],
          cargarPrecio: ({
            required ean,
            required localId,
            required precio,
            required ubicacion,
          }) => throw UnimplementedError(),
        ),
      );
      expect(find.text('No pudimos conectar con el servidor'), findsOneWidget);
      expect(
        find.text('El servidor respondió 403 (alta_cerrada)'),
        findsOneWidget,
      );
    });

    testWidgets('si el código no sirve, lo dice y deja probar otro', (
      tester,
    ) async {
      var intentos = 0;
      await abrir(
        tester,
        deps: AppDeps(
          guardarInvitacion: (_) async => intentos++,
          loadMe: () async {
            if (intentos < 2) {
              throw InvitacionRequerida(rechazada: intentos > 0);
            }
            return const Me(id: 'u1', alias: 'anon-abc123', karma: 0);
          },
          loadProducto: (_) async => _aceite,
          obtenerUbicacion: () async => _aca,
          abrirAjustes: () async {},
          loadLocalesCerca: (_) async => [_local],
          crearLocal: ({required nombre, direccion, required ubicacion}) =>
              throw UnimplementedError(),
          loadHistorial: (_) async => [],
          loadVigentes: (_, {ubicacion}) async => [],
          cargarPrecio: ({
            required ean,
            required localId,
            required precio,
            required ubicacion,
          }) => throw UnimplementedError(),
        ),
      );
      expect(find.textContaining('Ese código no sirve'), findsNothing);

      await tester.enterText(find.byType(TextField), '111111');
      await tester.tap(find.text('Entrar'));
      await tester.pumpAndSettle();
      expect(find.textContaining('Ese código no sirve'), findsOneWidget);
      expect(find.text('Escanear código'), findsNothing);

      await tester.enterText(find.byType(TextField), '222222');
      await tester.tap(find.text('Entrar'));
      await tester.pumpAndSettle();
      expect(find.text('anon-abc123'), findsOneWidget);
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
          obtenerUbicacion: () async => _aca,
          abrirAjustes: () async {},
          loadLocalesCerca: (_) async => [_local],
          crearLocal: ({required nombre, direccion, required ubicacion}) =>
              throw UnimplementedError(),
          loadHistorial: (_) async => [],
          loadVigentes: (_, {ubicacion}) async => [],
          cargarPrecio: ({
            required ean,
            required localId,
            required precio,
            required ubicacion,
          }) => throw UnimplementedError(),
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

  group('historial de precios', () {
    PrecioHistorial precio(String valor, String local, DateTime fecha) =>
        PrecioHistorial(
          id: valor,
          localNombre: local,
          precio: valor,
          fecha: fecha,
        );

    testWidgets('sin precios, lo dice', (tester) async {
      await abrir(tester);
      await _buscar(tester, _aceite.ean);
      expect(find.text('Historial de precios'), findsOneWidget);
      expect(
        find.text('Todavía nadie cargó un precio de este producto.'),
        findsOneWidget, // el historial; en «precios por local» dice «cerca tuyo»
      );
    });

    testWidgets('lista precio, local y fecha, formateados', (tester) async {
      final ahora = DateTime.now();
      backend.precios.addAll([
        precio(
          '1000.00',
          'Local viejo',
          ahora.subtract(const Duration(days: 3)),
        ),
        precio('1234.50', 'Local del admin', ahora),
      ]);
      await abrir(tester);
      await _buscar(tester, _aceite.ean);

      expect(find.text(r'$ 1.234,50'), findsOneWidget);
      expect(find.text(r'$ 1.000,00'), findsOneWidget);
      expect(find.textContaining('Local del admin'), findsOneWidget);
      expect(find.textContaining('(hoy)'), findsOneWidget);
      expect(find.textContaining('(hace 3 días)'), findsOneWidget);
    });

    testWidgets('si falla, ofrece reintentar y se recupera', (tester) async {
      backend.errorHistorial = ApiException('Sin conexión');
      backend.precios.add(precio('500.00', 'Local del admin', DateTime.now()));
      await abrir(tester);
      await _buscar(tester, _aceite.ean);
      expect(find.text('No pudimos cargar el historial.'), findsOneWidget);
      // la ficha del producto sigue visible
      expect(find.text('Aceite de girasol'), findsOneWidget);

      await tester.tap(find.text('Reintentar'));
      await tester.pumpAndSettle();
      expect(find.text(r'$ 500,00'), findsOneWidget);
    });

    testWidgets('el precio recién cargado aparece al volver a la ficha', (
      tester,
    ) async {
      await abrir(tester);
      await _irAlFormulario(tester);
      await _enviarPrecio(tester, '850');
      // Volver atrás desde el éxito (en vez de "Listo") deja la ficha.
      await tester.pageBack();
      await tester.pumpAndSettle();
      // en «precios por local» y en el historial
      expect(find.text(r'$ 850,00'), findsNWidgets(2));
    });
  });

  group('locales', () {
    final dentro = find.byType(AlertDialog);

    testWidgets('busca los locales cerca de donde estás', (tester) async {
      await abrir(tester);
      await _irAlFormulario(tester);
      expect(backend.ubicacionPedida?.lat, _aca.lat);
      expect(backend.ubicacionPedida?.lng, _aca.lng);
    });

    testWidgets('sin locales cerca: lo crea y carga el precio ahí', (
      tester,
    ) async {
      backend.cerca.clear();
      await abrir(tester);
      await _irAlFormulario(tester);
      expect(find.text('No hay locales registrados cerca de acá.'), findsOne);

      await tester.tap(find.text('Crear local aquí'));
      await tester.pumpAndSettle();
      await tester.enterText(
        find.descendant(of: dentro, matching: find.byType(TextField)).first,
        '  Kiosco Don Pepe ',
      );
      await tester.tap(find.text('Crear local'));
      await tester.pumpAndSettle();

      expect(backend.creados.single.nombre, 'Kiosco Don Pepe');
      expect(backend.creados.single.ubicacion.lat, _aca.lat);
      expect(
        find.textContaining('en Kiosco Don Pepe (sin verificar)'),
        findsOne,
      );

      await _enviarPrecio(tester, '300');
      expect(backend.cargas.single.localId, 'nuevo1');
    });

    testWidgets('con varios locales, se puede cambiar el elegido', (
      tester,
    ) async {
      backend.cerca.add(
        const Local(id: 'l2', nombre: 'Otro local', distanciaM: 40),
      );
      await abrir(tester);
      await _irAlFormulario(tester);
      expect(find.text('en Local del admin'), findsOneWidget);

      await tester.tap(find.text('Cambiar'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Otro local'));
      await tester.pumpAndSettle();
      expect(find.text('en Otro local'), findsOneWidget);

      await _enviarPrecio(tester, '300');
      expect(backend.cargas.single.localId, 'l2');
    });

    testWidgets('desde «cambiar» también se puede crear uno nuevo', (
      tester,
    ) async {
      await abrir(tester);
      await _irAlFormulario(tester);

      await tester.tap(find.text('Cambiar'));
      await tester.pumpAndSettle();
      await tester.tap(find.textContaining('crear uno nuevo aquí'));
      await tester.pumpAndSettle();
      await tester.enterText(
        find.descendant(of: dentro, matching: find.byType(TextField)).first,
        'Vecino',
      );
      await tester.tap(find.text('Crear local'));
      await tester.pumpAndSettle();

      expect(find.textContaining('en Vecino'), findsOneWidget);
    });

    testWidgets('nombre vacío: no crea y marca el error', (tester) async {
      backend.cerca.clear();
      await abrir(tester);
      await _irAlFormulario(tester);
      await tester.tap(find.text('Crear local aquí'));
      await tester.pumpAndSettle();

      await tester.tap(find.text('Crear local'));
      await tester.pumpAndSettle();

      expect(find.text('Ingresá el nombre del local'), findsOneWidget);
      expect(backend.creados, isEmpty);
    });

    testWidgets('duplicado: lo explica y deja corregir', (tester) async {
      backend.cerca.clear();
      backend.errorAlCrear = ApiException('Error 409', statusCode: 409);
      await abrir(tester);
      await _irAlFormulario(tester);
      await tester.tap(find.text('Crear local aquí'));
      await tester.pumpAndSettle();
      await tester.enterText(
        find.descendant(of: dentro, matching: find.byType(TextField)).first,
        'Kiosco',
      );

      await tester.tap(find.text('Crear local'));
      await tester.pumpAndSettle();
      expect(find.textContaining('Ya hay un local con ese nombre'), findsOne);

      await tester.tap(find.text('Crear local')); // reintenta con otro nombre
      await tester.pumpAndSettle();
      expect(find.textContaining('en Kiosco'), findsOneWidget);
    });

    testWidgets('sin permiso para crear locales, lo avisa', (tester) async {
      backend.cerca.clear();
      backend.errorAlCrear = ApiException('Error 403', statusCode: 403);
      await abrir(tester);
      await _irAlFormulario(tester);
      await tester.tap(find.text('Crear local aquí'));
      await tester.pumpAndSettle();
      await tester.enterText(
        find.descendant(of: dentro, matching: find.byType(TextField)).first,
        'Kiosco',
      );
      await tester.tap(find.text('Crear local'));
      await tester.pumpAndSettle();

      expect(find.textContaining('solo un administrador'), findsOneWidget);
    });

    testWidgets('permiso de ubicación negado: lo explica y reintenta', (
      tester,
    ) async {
      await abrir(tester);
      await _buscar(tester, _aceite.ean);
      backend.errorUbicacion = const UbicacionException(
        UbicacionError.permisoDenegado,
      );
      await tester.tap(_botonCargar);
      await tester.pumpAndSettle();
      expect(find.textContaining('Necesitamos tu ubicación'), findsOneWidget);

      await tester.tap(find.text('Reintentar'));
      await tester.pumpAndSettle();
      expect(find.text('en Local del admin'), findsOneWidget);
    });

    testWidgets('permiso negado para siempre: manda a los ajustes', (
      tester,
    ) async {
      await abrir(tester);
      await _buscar(tester, _aceite.ean);
      backend.errorUbicacion = const UbicacionException(
        UbicacionError.permisoDenegadoParaSiempre,
      );
      await tester.tap(_botonCargar);
      await tester.pumpAndSettle();

      await tester.tap(find.text('Abrir ajustes'));
      expect(backend.ajustesAbiertos, 1);
    });

    testWidgets('GPS apagado: pide prenderlo', (tester) async {
      await abrir(tester);
      await _buscar(tester, _aceite.ean);
      backend.errorUbicacion = const UbicacionException(
        UbicacionError.servicioApagado,
      );
      await tester.tap(_botonCargar);
      await tester.pumpAndSettle();
      expect(find.textContaining('Prendé la ubicación'), findsOneWidget);
    });
  });

  group('precios por local (mapa y lista)', () {
    PrecioVigente vigente(
      String local,
      String precio, {
      String frescura = 'verde',
      int dias = 0,
      bool vencido = false,
      double lat = -34.60,
      double lng = -58.38,
      bool verificado = true,
    }) => PrecioVigente(
      localId: local,
      localNombre: 'Local $local',
      localVerificado: verificado,
      lat: lat,
      lng: lng,
      precio: precio,
      fecha: DateTime.now().subtract(Duration(days: dias)),
      edadDias: dias,
      frescura: frescura,
      vencido: vencido,
    );

    Finder filaDe(String local) => find.byWidgetPredicate(
      (w) =>
          w is ListTile &&
          w.subtitle is Text &&
          ((w.subtitle! as Text).textSpan?.toPlainText() ?? '').contains(
            'Local $local',
          ),
    );
    ListTile fila(WidgetTester tester, String local) =>
        tester.widget<ListTile>(filaDe(local));

    /// Pantalla alta, para que la lista construya todas las filas.
    void pantallaAlta(WidgetTester tester) {
      tester.view.physicalSize = const Size(900, 2400);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.reset);
    }

    testWidgets('sin precios: lo dice y no muestra el mapa', (tester) async {
      await abrir(tester);
      await _buscar(tester, _aceite.ean);
      expect(find.text('Precios por local'), findsOneWidget);
      expect(find.byType(FlutterMap), findsNothing);
      expect(find.text('No hay precios cargados cerca tuyo.'), findsOneWidget);
      expect(
        find.text('Todavía nadie cargó un precio de este producto.'),
        findsOneWidget, // el historial
      );
    });

    testWidgets('sin precios cerca: ofrece ver los de otros lugares', (
      tester,
    ) async {
      pantallaAlta(tester);
      backend
        ..soloLejos = true
        ..vigentes.add(vigente('lejos', '900.00'));
      await abrir(tester);
      await _buscar(tester, _aceite.ean);
      expect(find.byType(FlutterMap), findsNothing);
      expect(find.text('No hay precios cargados cerca tuyo.'), findsOneWidget);

      await tester.tap(find.text('Ver precios en otros lugares'));
      await tester.pumpAndSettle();

      expect(find.byType(FlutterMap), findsOneWidget);
      expect(find.text(r'$ 900,00'), findsWidgets);
      expect(backend.ubicacionesVigentes.last, isNull);
    });

    testWidgets('pide los precios con la ubicación del usuario', (
      tester,
    ) async {
      backend.vigentes.add(vigente('a', '900.00'));
      await abrir(tester);
      await _buscar(tester, _aceite.ean);
      expect(backend.ubicacionesVigentes.single, isNotNull);
    });

    testWidgets('sin ubicación (GPS apagado) muestra todos igual', (
      tester,
    ) async {
      backend
        ..errorUbicacion = const UbicacionException(
          UbicacionError.servicioApagado,
        )
        ..vigentes.add(vigente('a', '900.00'));
      await abrir(tester);
      await _buscar(tester, _aceite.ean);
      expect(find.text(r'$ 900,00'), findsWidgets);
      expect(backend.ubicacionesVigentes.single, isNull);
    });

    testWidgets('con más de 5 locales muestra 5 y «Mostrar más»', (
      tester,
    ) async {
      pantallaAlta(tester);
      for (var i = 1; i <= 8; i++) {
        backend.vigentes.add(vigente('l$i', '${1000 + i}.00'));
      }
      await abrir(tester);
      await _buscar(tester, _aceite.ean);
      expect(find.byType(ListTile), findsNWidgets(5));
      expect(find.text('Mostrar más (3)'), findsOneWidget);

      await tester.ensureVisible(find.text('Mostrar más (3)'));
      await tester.tap(find.text('Mostrar más (3)'));
      await tester.pumpAndSettle();

      expect(find.byType(ListTile), findsNWidgets(8));
      expect(find.text('Mostrar menos'), findsOneWidget);
    });

    testWidgets('se puede ordenar por frescura', (tester) async {
      pantallaAlta(tester);
      backend.vigentes.addAll([
        vigente('barato', '100.00', dias: 20, frescura: 'amarillo'),
        vigente('fresco', '300.00', dias: 1),
      ]);
      await abrir(tester);
      await _buscar(tester, _aceite.ean);
      final antes = tester.getTopLeft(filaDe('barato')).dy;
      expect(antes, lessThan(tester.getTopLeft(filaDe('fresco')).dy));

      await tester.tap(find.text('Frescura'));
      await tester.pumpAndSettle();

      expect(
        tester.getTopLeft(filaDe('fresco')).dy,
        lessThan(tester.getTopLeft(filaDe('barato')).dy),
      );
      // «Más barato» sigue en el más barato aunque cambie el orden.
      expect(find.text('Más barato'), findsOneWidget);
    });

    testWidgets('lista del más barato al más caro, con frescura', (
      tester,
    ) async {
      pantallaAlta(tester);
      backend.vigentes.addAll([
        vigente('a', '900.00'),
        vigente('b', '1000.00', frescura: 'amarillo', dias: 15, lat: -34.62),
        vigente('c', '1200.00', frescura: 'rojo', dias: 25, lat: -34.58),
        vigente('d', '800.00', dias: 60, vencido: true, verificado: false),
      ]);
      await abrir(tester);
      await _buscar(tester, _aceite.ean);

      expect(find.byType(FlutterMap), findsOneWidget);
      expect(find.text(r'$ 900,00'), findsOneWidget);
      expect(find.text('Más barato'), findsOneWidget);
      expect(find.textContaining('Fresco'), findsOneWidget);
      expect(find.textContaining('Reciente'), findsOneWidget);
      expect(find.textContaining('Viejo'), findsOneWidget);
      expect(find.textContaining('Vencido'), findsOneWidget);
      expect(find.textContaining('(sin verificar)'), findsOneWidget);
      expect(find.textContaining('hace 15 días'), findsOneWidget);
      // un cartel con el precio por local, en el mapa
      expect(find.byKey(const ValueKey('cartel-a')), findsOneWidget);
      expect(find.byKey(const ValueKey('cartel-b')), findsOneWidget);
    });

    testWidgets('tocar un precio de la lista lo resalta en el mapa', (
      tester,
    ) async {
      backend.vigentes.addAll([
        vigente('a', '900.00'),
        vigente('b', '1000.00', lat: -34.62),
      ]);
      await abrir(tester);
      await _buscar(tester, _aceite.ean);
      expect(fila(tester, 'b').selected, isFalse);
      expect(find.byKey(const ValueKey('cartel-b-elegido')), findsNothing);

      await tester.tap(filaDe('b'));
      await tester.pumpAndSettle();

      expect(fila(tester, 'b').selected, isTrue);
      expect(fila(tester, 'a').selected, isFalse);
      // el mapa se centró en el elegido (el otro local queda fuera de cuadro)
      expect(find.byKey(const ValueKey('cartel-b-elegido')), findsOneWidget);
    });

    testWidgets('tocar un cartel del mapa resalta su precio en la lista', (
      tester,
    ) async {
      backend.vigentes.addAll([
        vigente('a', '900.00'),
        vigente('b', '1000.00', lat: -34.62),
      ]);
      await abrir(tester);
      await _buscar(tester, _aceite.ean);

      await tester.tap(find.byKey(const ValueKey('cartel-b')));
      await tester.pumpAndSettle();

      expect(fila(tester, 'b').selected, isTrue);
      expect(find.byKey(const ValueKey('cartel-b-elegido')), findsOneWidget);
    });

    testWidgets('si fallan los precios, ofrece reintentar y se recupera', (
      tester,
    ) async {
      backend.errorVigentes = ApiException('Sin conexión');
      backend.vigentes.add(vigente('a', '900.00'));
      await abrir(tester);
      await _buscar(tester, _aceite.ean);
      expect(find.text('No pudimos cargar los precios.'), findsOneWidget);
      expect(find.text('Aceite de girasol'), findsOneWidget);

      await tester.tap(find.text('Reintentar'));
      await tester.pumpAndSettle();
      expect(find.byType(FlutterMap), findsOneWidget);
    });

    testWidgets('un precio recién cargado aparece en el mapa y la lista', (
      tester,
    ) async {
      await abrir(tester);
      await _irAlFormulario(tester);
      await _enviarPrecio(tester, '850');
      await tester.pageBack();
      await tester.pumpAndSettle();

      expect(find.byType(FlutterMap), findsOneWidget);
      expect(find.text(r'$ 850,00'), findsWidgets);
      expect(find.byKey(const ValueKey('cartel-l1')), findsOneWidget);
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

    testWidgets('si llegó al tope de cargas, lo explica', (tester) async {
      backend.errorAlCargar = ApiException(
        'Error 429',
        statusCode: 429,
        detail: {'codigo': 'limite_cargas'},
      );
      await abrir(tester);
      await _irAlFormulario(tester);

      await _enviarPrecio(tester, '500');
      expect(
        find.text(
          'Cargaste muchos precios seguidos. Esperá un rato y probá de nuevo.',
        ),
        findsOneWidget,
      );
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

    testWidgets('lejos del local: dice a cuántos metros y no suma karma', (
      tester,
    ) async {
      backend.errorAlCargar = ApiException(
        'Error 403',
        statusCode: 403,
        detail: {'codigo': 'fuera_de_rango', 'distancia_m': 480},
      );
      await abrir(tester);
      await _irAlFormulario(tester);

      await _enviarPrecio(tester, '500');

      expect(find.textContaining('Estás a 480 m de'), findsOneWidget);
      expect(find.text('¡Precio cargado!'), findsNothing);
      expect(backend.karma, 0);
    });

    testWidgets('GPS impreciso: pide esperar y reintentar', (tester) async {
      backend.errorAlCargar = ApiException(
        'Error 403',
        statusCode: 403,
        detail: {'codigo': 'precision_baja'},
      );
      await abrir(tester);
      await _irAlFormulario(tester);

      await _enviarPrecio(tester, '500');

      expect(find.textContaining('muy imprecisa'), findsOneWidget);
    });

    testWidgets('manda la ubicación actual con la carga', (tester) async {
      await abrir(tester);
      await _irAlFormulario(tester);

      await _enviarPrecio(tester, '500');

      expect(backend.cargas.single.ubicacion.lat, _aca.lat);
    });
  });
}
