import 'dart:convert';

import 'package:almacenero/data/api_client.dart';
import 'package:almacenero/data/auth_repository.dart';
import 'package:almacenero/data/authed_api.dart';
import 'package:almacenero/data/product_repository.dart';
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
  late Map<String, dynamic> cuerpo;

  ProductRepository build() {
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
      return http.Response(status == 200 ? jsonEncode(cuerpo) : '{}', status);
    });
    final api = ApiClient(baseUrl: 'http://x', httpClient: client);
    final auth = AuthRepository(api: api, store: _MemoryStore());
    return ProductRepository(
      api: AuthedApi(api: api, auth: auth),
    );
  }

  setUp(() {
    pedidos = [];
    estado = (_) => 200;
    cuerpo = {
      'id': 'p1',
      'ean': '7790070411112',
      'nombre': 'Aceite de girasol',
      'marca': 'Ejemplo',
      'tamano_valor': '900', // Decimal serializado como string por el backend
      'tamano_unidad': 'ml',
      'imagen_url': null,
    };
  });

  test('porEan: pide /v1/productos/{ean} con el token y parsea', () async {
    final p = await build().porEan('7790070411112');

    final get = pedidos.last;
    expect(get.url.path, '/v1/productos/7790070411112');
    expect(get.headers['Authorization'], startsWith('Bearer acc'));
    expect(p.nombre, 'Aceite de girasol');
    expect(p.tamano, '900 ml');
  });

  test('tamaño decimal y unidades', () {
    Producto con(Object? valor, String? unidad) => Producto.fromJson({
      ...cuerpo,
      'tamano_valor': valor,
      'tamano_unidad': unidad,
    });
    expect(con('1.5', 'l').tamano, '1.5 l');
    expect(con('6', 'u').tamano, '6 un.');
    expect(con(null, null).tamano, isNull);
  });

  test('404 se clasifica como no encontrado, 422 como balanza', () async {
    estado = (_) => 404;
    final e404 = await build()
        .porEan('7799999999999')
        .then<Object>((_) => 'ok', onError: (Object e) => e);
    expect(clasificarError(e404), ProductoError.noEncontrado);

    estado = (_) => 422;
    final e422 = await build()
        .porEan('2000000012345')
        .then<Object>((_) => 'ok', onError: (Object e) => e);
    expect(clasificarError(e422), ProductoError.eanDeBalanza);

    expect(clasificarError(Exception('x')), ProductoError.otro);
  });

  test('ante un 401 renueva la sesión y reintenta una vez', () async {
    var intentos = 0;
    estado = (_) => ++intentos == 1 ? 401 : 200;

    final p = await build().porEan('7790070411112');

    expect(p.ean, '7790070411112');
    expect(intentos, 2);
    expect(
      pedidos.map((r) => r.url.path),
      containsAllInOrder(['/v1/auth/anonymous', '/v1/productos/7790070411112']),
    );
  });
}
