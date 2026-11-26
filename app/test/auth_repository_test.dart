import 'dart:convert';

import 'package:almacenero/data/api_client.dart';
import 'package:almacenero/data/auth_repository.dart';
import 'package:almacenero/data/google_signin_service.dart';
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

class MemoryInvitations implements InvitationStore {
  String? code;

  @override
  Future<String?> read() async => code;

  @override
  Future<void> write(String c) async => code = c;

  @override
  Future<void> clear() async => code = null;
}

class GoogleDeMentira implements GoogleSignInService {
  String? idToken = 'id-google-1';
  int pedidos = 0;

  @override
  Future<String?> obtenerIdToken() async {
    pedidos++;
    return idToken;
  }
}

void main() {
  late DateTime now;
  late MemoryStore store;
  late List<String> llamadas;
  late Map<String, int> estados;
  late MemoryInvitations invitaciones;
  late List<Object?> cuerpos;
  late Map<String, Object> detalles;
  late List<String?> bearers;
  late GoogleDeMentira google;

  AuthRepository build() {
    final client = MockClient((request) async {
      llamadas.add(request.url.path);
      bearers.add(request.headers['Authorization']);
      cuerpos.add(request.body.isEmpty ? null : jsonDecode(request.body));
      final status = estados[request.url.path] ?? 200;
      if (status != 200) {
        return http.Response(
          jsonEncode({'detail': detalles[request.url.path] ?? 'x'}),
          status,
        );
      }
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
      invitations: invitaciones,
      google: google,
      now: () => now,
    );
  }

  setUp(() {
    now = DateTime(2026, 1, 1, 12);
    store = MemoryStore();
    llamadas = [];
    estados = {};
    invitaciones = MemoryInvitations();
    cuerpos = [];
    detalles = {};
    bearers = [];
    google = GoogleDeMentira();
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

  test('refresh de una cuenta de baja: no se crea otra cuenta sola', () async {
    final auth = build();
    await auth.accessToken();
    now = now.add(const Duration(hours: 2));
    estados['/v1/auth/refresh'] = 403;
    detalles['/v1/auth/refresh'] = {'codigo': 'cuenta_baja'};
    await expectLater(
      auth.accessToken(),
      throwsA(
        isA<ApiException>().having((e) => e.isCuentaBaja, 'isCuentaBaja', true),
      ),
    );
    expect(llamadas.last, '/v1/auth/refresh'); // no volvió a /anonymous
    expect(store.session, isNotNull);
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

  group('invitación', () {
    test('manda el código guardado al crear el usuario', () async {
      invitaciones.code = 'grupo';
      await build().accessToken();
      expect(cuerpos.single, {'codigo_invitacion': 'grupo'});
    });

    test('guardarInvitacion recorta y persiste el código', () async {
      await build().guardarInvitacion('  grupo ');
      expect(invitaciones.code, 'grupo');
    });

    test('si el backend la pide, avisa con InvitacionRequerida', () async {
      estados['/v1/auth/anonymous'] = 403;
      detalles['/v1/auth/anonymous'] = {'codigo': 'invitacion_requerida'};
      await expectLater(
        build().accessToken(),
        throwsA(
          isA<InvitacionRequerida>().having(
            (e) => e.rechazada,
            'rechazada',
            false,
          ),
        ),
      );
    });

    test('código rechazado: se descarta y se pide de nuevo', () async {
      invitaciones.code = 'malo';
      estados['/v1/auth/anonymous'] = 403;
      detalles['/v1/auth/anonymous'] = {'codigo': 'invitacion_invalida'};
      await expectLater(
        build().accessToken(),
        throwsA(
          isA<InvitacionRequerida>().having(
            (e) => e.rechazada,
            'rechazada',
            true,
          ),
        ),
      );
      expect(invitaciones.code, isNull);
    });

    test('429 al crear el usuario llega como ApiException', () async {
      estados['/v1/auth/anonymous'] = 429;
      await expectLater(
        build().accessToken(),
        throwsA(
          isA<ApiException>().having((e) => e.isRateLimited, '429', true),
        ),
      );
    });
  });

  group('Google', () {
    test(
      'ligar: manda el id_token con la sesión y guarda la sesión nueva',
      () async {
        final auth = build();
        await auth.accessToken(); // sesión anónima: acc1

        await auth.ligarConGoogle();

        expect(llamadas, ['/v1/auth/anonymous', '/v1/auth/google/ligar']);
        expect(bearers.last, 'Bearer acc1');
        expect(cuerpos.last, {'id_token': 'id-google-1'});
        expect(store.session?.accessToken, 'acc2'); // ya no dice anónima
        expect(await auth.accessToken(), 'acc2');
      },
    );

    test('ligar: si la persona cancela no se llama al backend', () async {
      final auth = build();
      await auth.accessToken();
      llamadas.clear();
      google.idToken = null;

      await expectLater(auth.ligarConGoogle(), throwsA(isA<GoogleCancelado>()));

      expect(llamadas, isEmpty);
      expect(store.session?.accessToken, 'acc1');
    });

    test('ligar: dos toques seguidos hacen una sola operación', () async {
      final auth = build();
      await auth.accessToken();
      llamadas.clear();

      await Future.wait([auth.ligarConGoogle(), auth.ligarConGoogle()]);

      expect(llamadas, ['/v1/auth/google/ligar']);
      expect(google.pedidos, 1);
    });

    test('ligar: ese Google ya es de otra cuenta', () async {
      final auth = build();
      await auth.accessToken();
      estados['/v1/auth/google/ligar'] = 409;
      detalles['/v1/auth/google/ligar'] = {'codigo': 'google_ya_ligado'};

      await expectLater(auth.ligarConGoogle(), throwsA(isA<GoogleYaLigado>()));
      expect(store.session?.accessToken, 'acc1'); // sigue con su cuenta
    });

    test('entrar: abre sesión sin token previo y la guarda', () async {
      final auth = build();

      await auth.entrarConGoogle();

      expect(llamadas, ['/v1/auth/google/entrar']);
      expect(bearers.single, isNull);
      expect(cuerpos.single, {'id_token': 'id-google-1'});
      expect(store.session?.accessToken, 'acc1');
    });

    test(
      'entrar con cuenta nueva y modo invitación: pide el código y reintenta '
      'con el mismo id_token',
      () async {
        final auth = build();
        estados['/v1/auth/google/entrar'] = 403;
        detalles['/v1/auth/google/entrar'] = {'codigo': 'invitacion_requerida'};
        await expectLater(
          auth.entrarConGoogle(),
          throwsA(
            isA<InvitacionRequerida>().having((e) => e.rechazada, 'r', false),
          ),
        );
        estados.remove('/v1/auth/google/entrar');
        cuerpos.clear();

        await auth.entrarConGoogle(codigoInvitacion: '123456');

        expect(google.pedidos, 1); // no se vuelve a abrir el selector de Google
        expect(cuerpos.single, {
          'id_token': 'id-google-1',
          'codigo_invitacion': '123456',
        });
        expect(store.session, isNotNull);
      },
    );

    test('entrar con un código malo vuelve a pedirlo', () async {
      final auth = build();
      estados['/v1/auth/google/entrar'] = 403;
      detalles['/v1/auth/google/entrar'] = {'codigo': 'invitacion_invalida'};
      await expectLater(
        auth.entrarConGoogle(codigoInvitacion: 'x'),
        throwsA(
          isA<InvitacionRequerida>().having((e) => e.rechazada, 'r', true),
        ),
      );
    });

    test('entrar con una cuenta de baja llega como ApiException', () async {
      final auth = build();
      estados['/v1/auth/google/entrar'] = 403;
      detalles['/v1/auth/google/entrar'] = {'codigo': 'cuenta_baja'};
      await expectLater(
        auth.entrarConGoogle(),
        throwsA(
          isA<ApiException>().having((e) => e.isCuentaBaja, 'baja', true),
        ),
      );
    });
  });
}
