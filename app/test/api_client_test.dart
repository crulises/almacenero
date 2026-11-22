import 'dart:async';

import 'package:almacenero/data/api_client.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

http.Response respuesta403(String codigo) =>
    http.Response('{"detail":{"codigo":"$codigo"}}', 403);

void main() {
  idDispositivoTests();
  reintentosTests();
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

void idDispositivoTests() {
  group('idDispositivo', () {
    Future<Map<String, String>> headersDe(
      String path,
      Future<String?> Function()? id,
    ) async {
      late Map<String, String> vistos;
      final api = ApiClient(
        baseUrl: 'http://x',
        httpClient: MockClient((r) async {
          vistos = r.headers;
          return http.Response('{}', 200);
        }),
        idDispositivo: id,
      );
      await api.get(path);
      return vistos;
    }

    test('se manda en /auth/* y en /me, y no en el resto', () async {
      expect(
        (await headersDe('/me', () async => 'abc12345'))['X-Device-Id'],
        'abc12345',
      );
      expect(
        (await headersDe(
          '/auth/refresh',
          () async => 'abc12345',
        ))['X-Device-Id'],
        'abc12345',
      );
      expect(
        (await headersDe(
          '/precios',
          () async => 'abc12345',
        )).containsKey('X-Device-Id'),
        isFalse,
      );
    });

    test('si no se puede leer, la app anda igual sin el header', () async {
      expect(
        (await headersDe(
          '/auth/refresh',
          () async => throw Exception('x'),
        )).containsKey('X-Device-Id'),
        isFalse,
      );
      expect(
        (await headersDe('/auth/refresh', null)).containsKey('X-Device-Id'),
        isFalse,
      );
    });
  });
}

void reintentosTests() {
  ApiClient cliente(
    Future<http.Response> Function(http.Request) h, {
    Duration timeout = const Duration(milliseconds: 30),
    Duration avisarTras = const Duration(milliseconds: 10),
  }) => ApiClient(
    baseUrl: 'http://x',
    httpClient: MockClient(h),
    timeout: timeout,
    esperaBase: const Duration(milliseconds: 1),
    avisarTras: avisarTras,
  );

  group('timeout y reintentos', () {
    test('un GET que no responde se reintenta y termina bien', () async {
      var llamadas = 0;
      final api = cliente((_) async {
        if (++llamadas == 1) {
          return Completer<http.Response>().future; // nunca responde
        }
        return http.Response('{"ok":true}', 200);
      });
      expect(await api.get('/me'), {'ok': true});
      expect(llamadas, 2);
    });

    test('reintenta de forma acotada y distingue timeout de sin red', () async {
      var llamadas = 0;
      final lento = cliente((_) {
        llamadas++;
        return Completer<http.Response>().future;
      });
      await expectLater(
        lento.get('/me'),
        throwsA(
          isA<ApiException>()
              .having((e) => e.esTimeout, 'esTimeout', isTrue)
              .having((e) => e.statusCode, 'statusCode', isNull),
        ),
      );
      expect(llamadas, 3); // 1 intento + 2 reintentos, no más

      final sinRed = cliente((_) async => throw http.ClientException('x'));
      await expectLater(
        sinRed.get('/me'),
        throwsA(isA<ApiException>().having((e) => e.esTimeout, 't', isFalse)),
      );
    });

    test('un POST común NO se reintenta (se podría duplicar)', () async {
      var llamadas = 0;
      final api = cliente((_) {
        llamadas++;
        return Completer<http.Response>().future;
      });
      await expectLater(api.post('/precios'), throwsA(isA<ApiException>()));
      expect(llamadas, 1);
    });

    test('/auth/refresh sí se reintenta', () async {
      var llamadas = 0;
      final api = cliente((_) async {
        if (++llamadas < 3) throw http.ClientException('x');
        return http.Response('{}', 200);
      });
      await api.post('/auth/refresh');
      expect(llamadas, 3);
    });

    test('una respuesta de error del servidor no se reintenta', () async {
      var llamadas = 0;
      final api = cliente((_) async {
        llamadas++;
        return http.Response('{}', 500);
      });
      await expectLater(api.get('/me'), throwsA(isA<ApiException>()));
      expect(llamadas, 1);
    });

    test('avisa «despertando» mientras tarda y lo apaga al terminar', () async {
      final vistos = <bool>[];
      var llamadas = 0;
      final api = cliente((_) async {
        if (++llamadas == 1) {
          await Future<void>.delayed(const Duration(milliseconds: 40));
          throw http.ClientException('x');
        }
        return http.Response('{}', 200);
      }, timeout: const Duration(seconds: 1));
      api.despertando.addListener(() => vistos.add(api.despertando.value));
      await api.get('/me');
      expect(vistos, [true, false]);
    });

    test('un pedido rápido no dispara el aviso', () async {
      final api = cliente(
        (_) async => http.Response('{}', 200),
        avisarTras: const Duration(seconds: 5),
      );
      var avisos = 0;
      api.despertando.addListener(() => avisos++);
      await api.get('/me');
      expect(avisos, 0);
    });
  });

  group('ApiException.explicacion', () {
    test('usa el mensaje de la regla, los campos y la guía del backend', () {
      final e = ApiException(
        'Error 422',
        statusCode: 422,
        detail: {
          'codigo': 'dato_invalido',
          'mensaje': 'Algún dato no cumple.',
          'como_resolver': 'Revisá los datos.',
          'campos': [
            {'campo': 'tamano_valor', 'problema': 'tiene que ser mayor a 0'},
          ],
        },
      );
      expect(
        e.explicacion,
        'Algún dato no cumple. (tamano_valor tiene que ser mayor a 0) '
        'Revisá los datos.',
      );
    });

    test('con un detail de texto o sin detail', () {
      expect(
        ApiException('Error 400', detail: 'EAN inválido').explicacion,
        'EAN inválido',
      );
      expect(ApiException('Error 500').explicacion, 'Error 500');
    });
  });
}
