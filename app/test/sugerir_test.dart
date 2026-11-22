import 'dart:convert';

import 'package:almacenero/app_deps.dart';
import 'package:almacenero/data/api_client.dart';
import 'package:almacenero/data/auth_repository.dart';
import 'package:almacenero/data/authed_api.dart';
import 'package:almacenero/data/location_service.dart';
import 'package:almacenero/data/product_repository.dart';
import 'package:almacenero/data/session.dart';
import 'package:almacenero/data/sugerencia_repository.dart';
import 'package:almacenero/data/user_repository.dart';
import 'package:almacenero/ui/product_screen.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:material_ui/material_ui.dart';

class _MemoryStore implements SessionStore {
  Session? session;

  @override
  Future<Session?> read() async => session;

  @override
  Future<void> write(Session s) async => session = s;

  @override
  Future<void> clear() async => session = null;
}

const _aceite = Producto(
  id: 'p1',
  ean: '7790070411112',
  nombre: 'Aceite Girasol',
  marca: 'Cocinero',
  tamanoValor: 900,
  tamanoUnidad: 'ml',
  presentacion: 'botella',
);

class _Backend {
  _Backend({this.rol = 'moderador', this.producto = _aceite});

  final String rol;
  final Producto? producto;
  final enviadas =
      <({String ean, Map<String, Object?> cambios, String? motivo})>[];

  AppDeps deps() => AppDeps(
    loadMe: () async => Me(id: 'u', alias: 'a', karma: 0, rol: rol),
    loadProducto: (ean) async {
      final p = producto;
      if (p == null) throw ApiException('no', statusCode: 404);
      return p;
    },
    obtenerUbicacion: () async =>
        const Ubicacion(lat: 0, lng: 0, precisionM: 5),
    abrirAjustes: () async {},
    loadLocalesCerca: (_) async => [],
    crearLocal: ({required nombre, direccion, required ubicacion}) async =>
        throw UnimplementedError(),
    cargarPrecio: ({
      required ean,
      required localId,
      required precio,
      required ubicacion,
    }) async => throw UnimplementedError(),
    loadHistorial: (_) async => [],
    loadVigentes: (_, {ubicacion}) async => [],
    sugerir: ({required ean, required cambios, motivo}) async {
      enviadas.add((ean: ean, cambios: cambios, motivo: motivo));
      return const SugerenciaEnviada(
        id: 's',
        tipo: 'correccion',
        estado: 'pendiente',
      );
    },
    loadEstandares: () async => const [
      Estandar(
        id: 'nombre',
        titulo: 'El nombre describe el producto',
        regla: 'La marca va en su campo.',
        mal: 'Aceite Cocinero 900 ml',
        bien: 'Aceite Girasol',
      ),
    ],
  );
}

Future<void> _abrir(
  WidgetTester tester,
  _Backend b, {
  String ean = '7790070411112',
}) async {
  // Pantalla alta (se ve el formulario entero) y árbol limpio entre aperturas.
  tester.view.physicalSize = const Size(800, 3000);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(const SizedBox());
  await tester.pumpWidget(
    MaterialApp(
      home: ProductScreen(ean: ean, deps: b.deps()),
    ),
  );
  await tester.pumpAndSettle();
}

