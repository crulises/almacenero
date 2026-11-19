import 'api_client.dart';
import 'session.dart';

/// El backend pide (o rechazó) el código de invitación para crear el usuario.
/// La UI debe pedirlo y llamar a [AuthRepository.guardarInvitacion].
class InvitacionRequerida implements Exception {
  const InvitacionRequerida({this.rechazada = false});

  /// true si había un código y el backend lo rechazó (inválido, vencido o agotado).
  final bool rechazada;

  @override
  String toString() => 'InvitacionRequerida(rechazada: $rechazada)';
}

/// Maneja la sesión: arranca anónima, la persiste y la renueva sola.
class AuthRepository {
  AuthRepository({
    required this._api,
    required this._store,
    this._invitations,
    DateTime Function()? now,
  }) : _now = now ?? DateTime.now;

  final ApiClient _api;
  final SessionStore _store;
  final InvitationStore? _invitations;
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

  /// Guarda el código de invitación para el próximo alta.
  Future<void> guardarInvitacion(String codigo) async =>
      _invitations?.write(codigo.trim());

  Future<Session> _signInAnonymously() async {
    final codigo = await _invitations?.read();
    try {
      return await _save(
        await _api.post(
          '/auth/anonymous',
          body: codigo == null ? null : {'codigo_invitacion': codigo},
        ),
      );
    } on ApiException catch (e) {
      final motivo = e.codigo;
      if (motivo == 'invitacion_requerida') throw const InvitacionRequerida();
      if (motivo == 'invitacion_invalida') {
        await _invitations?.clear(); // no sirve: que lo vuelva a escribir
        throw const InvitacionRequerida(rechazada: true);
      }
      rethrow;
    }
  }

  Future<Session> _save(Map<String, dynamic> json) async {
    final session = Session.fromBackend(json, _now());
    await _store.write(session);
    return session;
  }
}
