import 'package:almacenero/app_deps.dart';
import 'package:almacenero/data/api_client.dart';
import 'package:almacenero/data/app_info.dart';
import 'package:almacenero/data/auth_repository.dart';
import 'package:almacenero/data/local_repository.dart';
import 'package:almacenero/data/location_service.dart';
import 'package:almacenero/data/price_repository.dart';
import 'package:almacenero/data/product_repository.dart';
import 'package:almacenero/data/recientes.dart';
import 'package:almacenero/data/user_repository.dart';
import 'package:almacenero/main.dart';
import 'package:almacenero/ui/acerca_screen.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:material_ui/material_ui.dart';
import 'package:shared_preferences/shared_preferences.dart';

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

/// La cámara de mentira: «lee» el código al abrirse y vuelve con él (o cancelado).
class _EscanerFalso extends StatefulWidget {
  const _EscanerFalso(this.ean);

  final String? ean;

  @override
  State<_EscanerFalso> createState() => _EscanerFalsoState();
}

class _EscanerFalsoState extends State<_EscanerFalso> {
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

/// Backend de mentira: el karma sube con cada precio cargado, como en el real.
class _Backend {
  int karma = 0;
  Escalon escalon = Escalon.normal;
  final cargas =
      <({String ean, String localId, String precio, Ubicacion ubicacion})>[];
  Object? errorAlCargar;
  Object? errorHistorial;
  Object? errorMe;
  final enlaces = <Uri>[];
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

  /// Lo que devuelve `referencia: true` (radio ampliado) cuando se pide con ubicación.
  final referencia = <PrecioVigente>[];

  /// Sin red: todo lo que va al servidor falla (lo guardado en el celular sigue).
  bool sinRed = false;
  final pedidosReferencia = <String>[];

  /// Lo que «escanea» la cámara de mentira (EAN); `null` = se cancela.
  String? escaneo;

  AppDeps deps({Future<Producto> Function(String)? loadProducto}) {
    final store = RecientesStore();
    final servicio = RecientesService(
      loadProducto: (ean) => _producto(loadProducto, ean),
      loadVigentes: _vigentes,
      obtenerUbicacion: () async => _ubicar(),
    );
    return _deps(loadProducto, store, servicio);
  }

  Future<Producto> _producto(
    Future<Producto> Function(String)? loadProducto,
    String ean,
  ) async {
    if (sinRed) throw ApiException('Sin conexión');
    return (loadProducto ?? (_) async => _aceite)(ean);
  }

  Ubicacion _ubicar() {
    if (sinRed) throw ApiException('Sin conexión');
    return _aca;
  }

  Future<List<PrecioVigente>> _vigentes(
    String ean, {
    Ubicacion? ubicacion,
    bool referencia = false,
  }) async {
    if (sinRed) throw ApiException('Sin conexión');
    ubicacionesVigentes.add(ubicacion);
    if (referencia) {
      pedidosReferencia.add(ean);
      return List.of(this.referencia);
    }
    if (soloLejos && ubicacion != null) return [];
    final error = errorVigentes;
    if (error != null) {
      errorVigentes = null; // falla una sola vez
      throw error;
    }
    return List.of(vigentes);
  }