void main() {
  group('modelo', () {
    test('detalle: marca · tamaño · presentación · pack', () {
      expect(_aceite.detalle, 'Cocinero · 900 ml · botella');
      const pack = Producto(
        id: 'x',
        ean: '1',
        nombre: 'Gaseosa Naranja',
        marca: 'Fanta',
        tamanoValor: 6.6,
        tamanoUnidad: 'l',
        packCantidad: 24,
        presentacion: 'lata',
      );
      expect(pack.detalle, 'Fanta · 6.6 l · lata · pack de 24');
      expect(
        const Producto(id: 'x', ean: '1', nombre: 'Algo').detalle,
        isEmpty,
      );
    });

    test('fromJson lee pack y presentación; el rol define quién sugiere', () {
      final p = Producto.fromJson({
        'id': 'p',
        'ean': '1',
        'nombre': 'N',
        'pack_cantidad': 6,
        'presentacion': 'caja',
      });
      expect((p.packCantidad, p.presentacion), (6, 'caja'));
      Me me(String? rol) => Me.fromJson({
        'id': 'u',
        'alias': 'a',
        'karma': 0,
        ...?(rol == null ? null : {'rol': rol}),
      });
      expect(me('moderador').puedeSugerir, isTrue);
      expect(me('admin').puedeSugerir, isTrue);
      expect(me('usuario').puedeSugerir, isFalse);
      expect(me(null).puedeSugerir, isFalse); // backend viejo: sin rol
    });
  });

  test(
    'SugerenciaRepository.enviar manda el cuerpo y estandares() parsea',
    () async {
      final pedidos = <http.Request>[];
      final client = MockClient((r) async {
        pedidos.add(r);
        if (r.url.path.startsWith('/v1/auth/')) {
          return http.Response(
            jsonEncode({
              'access_token': 'a',
              'refresh_token': 'r',
              'expires_in': 3600,
            }),
            200,
          );
        }
        if (r.url.path == '/v1/ayuda/estandares') {
          return http.Response(
            jsonEncode([
              {
                'id': 'nombre',
                'titulo': 'T',
                'regla': 'R',
                'mal': 'M',
                'bien': 'B',
              },
            ]),
            200,
          );
        }
        return http.Response(
          jsonEncode({'id': 's1', 'tipo': 'alta', 'estado': 'pendiente'}),
          201,
        );
      });
      final api = ApiClient(baseUrl: 'http://x', httpClient: client);
      final repo = SugerenciaRepository(
        api: AuthedApi(
          api: api,
          auth: AuthRepository(api: api, store: _MemoryStore()),
        ),
      );

      final s = await repo.enviar(
        ean: '7790000000062',
        cambios: {'nombre': 'Fanta', 'marca': null},
        motivo: '  lo vi en el envase ',
      );

      final post = pedidos.last;
      expect(post.method, 'POST');
      expect(post.url.path, '/v1/catalogo/sugerencias');
      expect(jsonDecode(post.body), {
        'ean': '7790000000062',
        'nombre': 'Fanta',
        'marca': null,
        'motivo': 'lo vi en el envase',
      });
      expect(s.tipo, 'alta');
      expect((await repo.estandares()).single.titulo, 'T');
    },
  );

  group('pantalla de producto', () {
    testWidgets(
      'muestra el nombre limpio y debajo marca · tamaño · presentación',
      (tester) async {
        await _abrir(tester, _Backend());
        expect(find.text('Aceite Girasol'), findsOneWidget);
        expect(find.text('Cocinero · 900 ml · botella'), findsOneWidget);
      },
    );

    testWidgets('un usuario común no ve el menú de sugerir', (tester) async {
      await _abrir(tester, _Backend(rol: 'usuario'));
      expect(find.byType(PopupMenuButton<String>), findsNothing);
    });

    testWidgets(
      'el moderador sugiere desde el menú ⋮: solo se manda lo que cambió',
      (tester) async {
        final b = _Backend();
        await _abrir(tester, b);
        await tester.tap(find.byType(PopupMenuButton<String>));
        await tester.pumpAndSettle();
        await tester.tap(find.text('Sugerir corrección'));
        await tester.pumpAndSettle();

        // sin tocar nada no se puede enviar
        await tester.tap(find.text('Enviar sugerencia', skipOffstage: false));
        await tester.pumpAndSettle();
        expect(find.text('No cambiaste nada.'), findsOneWidget);
        expect(b.enviadas, isEmpty);

        await tester.enterText(
          find.widgetWithText(TextField, 'Marca'),
          'Cañuelas',
        );
        await tester.enterText(find.widgetWithText(TextField, 'Pack de'), '6');
        await tester.enterText(
          find.widgetWithText(TextField, 'Por qué (opcional)'),
          'está en el envase',
        );
        await tester.ensureVisible(
          find.text('Enviar sugerencia', skipOffstage: false),
        );
        await tester.tap(find.text('Enviar sugerencia', skipOffstage: false));
        await tester.pumpAndSettle();

        expect(b.enviadas.single.ean, '7790070411112');
        expect(b.enviadas.single.cambios, {
          'marca': 'Cañuelas',
          'pack_cantidad': 6,
        });
        expect(b.enviadas.single.motivo, 'está en el envase');
        expect(
          find.text('Sugerencia enviada. Un admin la va a revisar.'),
          findsOneWidget,
        );
      },
    );

    testWidgets('tamaño y unidad van juntos', (tester) async {
      final b = _Backend(
        producto: const Producto(
          id: 'p',
          ean: '7790070411112',
          nombre: 'Aceite Girasol',
        ),
      );
      await _abrir(tester, b);
      await tester.tap(find.byType(PopupMenuButton<String>));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Sugerir corrección'));
      await tester.pumpAndSettle();
      await tester.enterText(find.widgetWithText(TextField, 'Tamaño'), '900');
      await tester.ensureVisible(
        find.text('Enviar sugerencia', skipOffstage: false),
      );
      await tester.tap(find.text('Enviar sugerencia', skipOffstage: false));
      await tester.pumpAndSettle();
      expect(
        find.text('El tamaño y la unidad van juntos (o los dos vacíos).'),
        findsOneWidget,
      );
      expect(b.enviadas, isEmpty);
    });

    testWidgets(
      'producto no encontrado: el moderador da de alta, el usuario no',
      (tester) async {
        await _abrir(tester, _Backend(rol: 'usuario', producto: null));
        expect(
          find.text('Este producto todavía no está en el catálogo.'),
          findsOneWidget,
        );
        expect(find.text('Dar de alta este producto'), findsNothing);

        final b = _Backend(producto: null);
        await _abrir(tester, b);
        await tester.tap(find.text('Dar de alta este producto'));
        await tester.pumpAndSettle();
        expect(
          find.text('Dar de alta'),
          findsOneWidget,
        ); // título del formulario

        await tester.ensureVisible(
          find.text('Enviar sugerencia', skipOffstage: false),
        );
        await tester.tap(find.text('Enviar sugerencia', skipOffstage: false));
        await tester.pumpAndSettle();
        expect(
          find.text('Para dar de alta un producto hace falta el nombre.'),
          findsOneWidget,
        );

        await tester.enterText(
          find.widgetWithText(TextField, 'Nombre'),
          'Fanta Naranja',
        );
        await tester.ensureVisible(
          find.text('Enviar sugerencia', skipOffstage: false),
        );
        await tester.tap(find.text('Enviar sugerencia', skipOffstage: false));
        await tester.pumpAndSettle();
        expect(b.enviadas.single.cambios, {'nombre': 'Fanta Naranja'});
      },
    );

    testWidgets('el formulario abre la ayuda de estándares', (tester) async {
      await _abrir(tester, _Backend());
      await tester.tap(find.byType(PopupMenuButton<String>));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Sugerir corrección'));
      await tester.pumpAndSettle();
      await tester.ensureVisible(
        find.text('Ver estándares de carga', skipOffstage: false),
      );
      await tester.tap(
        find.text('Ver estándares de carga', skipOffstage: false),
      );
      await tester.pumpAndSettle();
      expect(find.text('El nombre describe el producto'), findsOneWidget);
      expect(find.textContaining('nunca cambia tu karma'), findsOneWidget);
    });
  });
}
