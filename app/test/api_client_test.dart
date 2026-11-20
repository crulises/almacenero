import 'package:almacenero/data/api_client.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

http.Response respuesta403(String codigo) =>
    http.Response('{"detail":{"codigo":"$codigo"}}', 403);

void main() {
  group('onCuentaBaja', () {
    test('avisa cuando CUALQUIER pedido recibe 403 cuenta_baja', () async {
      var avisos = 0;
      final api = ApiClient(
        baseUrl: 'http://x',
        httpClient: MockClient((_) async => respuesta403('cuenta_baja')),
        onCuentaBaja: () => avisos++,
      );
      await expectLater(api.get('/me'), throwsA(isA<ApiException>()));
      await expectLater(api.post('/precios'), throwsA(isA<ApiException>()));
      expect(avisos, 2);
    });

    test('no avisa con otros errores (restringido, 401, red)', () async {
      var avisos = 0;
      for (final respuesta in [
        respuesta403('cuenta_restringida'),
        http.Response('{}', 401),
        http.Response('{}', 500),
      ]) {
        final api = ApiClient(
          baseUrl: 'http://x',
          httpClient: MockClient((_) async => respuesta),
          onCuentaBaja: () => avisos++,
        );
        await expectLater(api.get('/me'), throwsA(isA<ApiException>()));
      }
      expect(avisos, 0);
    });
  });
}
