import 'api_client.dart';
import 'auth_repository.dart';

class Me {
  const Me({required this.id, required this.alias, required this.karma});

  final String id;
  final String alias;
  final int karma;

  factory Me.fromJson(Map<String, dynamic> json) => Me(
    id: json['id'] as String,
    alias: json['alias'] as String,
    karma: json['karma'] as int,
  );
}

class UserRepository {
  UserRepository({required this._api, required this._auth});

  final ApiClient _api;
  final AuthRepository _auth;

  /// Usuario actual. Si el backend rechaza el token (401), renueva y reintenta una vez.
  Future<Me> me() async {
    try {
      return Me.fromJson(
        await _api.get('/me', token: await _auth.accessToken()),
      );
    } on ApiException catch (e) {
      if (!e.isUnauthorized) rethrow;
      final token = await _auth.accessToken(forceRefresh: true);
      return Me.fromJson(await _api.get('/me', token: token));
    }
  }
}
