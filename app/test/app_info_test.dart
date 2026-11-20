import 'package:almacenero/data/api_client.dart';
import 'package:almacenero/data/app_info.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

ApiClient _api(Future<http.Response> Function(http.Request) handler) =>
    ApiClient(baseUrl: 'http://x', httpClient: MockClient(handler));

void main() {
  group('probarServidor', () {
    test('si /health responde, lo dice con la demora', () async {
      final api = _api((r) async {
        expect(r.url.path, '/v1/health');
        return http.Response('{"status":"ok"}', 200);
      });
      expect(await probarServidor(api), matches(r'^responde \(\d+ ms\)$'));
    });

    test('si el servidor devuelve error, dice cuál', () async {
      final api = _api((_) async => http.Response('{}', 503));
      expect(await probarServidor(api), 'respondió error 503');
    });

    test('si no hay red, lo distingue de un error del servidor', () async {
      final api = _api((_) async => throw http.ClientException('sin ruta'));
      expect(await probarServidor(api), startsWith('sin conexión'));
    });
  });

  test('sin --dart-define la versión es «dev»', () {
    expect(BuildInfo.actual.version, 'dev');
  });
}