  AppDeps _deps(
    Future<Producto> Function(String)? loadProducto,
    RecientesStore store,
    RecientesService servicio,
  ) => AppDeps(
    leerRecientes: store.leer,
    guardarReciente: store.registrar,
    refrescarReciente: (r) async {
      final nuevo = await servicio.refrescar(r);
      if (nuevo != null) await store.registrar(nuevo, moverAlTope: false);
      return nuevo;
    },
    pantallaEscaneo: () => _EscanerFalso(escaneo),
    abrirEnlace: (url) async => enlaces.add(url),
    loadMe: () async {
      if (sinRed) throw ApiException('Sin conexión');
      final error = errorMe;
      if (error != null) throw error;
      return Me(id: 'u1', alias: 'anon-abc123', karma: karma, escalon: escalon);
    },
    loadProducto: (ean) => _producto(loadProducto, ean),
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
    loadVigentes: _vigentes,
    loadHistorial: (_) async {
      if (sinRed) throw ApiException('Sin conexión');
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
          final primero =
              precios.length == 1; // recién agregado: no había ninguno
          karma++;
          return PrecioCargado(
            precioId: 'pr${cargas.length}',
            karma: karma,
            primerPrecio: primero,
          );
        },
  );
}

Future<void> _buscar(WidgetTester tester, String ean) async {
  await tester.enterText(find.byType(TextField), ean);
  await tester.tap(find.byTooltip('Buscar'));
  await tester.pumpAndSettle();
}

/// El botón del formulario de carga.
final _botonCargar = find.widgetWithText(FilledButton, 'Cargar precio');

/// El de la ficha del producto (dice «Cargar precio» o «Sé el primero en cargarlo»).
final _botonFicha = find.widgetWithIcon(FilledButton, Icons.sell);

Future<void> _irAlFormulario(WidgetTester tester) async {
  await _buscar(tester, _aceite.ean);
  await tester.tap(_botonFicha);
  await tester.pumpAndSettle();
}

Future<void> _enviarPrecio(WidgetTester tester, String precio) async {
  await tester.enterText(find.byType(TextField), precio);
  await tester.tap(_botonCargar);
  await tester.pumpAndSettle();
}

void main() {
  late _Backend backend;

  testWidgets('«Despertando servidor…» aparece y desaparece con el aviso', (
    tester,
  ) async {
    final despertando = ValueNotifier(false);
    await tester.pumpWidget(
      MaterialApp(
        home: AvisoDespertando(
          despertando: despertando,
          child: const Scaffold(body: Text('contenido')),
        ),
      ),
    );
    expect(find.text('Despertando servidor…'), findsNothing);
    despertando.value = true;
    await tester.pump();
    expect(find.text('Despertando servidor…'), findsOneWidget);
    expect(find.text('contenido'), findsOneWidget);
    despertando.value = false;
    await tester.pump();
    expect(find.text('Despertando servidor…'), findsNothing);
  });

  setUp(() {
    SharedPreferences.setMockInitialValues({});
    backend = _Backend();
  });

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
          loadVigentes: (_, {ubicacion, referencia = false}) async => [],
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
          loadVigentes: (_, {ubicacion, referencia = false}) async => [],
          cargarPrecio: ({
            required ean,
            required localId,
            required precio,
            required ubicacion,
          }) => throw UnimplementedError(),
        ),
      );
      // La tarjeta ya no está en el inicio: se muda a «Acerca de».
      expect(find.text('Versión: 0.0.7 (abc1234)'), findsNothing);
      await tester.tap(find.byTooltip('Acerca de'));
      await tester.pumpAndSettle();
      expect(find.text('Versión: 0.0.7 (abc1234)'), findsOneWidget);
      expect(find.text('Servidor: http://192.168.1.5:8000'), findsOneWidget);
      expect(find.text('Estado: responde (35 ms)'), findsOneWidget);
      expect(find.text('IP del celular: 192.168.1.42 (wlan0)'), findsOneWidget);
    });

    testWidgets(
      '«Acerca de» lista las fuentes con licencia y abre sus enlaces',
      (tester) async {
        // Pantalla alta: así la lista (perezosa) construye todas las tarjetas.
        tester.view.physicalSize = const Size(800, 4000);
        tester.view.devicePixelRatio = 1;
        addTearDown(tester.view.reset);
        await abrir(tester);
        await tester.tap(find.byTooltip('Acerca de'));
        await tester.pumpAndSettle();
        expect(find.text('Acerca de'), findsOneWidget); // título de la barra
        expect(find.text('Almacenero'), findsOneWidget);
        expect(find.text('Versión dev'), findsOneWidget);

        for (final f in fuentesDatos) {
          expect(find.text(f.nombre), findsWidgets);
          expect(find.text('Licencia: ${f.licencia}'), findsOneWidget);
          expect(find.text(f.texto), findsOneWidget);
        }
        expect(
          find.textContaining('© colaboradores de OpenStreetMap'),
          findsWidgets,
        );
        expect(
          find.textContaining('Creative Commons Atribución 4.0'),
          findsOneWidget,
        );

        await tester.tap(find.text('CC BY 4.0'));
        await tester.pump();
        expect(backend.enlaces, [
          Uri.parse('https://creativecommons.org/licenses/by/4.0/deed.es'),
        ]);
      },
    );

    testWidgets('«Acerca de» abre las licencias de las librerías', (
      tester,
    ) async {
      await abrir(tester);
      await tester.tap(find.byTooltip('Acerca de'));
      await tester.pumpAndSettle();
      await tester.scrollUntilVisible(
        find.text('Licencias de librerías'),
        200,
        scrollable: find.byType(Scrollable).first,
      );
      await tester.tap(find.text('Licencias de librerías'));
      await tester.pumpAndSettle();
      expect(find.byType(LicensePage), findsOneWidget);
    });

    testWidgets('distingue «el servidor tardó» de «sin red»', (tester) async {
      backend.errorMe = ApiException(
        'El servidor tardó demasiado en responder (20 s)',
        esTimeout: true,
      );
      await abrir(tester);
      expect(find.text('No pudimos conectar con el servidor'), findsOneWidget);
      expect(
        find.text('El servidor tardó demasiado en responder (20 s)'),
        findsOneWidget,
      );

      backend.errorMe = ApiException('Sin conexión con el servidor: sin ruta');
      await tester.tap(find.text('Reintentar'));
      await tester.pumpAndSettle();
      expect(
        find.text('Sin conexión con el servidor: sin ruta'),
        findsOneWidget,
      );
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
          loadVigentes: (_, {ubicacion, referencia = false}) async => [],
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
          loadVigentes: (_, {ubicacion, referencia = false}) async => [],
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
          loadVigentes: (_, {ubicacion, referencia = false}) async => [],
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

  group('moderación', () {
    testWidgets('karma normal: sin avisos', (tester) async {
      await abrir(tester);
      expect(find.byKey(const Key('aviso-moderacion')), findsNothing);
    });

    testWidgets('con aviso: lo explica sin castigar y sigue usando todo', (
      tester,
    ) async {
      backend.karma = -6;
      backend.escalon = Escalon.aviso;
      await abrir(tester);
      expect(find.byKey(const Key('aviso-moderacion')), findsOneWidget);
      expect(find.text('Tu karma está en -6.'), findsOneWidget);
      expect(find.textContaining('llega a -15'), findsOneWidget);
      expect(find.text('Escanear código'), findsOneWidget); // sigue todo
    });

    testWidgets('restringido: dice que solo puede consultar', (tester) async {
      backend.karma = -20;
      backend.escalon = Escalon.restringido;
      await abrir(tester);
      expect(find.text('Por ahora solo podés consultar.'), findsOneWidget);
      expect(find.textContaining('Tu karma está en -20'), findsOneWidget);
      expect(find.text('Escanear código'), findsOneWidget); // consultar sí
    });

    testWidgets('restringido: «Cargar precio» apagado y con el motivo', (
      tester,
    ) async {
      backend.karma = -20;
      backend.escalon = Escalon.restringido;
      await abrir(tester);
      await _buscar(tester, '7790070411112');
      final boton = tester.widget<FilledButton>(_botonFicha);
      expect(boton.onPressed, isNull);
      expect(find.text('Por ahora solo podés consultar.'), findsOneWidget);
    });

    testWidgets('con aviso: «Cargar precio» sigue activo', (tester) async {
      backend.karma = -6;
      backend.escalon = Escalon.aviso;
      await abrir(tester);
      await _buscar(tester, '7790070411112');
      final boton = tester.widget<FilledButton>(_botonFicha);
      expect(boton.onPressed, isNotNull);
    });

    testWidgets('sin tocar nada: la app consulta sola y se entera de la baja', (
      tester,
    ) async {
      final baja = ValueNotifier<bool>(false);
      var consultas = 0;
      await abrir(
        tester,
        deps: AppDeps(
          cuentaBaja: baja,
          verificarCada: const Duration(seconds: 30),
          loadMe: () async {
            consultas++;
            // A partir de la 3.ª consulta el admin ya dio de baja la cuenta.
            if (consultas >= 3) {
              baja.value = true; // lo que hace el cliente HTTP ante el 403
              throw ApiException(
                'Error 403',
                statusCode: 403,
                detail: {'codigo': 'cuenta_baja'},
              );
            }
            return const Me(
              id: 'u1',
              alias: 'anon-abc123',
              karma: 0,
              escalon: Escalon.normal,
            );
          },
          loadProducto: (_) async => _aceite,
          obtenerUbicacion: () async => _aca,
          abrirAjustes: () async {},
          loadLocalesCerca: (_) async => [_local],
          crearLocal: ({required nombre, direccion, required ubicacion}) =>
              throw UnimplementedError(),
          loadHistorial: (_) async => [],
          loadVigentes: (_, {ubicacion, referencia = false}) async => [],
          cargarPrecio: ({
            required ean,
            required localId,
            required precio,
            required ubicacion,
          }) => throw UnimplementedError(),
        ),
      );
      expect(find.byKey(const Key('cuenta-baja')), findsNothing);
      await tester.pump(const Duration(seconds: 30));
      await tester.pump(const Duration(seconds: 30));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('cuenta-baja')), findsOneWidget);
    });

    testWidgets('la baja a mitad de uso lleva a la pantalla de baja', (
      tester,
    ) async {
      final baja = ValueNotifier<bool>(false);
      await abrir(
        tester,
        deps: AppDeps(
          cuentaBaja: baja,
          loadMe: backend.deps().loadMe,
          loadProducto: (_) async => _aceite,
          obtenerUbicacion: () async => _aca,
          abrirAjustes: () async {},
          loadLocalesCerca: (_) async => [_local],
          crearLocal: ({required nombre, direccion, required ubicacion}) =>
              throw UnimplementedError(),
          loadHistorial: (_) async => [],
          loadVigentes: (_, {ubicacion, referencia = false}) async => [],
          cargarPrecio: ({
            required ean,
            required localId,
            required precio,
            required ubicacion,
          }) => throw UnimplementedError(),
        ),
      );
      await _buscar(tester, '7790070411112');
      expect(find.text('Aceite de girasol'), findsOneWidget);
      baja.value = true; // el backend avisó en cualquier pedido
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('cuenta-baja')), findsOneWidget);
      expect(find.text('Aceite de girasol'), findsNothing);
    });

    testWidgets('restringido: al cargar un precio, el error se explica', (
      tester,
    ) async {
      backend.errorAlCargar = ApiException(
        'Error 403',
        statusCode: 403,
        detail: {'codigo': 'cuenta_restringida'},
      );
      await abrir(tester);
      await _irAlFormulario(tester);
      await _enviarPrecio(tester, '500');
      expect(find.textContaining('solo podés consultar'), findsOneWidget);
      expect(backend.cargas, isEmpty);
    });

    testWidgets('restringido: al crear un local, el error se explica', (
      tester,
    ) async {
      backend.cerca.clear();
      backend.errorAlCrear = ApiException(
        'Error 403',
        statusCode: 403,
        detail: {'codigo': 'cuenta_restringida'},
      );
      await abrir(tester);
      await _irAlFormulario(tester);
      await tester.tap(find.text('Crear local aquí'));
      await tester.pumpAndSettle();
      await tester.enterText(
        find
            .descendant(
              of: find.byType(AlertDialog),
              matching: find.byType(TextField),
            )
            .first,
        'Kiosco',
      );
      await tester.tap(find.text('Crear local'));
      await tester.pumpAndSettle();
      expect(find.textContaining('solo podés consultar'), findsOneWidget);
    });

    testWidgets('cuenta de baja: pantalla final, sin escanear ni reintentar', (
      tester,
    ) async {
      await abrir(
        tester,
        deps: AppDeps(
          loadMe: () async => throw ApiException(
            'Error 403',
            statusCode: 403,
            detail: {'codigo': 'cuenta_baja'},
          ),
          loadProducto: (_) async => _aceite,
          obtenerUbicacion: () async => _aca,
          abrirAjustes: () async {},
          loadLocalesCerca: (_) async => [_local],
          crearLocal: ({required nombre, direccion, required ubicacion}) =>
              throw UnimplementedError(),
          loadHistorial: (_) async => [],
          loadVigentes: (_, {ubicacion, referencia = false}) async => [],
          cargarPrecio: ({
            required ean,
            required localId,
            required precio,
            required ubicacion,
          }) => throw UnimplementedError(),
        ),
      );
      expect(find.byKey(const Key('cuenta-baja')), findsOneWidget);
      expect(find.textContaining('dada de baja'), findsWidgets);
      expect(find.text('Escanear código'), findsNothing);
      expect(find.text('Reintentar'), findsNothing);
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
      expect(_botonFicha, findsNothing);
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
      // Al guardar se vuelve solo a la ficha.
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
      expect(
        find.text('No hay locales registrados cerca de acá.'),
        findsOneWidget,
      );

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
      expect(
        find.textContaining('Ya hay un local con ese nombre'),
        findsOneWidget,
      );

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
      await tester.tap(_botonFicha);
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
      await tester.tap(_botonFicha);
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
      await tester.tap(_botonFicha);
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
      // La atribución de OSM es obligatoria (ODbL) y tiene que estar a la vista.
      expect(find.text('© OpenStreetMap contributors'), findsOneWidget);
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
      // Con precios vigentes siempre hay historial (si no, el botón pasa a «Sé el primero»).
      backend.precios.add(
        PrecioHistorial(
          id: 'h',
          localNombre: 'Local a',
          precio: '900.00',
          fecha: DateTime.now(),
        ),
      );
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
      // Se vuelve a la ficha del producto, con el aviso; no hay pantalla de éxito.
      expect(find.text('Precio de góndola'), findsNothing);
      expect(find.text('Aceite de girasol'), findsOneWidget);
      expect(find.textContaining('Precio cargado · karma 1'), findsOneWidget);
      expect(find.text('¡Precio cargado!'), findsNothing);

      await tester.pageBack(); // de la ficha al inicio
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
      expect(find.textContaining('Precio cargado'), findsNothing);
      expect(backend.karma, 0);

      await tester.tap(_botonCargar); // el precio sigue escrito
      await tester.pumpAndSettle();
      expect(find.textContaining('Precio cargado · karma 1'), findsOneWidget);
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
      expect(find.textContaining('Precio cargado'), findsNothing);
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

  PrecioVigente vigenteA(
    String local,
    String precio, {
    double? dist,
    int edad = 0,
  }) => PrecioVigente(
    localId: local,
    localNombre: 'Local $local',
    localVerificado: true,
    lat: -34.6,
    lng: -58.4,
    precio: precio,
    fecha: DateTime.now().subtract(Duration(days: edad)),
    edadDias: edad,
    frescura: 'verde',
    vencido: false,
    distanciaM: dist,
  );

  Producto otro(String ean, String nombre) =>
      Producto(id: 'x$ean', ean: ean, nombre: nombre);

  Future<Producto> productos(String ean) async =>
      ean == _aceite.ean ? _aceite : otro(ean, 'Fideos $ean');

  group('flujo de carga', () {
    testWidgets('sin precios en ningún lado: invita a ser el primero', (
      tester,
    ) async {
      await abrir(tester);
      await _buscar(tester, _aceite.ean);
      expect(find.text('Sé el primero en cargarlo'), findsOneWidget);
      expect(find.text('Cargar precio'), findsNothing);
    });

    testWidgets('con precios el botón vuelve a ser «Cargar precio»', (
      tester,
    ) async {
      backend.precios.add(
        PrecioHistorial(
          id: 'x',
          localNombre: 'Local del admin',
          precio: '10.00',
          fecha: DateTime.now(),
        ),
      );
      await abrir(tester);
      await _buscar(tester, _aceite.ean);
      expect(find.text('Cargar precio'), findsOneWidget);
      expect(find.text('Sé el primero en cargarlo'), findsNothing);
    });

    testWidgets('el primero en cargarlo lo ve en el aviso', (tester) async {
      await abrir(tester);
      await _irAlFormulario(tester);
      await _enviarPrecio(tester, '500');
      expect(find.textContaining('Fuiste el primero'), findsOneWidget);
      expect(find.textContaining('karma 1'), findsOneWidget);
    });

    testWidgets('si no se guarda nada, atrás vuelve a la ficha sin aviso', (
      tester,
    ) async {
      await abrir(tester);
      await _irAlFormulario(tester);
      await tester.pageBack();
      await tester.pumpAndSettle();
      expect(find.text('Aceite de girasol'), findsOneWidget);
      expect(find.textContaining('Precio cargado'), findsNothing);
    });

    testWidgets(
      '«Escanear otro» abre la ficha nueva y atrás vuelve al inicio',
      (tester) async {
        backend.escaneo = '7790000000017';
        await abrir(tester, deps: backend.deps(loadProducto: productos));
        await _buscar(tester, _aceite.ean);

        await tester.tap(find.text('Escanear otro'));
        await tester.pumpAndSettle();
        expect(find.text('Fideos 7790000000017'), findsOneWidget);

        await tester
            .pageBack(); // un solo atrás: la ficha anterior se reemplazó
        await tester.pumpAndSettle();
        expect(find.text('Almacenero'), findsOneWidget);
      },
    );

    testWidgets('«Escanear otro» cancelado deja la ficha donde estaba', (
      tester,
    ) async {
      backend.escaneo = null;
      await abrir(tester);
      await _buscar(tester, _aceite.ean);
      await tester.tap(find.text('Escanear otro'));
      await tester.pumpAndSettle();
      expect(find.text('Aceite de girasol'), findsOneWidget);
    });

    testWidgets('quien escanea de a uno no tiene un toque de más', (
      tester,
    ) async {
      await abrir(tester);
      await _buscar(tester, _aceite.ean);
      await tester.pageBack(); // una sola vuelta lleva al inicio
      await tester.pumpAndSettle();
      expect(find.text('Escanear código'), findsOneWidget);
    });
  });

  group('recientes', () {
    testWidgets('lo consultado queda bajo el campo: qué, dónde y a cuánto', (
      tester,
    ) async {
      backend.vigentes.add(vigenteA('l1', '900.00', dist: 350));
      await abrir(tester);
      expect(find.text('Recientes'), findsNothing); // nada que mostrar todavía
      await _buscar(tester, _aceite.ean);
      await tester.pageBack();
      await tester.pumpAndSettle();

      expect(find.text('Recientes'), findsOneWidget);
      expect(find.text('Aceite de girasol'), findsOneWidget);
      expect(find.textContaining(r'$ 900,00'), findsOneWidget);
      expect(find.textContaining('Local l1'), findsOneWidget);
      expect(find.textContaining('350 m'), findsOneWidget);
      expect(find.textContaining('Referencia'), findsNothing);
    });

    testWidgets('sin repetir y con tope de 4: lo último arriba', (
      tester,
    ) async {
      await abrir(tester, deps: backend.deps(loadProducto: productos));
      for (final e in [
        '70000001',
        '70000002',
        '70000003',
        '70000004',
        '70000005',
      ]) {
        await _buscar(tester, e);
        await tester.pageBack();
        await tester.pumpAndSettle();
      }
      await _buscar(tester, '70000003'); // reconsultar lo sube
      await tester.pageBack();
      await tester.pumpAndSettle();

      final nombres = [
        for (final t in tester.widgetList<Text>(find.textContaining('Fideos')))
          t.data,
      ];
      expect(nombres, [
        'Fideos 70000003',
        'Fideos 70000005',
        'Fideos 70000004',
        'Fideos 70000002',
      ]);
    });

    testWidgets('tocar uno abre su ficha', (tester) async {
      await abrir(tester);
      await _buscar(tester, _aceite.ean);
      await tester.pageBack();
      await tester.pumpAndSettle();
      await tester.tap(find.text('Aceite de girasol'));
      await tester.pumpAndSettle();
      expect(find.text('EAN ${_aceite.ean}'), findsOneWidget);
    });

    testWidgets(
      'nada en la zona: usa un precio lejano marcado como referencia',
      (tester) async {
        backend.referencia.add(vigenteA('lejos', '800.00', dist: 120000));
        backend.soloLejos = true; // en la zona no hay nada
        await abrir(tester);
        await _buscar(tester, _aceite.ean);
        await tester.pageBack();
        await tester.pumpAndSettle();

        expect(find.textContaining('Referencia'), findsOneWidget);
        expect(find.textContaining('120 km'), findsOneWidget);
        expect(find.textContaining(r'$ 800,00'), findsOneWidget);
        expect(backend.pedidosReferencia, isNotEmpty);
      },
    );

    testWidgets('sin ningún precio: dice que no hay y no deja la fila vacía', (
      tester,
    ) async {
      await abrir(tester);
      await _buscar(tester, _aceite.ean);
      await tester.pageBack();
      await tester.pumpAndSettle();
      expect(find.textContaining('Sin precios'), findsOneWidget);
    });

    testWidgets('sin red se ven igual, sin errores ni esperas', (tester) async {
      backend.vigentes.add(vigenteA('l1', '900.00', dist: 350));
      await abrir(tester);
      await _buscar(tester, _aceite.ean);
      await tester.pageBack();
      await tester.pumpAndSettle();

      // Se corta la red y se reabre la app: lo guardado en el celular sigue ahí.
      backend.sinRed = true;
      await tester.pumpWidget(const SizedBox());
      await abrir(tester);

      expect(find.text('Aceite de girasol'), findsOneWidget);
      expect(find.textContaining(r'$ 900,00'), findsOneWidget);
      expect(find.textContaining('350 m'), findsOneWidget);
      expect(tester.takeException(), isNull);
    });

    testWidgets('con red se refresca el precio guardado', (tester) async {
      backend.vigentes.add(vigenteA('l1', '900.00', dist: 350));
      await abrir(tester);
      await _buscar(tester, _aceite.ean);
      await tester.pageBack();
      await tester.pumpAndSettle();

      backend.vigentes
        ..clear()
        ..add(vigenteA('l1', '950.00', dist: 350));
      await tester.pumpWidget(const SizedBox());
      await abrir(tester);

      expect(find.textContaining(r'$ 950,00'), findsOneWidget);
      expect(find.textContaining(r'$ 900,00'), findsNothing);
    });
  });
}
