import 'dart:convert';

import 'package:almacenero/app_deps.dart';
import 'package:almacenero/data/api_client.dart';
import 'package:almacenero/data/auth_repository.dart';
import 'package:almacenero/data/authed_api.dart';
import 'package:almacenero/data/session.dart';
import 'package:almacenero/data/user_repository.dart';
import 'package:almacenero/main.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:material_ui/material_ui.dart';

class _Sesion implements SessionStore {
  Session? s;
  @override
  Future<Session?> read() async => s;
  @override
  Future<void> write(Session x) async => s = x;
  @override
  Future<void> clear() async => s = null;
}

class _Codigo implements InvitationStore {
  String? c;
  @override
  Future<String?> read() async => c;
  @override
  Future<void> write(String x) async => c = x;
  @override
  Future<void> clear() async => c = null;
}

void main() {
  testWidgets('cadena real: 403 del backend -> pantalla pide el código', (
    tester,
  ) async {
    final codigo = _Codigo();
    final cliente = MockClient((r) async {
      if (r.url.path == '/v1/auth/anonymous') {
        final body = r.body.isEmpty ? null : jsonDecode(r.body);
        if (body?['codigo_invitacion'] == 'bueno') {
          return http.Response(
            jsonEncode({
              'access_token': 'a',
              'refresh_token': 'r',
              'expires_in': 3600,
            }),
            200,
          );
        }
        return http.Response(
          jsonEncode({
            'detail': {'codigo': 'invitacion_requerida', 'mensaje': 'falta'},
          }),
          403,
          headers: {'content-type': 'application/json'},
        );
      }
      return http.Response(
        jsonEncode({'id': 'u', 'alias': 'anon-xyz', 'karma': 0}),
        200,
      );
    });
    final api = ApiClient(baseUrl: 'http://x', httpClient: cliente);
    final auth = AuthRepository(
      api: api,
      store: _Sesion(),
      invitations: codigo,
    );
    final authed = AuthedApi(api: api, auth: auth);

    await tester.pumpWidget(
      AlmaceneroApp(
        deps: AppDeps(
          guardarInvitacion: auth.guardarInvitacion,
          loadMe: UserRepository(api: authed).me,
          loadProducto: (_) => throw UnimplementedError(),
          obtenerUbicacion: () => throw UnimplementedError(),
          abrirAjustes: () async {},
          loadLocalesCerca: (_) => throw UnimplementedError(),
          crearLocal: ({required nombre, direccion, required ubicacion}) =>
              throw UnimplementedError(),
          loadHistorial: (_) => throw UnimplementedError(),
          loadVigentes: (_, {ubicacion}) => throw UnimplementedError(),
          cargarPrecio: ({
            required ean,
            required localId,
            required precio,
            required ubicacion,
          }) => throw UnimplementedError(),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('Código de invitación'), findsOneWidget);
    await tester.enterText(find.byType(TextField).first, 'bueno');
    await tester.tap(find.text('Entrar'));
    await tester.pumpAndSettle();
    expect(find.text('anon-xyz'), findsOneWidget);
  });
}
