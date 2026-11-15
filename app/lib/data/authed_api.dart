import 'api_client.dart';
import 'auth_repository.dart';

/// Llamadas al backend con la sesión del usuario. Si el backend rechaza el token (401),
/// renueva la sesión y reintenta una sola vez.
class AuthedApi {
  AuthedApi({required this._api, required this._auth});

  final ApiClient _api;
  final AuthRepository _auth;

  Future<Map<String, dynamic>> get(String path) =>
      _conReintento((token) => _api.get(path, token: token));

  Future<List<dynamic>> getList(String path) =>
      _conReintento((token) => _api.getList(path, token: token));

  Future<Map<String, dynamic>> post(String path, Map<String, dynamic> body) =>
      _conReintento((token) => _api.post(path, body: body, token: token));

  Future<T> _conReintento<T>(Future<T> Function(String token) llamada) async {
    try {
      return await llamada(await _auth.accessToken());
    } on ApiException catch (e) {
      if (!e.isUnauthorized) rethrow;
      return llamada(await _auth.accessToken(forceRefresh: true));
    }
  }
}
