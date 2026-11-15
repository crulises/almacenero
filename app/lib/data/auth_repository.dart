import 'api_client.dart';
import 'session.dart';

/// Maneja la sesión: arranca anónima, la persiste y la renueva sola.
class AuthRepository {
  AuthRepository({
    required this._api,
    required this._store,
    DateTime Function()? now,
  }) : _now = now ?? DateTime.now;

  final ApiClient _api;
  final SessionStore _store;
  final DateTime Function() _now;

  Future<Session>? _inFlight;

  /// Token válido para llamar al backend. Crea o renueva la sesión si hace falta.
  /// Llamadas simultáneas comparten la misma operación (no se crean dos usuarios).
  Future<String> accessToken({bool forceRefresh = false}) async {
    final session = await (_inFlight ??= _resolve(forceRefresh)
        .whenComplete(() => _inFlight = null));
    return session.accessToken;
  }

  Future<Session> _resolve(bool forceRefresh) async {
    final current = await _store.read();
    if (current == null) return _signInAnonymously();
    if (!forceRefresh && !current.isExpired(_now())) return current;
    try {
      final json = await _api.post(
        '/auth/refresh',
        body: {'refresh_token': current.refreshToken},
      );
      return await _save(json);
    } on ApiException catch (e) {
      // Refresh token inválido: la sesión se perdió. Se vuelve a empezar anónimo.
      if (e.isUnauthorized) return _signInAnonymously();
      rethrow;
    }
  }

  Future<Session> _signInAnonymously() async =>
      _save(await _api.post('/auth/anonymous'));

  Future<Session> _save(Map<String, dynamic> json) async {
    final session = Session.fromBackend(json, _now());
    await _store.write(session);
    return session;
  }
}
