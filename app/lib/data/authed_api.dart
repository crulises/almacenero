import 'api_client.dart';
import 'auth_repository.dart';

/// Llamadas al backend con la sesión del usuario. Si el backend rechaza el token (401),
/// renueva la sesión y reintenta una sola vez.
class AuthedApi {
  AuthedApi({required this._api, required this._auth});

  final ApiClient _api;
  final AuthRepository _auth;

  Future<Map<String, dynamic>> get(String path) async {
    try {
      return await _api.get(path, token: await _auth.accessToken());
    } on ApiException catch (e) {
      if (!e.isUnauthorized) rethrow;
      return _api.get(path, token: await _auth.accessToken(forceRefresh: true));
    }
  }
}
