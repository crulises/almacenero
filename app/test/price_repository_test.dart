import 'dart:convert';

import 'package:almacenero/data/api_client.dart';
import 'package:almacenero/data/auth_repository.dart';
import 'package:almacenero/data/authed_api.dart';
import 'package:almacenero/data/local_repository.dart';
import 'package:almacenero/data/price_repository.dart';
import 'package:almacenero/data/session.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

class _MemoryStore implements SessionStore {
  Session? session;

  @override
  Future<Session?> read() async => session;

  @override
  Future<void> write(Session s) async => session = s;

  @override
  Future<void> clear() async => session = null;
}

void main() {
  late List<http.Request> pedidos;
  late int Function(http.Request) estado;
  late Object cuerpo;

  AuthedApi build() {
    final client = MockClient((request) async {
      pedidos.add(request);
      if (request.url.path.startsWith('/v1/auth/')) {
        return http.Response(
          jsonEncode({
            'access_token': 'acc${pedidos.length}',
            'refresh_token': 'ref',
            'expires_in': 3600,
          }),
          200,
        );
      }
      final status = estado(request);
      return http.Response(status < 300 ? jsonEncode(cuerpo) : '{}', status);
    });
    final api = ApiClient(baseUrl: 'http://x', httpClient: client);
    return AuthedApi(
      api: api,
      auth: AuthRepository(api: api, store: _MemoryStore()),
    );
  }

  setUp(() {
    pedidos = [];
    estado = (_) => 201;
    cuerpo = {'precio_id': 'pr1', 'karma': 4};
  });

  group('PriceRepository', () {
    test('cargar: manda el JSON con el token y devuelve el karma', () async {
      final r = await PriceRepository(api: build())
          .cargar(ean: '7790070411112', localId: 'l1', precio: '1234.50');

      final post = pedidos.last;
      expect(post.method, 'POST');
      expect(post.url.path, '/v1/precios');
      expect(post.headers['Authorization'], startsWith('Bearer acc'));
      expect(jsonDecode(post.body), {
        'ean': '7790070411112',
        'local_id': 'l1',
        // string, no número: el precio nunca pasa por double
        'precio': '1234.50',
      });
      expect(r.precioId, 'pr1');
      expect(r.karma, 4);
    });

    test('clasifica los errores de carga', () async {
      Future<Object> falla(int status) async {
        estado = (_) => status;
        return PriceRepository(api: build())
            .cargar(ean: '1', localId: 'l', precio: '1.00')
            .then<Object>((_) => 'ok', onError: (Object e) => e);
      }

      expect(clasificarErrorCarga(await falla(404)), CargaError.noEncontrado);
      expect(clasificarErrorCarga(await falla(422)), CargaError.precioInvalido);
      expect(clasificarErrorCarga(await falla(500)), CargaError.otro);
      expect(clasificarErrorCarga(Exception('x')), CargaError.otro);
    });

    test('un 401 renueva la sesión y reintenta una vez', () async {
      var intentos = 0;
      estado = (_) => ++intentos == 1 ? 401 : 201;

      final r = await PriceRepository(api: build())
          .cargar(ean: '7790070411112', localId: 'l1', precio: '10.00');

      expect(r.karma, 4);
      expect(intentos, 2);
    });
  });

  group('LocalRepository', () {
    test('listar: parsea la lista JSON de locales', () async {
      estado = (_) => 200;
      cuerpo = [
        {
          'id': 'l1',
          'nombre': 'Local del admin',
          'direccion': 'Calle 1',
          'lat': -34.6,
          'lng': -58.4,
        },
        {'id': 'l2', 'nombre': 'Otro', 'direccion': null},
      ];

      final locales = await LocalRepository(api: build()).listar();

      expect(pedidos.last.url.path, '/v1/locales');
      expect(locales.map((l) => l.nombre), ['Local del admin', 'Otro']);
      expect(locales.first.direccion, 'Calle 1');
      expect(locales.last.direccion, isNull);
    });
  });
}
