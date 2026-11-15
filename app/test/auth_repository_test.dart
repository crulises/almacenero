import 'dart:convert';

import 'package:almacenero/data/api_client.dart';
import 'package:almacenero/data/auth_repository.dart';
import 'package:almacenero/data/session.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

class MemoryStore implements SessionStore {
  Session? session;

  @override
  Future<Session?> read() async => session;

  @override
  Future<void> write(Session s) async => session = s;

  @override
  Future<void> clear() async => session = null;
}

void main() {
  late DateTime now;
  late MemoryStore store;
  late List<String> llamadas;
  late Map<String, int> estados;

  AuthRepository build() {
    final client = MockClient((request) async {
      llamadas.add(request.url.path);
      final status = estados[request.url.path] ?? 200;
      if (status != 200) return http.Response('{}', status);
      final n = llamadas.length;
      return http.Response(
        jsonEncode({
          'access_token': 'acc$n',
          'refresh_token': 'ref$n',
          'expires_in': 3600,
        }),
        200,
      );
    });
    return AuthRepository(
      api: ApiClient(baseUrl: 'http://x', httpClient: client),
      store: store,
      now: () => now,
    );
  }

  setUp(() {
    now = DateTime(2026, 1, 1, 12);
    store = MemoryStore();
    llamadas = [];
    estados = {};
  });

  test('primer arranque: crea sesión anónima y la guarda', () async {
    final token = await build().accessToken();
    expect(token, 'acc1');
    expect(llamadas, ['/v1/auth/anonymous']);
    expect(store.session?.refreshToken, 'ref1');
  });

  test('con sesión vigente no llama al backend', () async {
    final auth = build();
    await auth.accessToken();
    llamadas.clear();
    expect(await auth.accessToken(), 'acc1');
    expect(llamadas, isEmpty);
  });

  test('sesión vencida: renueva con el refresh token', () async {
    final auth = build();
    await auth.accessToken();
    now = now.add(const Duration(hours: 2));
    expect(await auth.accessToken(), 'acc2');
    expect(llamadas.last, '/v1/auth/refresh');
  });

  test('refresh rechazado: arranca una sesión anónima nueva', () async {
    final auth = build();
    await auth.accessToken();
    now = now.add(const Duration(hours: 2));
    estados['/v1/auth/refresh'] = 401;
    expect(await auth.accessToken(), 'acc3');
    expect(llamadas.last, '/v1/auth/anonymous');
  });

  test('llamadas simultáneas crean un solo usuario', () async {
    final auth = build();
    final tokens = await Future.wait([auth.accessToken(), auth.accessToken()]);
    expect(tokens, ['acc1', 'acc1']);
    expect(llamadas, ['/v1/auth/anonymous']);
  });

  test('error de red no borra la sesión', () async {
    final auth = build();
    await auth.accessToken();
    now = now.add(const Duration(hours: 2));
    estados['/v1/auth/refresh'] = 500;
    await expectLater(auth.accessToken(), throwsA(isA<ApiException>()));
    expect(store.session, isNotNull);
  });
}
