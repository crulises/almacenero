import 'dart:convert';

import 'package:almacenero/data/api_client.dart';
import 'package:almacenero/data/auth_repository.dart';
import 'package:almacenero/data/authed_api.dart';
import 'package:almacenero/data/local_repository.dart';
import 'package:almacenero/data/location_service.dart';
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

  group('historial', () {
    test('parsea precios, locales y fechas', () async {
      estado = (_) => 200;
      cuerpo = [
        {
          'id': 'a',
          'local_id': 'l1',
          'local_nombre': 'Local del admin',
          'precio': '1234.50',
          'fecha': '2026-11-15T13:45:00.123456Z',
          'user_id': 'u',
        },
      ];

      final h = await PriceRepository(api: build()).historial('7790070411112');

      expect(pedidos.last.url.path, '/v1/productos/7790070411112/precios');
      expect(h.single.precio, '1234.50');
      expect(h.single.localNombre, 'Local del admin');
      expect(h.single.fecha.toUtc().hour, 13);
    });
  });

  group('vigentes', () {
    test('parsea precio, local, ubicación y frescura', () async {
      estado = (_) => 200;
      cuerpo = [
        {
          'local_id': 'l1',
          'local_nombre': 'Local del admin',
          'local_verificado': true,
          'lat': -34.6,
          'lng': -58.4,
          'precio': '1234.50',
          'fecha': '2026-11-15T13:45:00.123456Z',
          'edad_dias': 3,
          'frescura': 'verde',
          'vencido': false,
        },
        {
          'local_id': 'l2',
          'local_nombre': 'Otro',
          'local_verificado': false,
          'lat': -34.7,
          'lng': -58.5,
          'precio': '2000.00',
          'fecha': '2026-09-01T10:00:00Z',
          'edad_dias': 75,
          'frescura': 'rojo',
          'vencido': true,
        },
      ];

      final v = await PriceRepository(api: build()).vigentes('7790070411112');

      expect(
        pedidos.last.url.path,
        '/v1/productos/7790070411112/precios/vigentes',
      );
      expect(v.map((p) => p.precio), ['1234.50', '2000.00']);
      expect(v.first.lat, -34.6);
      expect(v.first.frescura, 'verde');
      expect(v.first.edadDias, 3);
      expect(v.last.localVerificado, isFalse);
      expect(v.last.vencido, isTrue);
    });
  });

  group('LocalRepository', () {
    const aca = Ubicacion(lat: -34.6, lng: -58.4);

    test('cerca: manda la ubicación y parsea distancia y verificado', () async {
      estado = (_) => 200;
      cuerpo = [
        {
          'id': 'l1',
          'nombre': 'Local del admin',
          'direccion': 'Calle 1',
          'lat': -34.6,
          'lng': -58.4,
          'verificado': true,
          'distancia_m': 12.5,
        },
        {
          'id': 'l2',
          'nombre': 'Otro',
          'direccion': null,
          'verificado': false,
          'distancia_m': 80,
        },
      ];

      final locales = await LocalRepository(api: build()).cerca(aca);

      expect(pedidos.last.url.path, '/v1/locales/cerca');
      expect(pedidos.last.url.queryParameters, {
        'lat': '-34.6',
        'lng': '-58.4',
      });
      expect(locales.map((l) => l.nombre), ['Local del admin', 'Otro']);
      expect(locales.first.distanciaM, 12.5);
      expect(locales.last.direccion, isNull);
      expect(locales.last.verificado, isFalse);
      expect(locales.last.distanciaM, 80);
    });

    test('crear: manda nombre y coordenadas, sin dirección vacía', () async {
      cuerpo = {
        'id': 'n1',
        'nombre': 'Kiosco',
        'direccion': null,
        'lat': -34.6,
        'lng': -58.4,
        'verificado': false,
      };

      final l = await LocalRepository(api: build())
          .crear(nombre: 'Kiosco', direccion: '', ubicacion: aca);

      final post = pedidos.last;
      expect(post.method, 'POST');
      expect(post.url.path, '/v1/locales');
      expect(jsonDecode(post.body), {
        'nombre': 'Kiosco',
        'lat': -34.6,
        'lng': -58.4,
      });
      expect(l.verificado, isFalse);
    });

    test('clasifica los errores del alta', () {
      AltaLocalError c(int status) =>
          clasificarErrorAltaLocal(ApiException('x', statusCode: status));
      expect(c(409), AltaLocalError.duplicado);
      expect(c(403), AltaLocalError.sinPermiso);
      expect(c(429), AltaLocalError.limiteDiario);
      expect(c(422), AltaLocalError.datosInvalidos);
      expect(c(500), AltaLocalError.otro);
      expect(clasificarErrorAltaLocal(Exception('x')), AltaLocalError.otro);
    });
  });

  test('clasifica los errores de ubicación', () {
    expect(
      clasificarErrorUbicacion(
        const UbicacionException(UbicacionError.servicioApagado),
      ),
      UbicacionError.servicioApagado,
    );
    expect(clasificarErrorUbicacion(Exception('x')), UbicacionError.otro);
  });
}
