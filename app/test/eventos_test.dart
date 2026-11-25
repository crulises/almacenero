import 'dart:convert';

import 'package:almacenero/app_deps.dart';
import 'package:almacenero/data/api_client.dart';
import 'package:almacenero/data/auth_repository.dart';
import 'package:almacenero/data/authed_api.dart';
import 'package:almacenero/data/cola_eventos.dart';
import 'package:almacenero/data/location_service.dart';
import 'package:almacenero/data/product_repository.dart';
import 'package:almacenero/data/session.dart';
import 'package:almacenero/data/user_repository.dart';
import 'package:almacenero/ui/product_screen.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:material_ui/material_ui.dart';

const _aceite = Producto(
  id: 'p1',
  ean: '7790070411112',
  nombre: 'Aceite de girasol',
);

AppDeps _deps({
  required Future<Producto> Function(String) loadProducto,
  required List<(String, Map<String, Object?>)> eventos,
}) => AppDeps(
  registrarEvento: (tipo, [datos = const {}]) => eventos.add((tipo, datos)),
  loadMe: () async =>
      const Me(id: 'u1', alias: 'a', karma: 0, escalon: Escalon.normal),
  loadProducto: loadProducto,
  obtenerUbicacion: () async =>
      const Ubicacion(lat: -34.6, lng: -58.4, precisionM: 10),
  abrirAjustes: () async {},
  loadLocalesCerca: (_) async => const [],
  crearLocal: ({required nombre, direccion, required ubicacion}) async =>
      throw UnimplementedError(),
  cargarPrecio: ({
    required ean,
    required localId,
    required precio,
    required ubicacion,
  }) async => throw UnimplementedError(),
  loadHistorial: (_) async => const [],
  loadVigentes: (_, {ubicacion, referencia = false}) async => const [],
);

Future<void> _abrir(
  WidgetTester tester,
  AppDeps deps, {
  String? via = 'camara',
}) async {
  await tester.pumpWidget(
    MaterialApp(
      home: ProductScreen(ean: '7790070411112', deps: deps, via: via),
    ),
  );
  await tester.pumpAndSettle();
}

class _Almacen implements SessionStore {
  Session? s;
  @override
  Future<Session?> read() async => s;
  @override
  Future<void> write(Session x) async => s = x;
  @override
  Future<void> clear() async => s = null;
}

void main() {
  group('ProductScreen anota producto.escaneado', () {
    testWidgets('producto encontrado → encontrado: true', (tester) async {
      final eventos = <(String, Map<String, Object?>)>[];
      await _abrir(
        tester,
        _deps(loadProducto: (_) async => _aceite, eventos: eventos),
      );
      expect(eventos.map((e) => e.$1), ['producto.escaneado']);
      expect(eventos.single.$2, {
        'ean': '7790070411112',
        'encontrado': true,
        'via': 'camara',
      });
    });

    testWidgets('404 → encontrado: false', (tester) async {
      final eventos = <(String, Map<String, Object?>)>[];
      await _abrir(
        tester,
        _deps(
          loadProducto: (_) async => throw ApiException('no', statusCode: 404),
          eventos: eventos,
        ),
      );
      expect(eventos.map((e) => e.$1), ['producto.escaneado']);
      expect(eventos.single.$2, {
        'ean': '7790070411112',
        'encontrado': false,
        'via': 'camara',
      });
    });

    testWidgets('sin red: no anota nada y la pantalla sigue sin romperse', (
      tester,
    ) async {
      final eventos = <(String, Map<String, Object?>)>[];
      await _abrir(
        tester,
        _deps(
          loadProducto: (_) async => throw ApiException('Sin conexión'),
          eventos: eventos,
        ),
      );
      expect(eventos, isEmpty);
      expect(tester.takeException(), isNull);
    });

    testWidgets('si se tipeó el código, también anota, con via: manual', (
      tester,
    ) async {
      final eventos = <(String, Map<String, Object?>)>[];
      await _abrir(
        tester,
        _deps(
          loadProducto: (_) async => throw ApiException('no', statusCode: 404),
          eventos: eventos,
        ),
        via: 'manual',
      );
      expect(eventos.single.$2, {
        'ean': '7790070411112',
        'encontrado': false,
        'via': 'manual',
      });
    });

    testWidgets('sin via (otra entrada a la ficha) no anota', (tester) async {
      final eventos = <(String, Map<String, Object?>)>[];
      await _abrir(
        tester,
        _deps(loadProducto: (_) async => _aceite, eventos: eventos),
        via: null,
      );
      expect(eventos, isEmpty);
    });
  });

  group('EventosRepository', () {
    test('manda el lote a POST /v1/eventos con el token y sin prender «Despertando»', () async {
      final pedidos = <http.Request>[];
      final cliente = MockClient((r) async {
        pedidos.add(r);
        if (r.url.path.startsWith('/v1/auth/')) {
          return http.Response(
            jsonEncode({
              'access_token': 'acc',
              'refresh_token': 'ref',
              'expires_in': 3600,
            }),
            200,
          );
        }
        // Tarda más que `avisarTras`: un pedido normal prendería el aviso.
        await Future<void>.delayed(const Duration(milliseconds: 60));
        return http.Response(jsonEncode({'guardados': 1}), 201);
      });
      final api = ApiClient(
        baseUrl: 'http://x',
        httpClient: cliente,
        avisarTras: const Duration(milliseconds: 10),
      );
      final auth = AuthRepository(
        api: api,
        store: _Almacen()
          ..s = Session(
            accessToken: 'acc',
            refreshToken: 'ref',
            expiresAt: DateTime.now().add(const Duration(hours: 1)),
          ),
        invitations: _SinInvitacion(),
      );
      var aviso = false;
      api.despertando.addListener(() => aviso = aviso || api.despertando.value);
      await EventosRepository(
        api: AuthedApi(api: api, auth: auth),
      ).enviar([
        {'tipo': 'app.abierta', 'datos': {}},
      ]);
      final p = pedidos.firstWhere((r) => r.url.path == '/v1/eventos');
      expect(p.method, 'POST');
      expect(p.headers['Authorization'], 'Bearer acc');
      expect(jsonDecode(p.body), {
        'eventos': [
          {'tipo': 'app.abierta', 'datos': {}},
        ],
      });
      expect(aviso, isFalse);
    });

    test('sin red, la cola se traga el error y descarta', () async {
      final api = ApiClient(
        baseUrl: 'http://x',
        httpClient: MockClient((_) async => throw http.ClientException('off')),
      );
      final auth = AuthRepository(
        api: api,
        store: _Almacen()
          ..s = Session(
            accessToken: 'acc',
            refreshToken: 'ref',
            expiresAt: DateTime.now().add(const Duration(hours: 1)),
          ),
        invitations: _SinInvitacion(),
      );
      final cola = ColaEventos(
        enviar: EventosRepository(
          api: AuthedApi(api: api, auth: auth),
        ).enviar,
      )..registrar('app.abierta');
      await cola.vaciar();
      expect(cola.pendientes, 0);
    });
  });
}

class _SinInvitacion implements InvitationStore {
  @override
  Future<String?> read() async => null;
  @override
  Future<void> write(String c) async {}
  @override
  Future<void> clear() async {}
}
