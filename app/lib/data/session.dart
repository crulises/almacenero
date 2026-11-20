import 'dart:convert';

import 'package:flutter_secure_storage/flutter_secure_storage.dart';

/// Sesión del usuario: tokens del proveedor de auth, obtenidos vía backend.
class Session {
  const Session({
    required this.accessToken,
    required this.refreshToken,
    required this.expiresAt,
  });

  final String accessToken;
  final String refreshToken;
  final DateTime expiresAt;

  /// Considera vencido un poco antes, para no mandar un token a punto de expirar.
  bool isExpired(DateTime now) =>
      now.isAfter(expiresAt.subtract(const Duration(seconds: 30)));

  factory Session.fromBackend(Map<String, dynamic> json, DateTime now) =>
      Session(
        accessToken: json['access_token'] as String,
        refreshToken: json['refresh_token'] as String,
        expiresAt: now.add(Duration(seconds: json['expires_in'] as int)),
      );

  Map<String, dynamic> toJson() => {
    'access_token': accessToken,
    'refresh_token': refreshToken,
    'expires_at': expiresAt.millisecondsSinceEpoch,
  };

  factory Session.fromJson(Map<String, dynamic> json) => Session(
    accessToken: json['access_token'] as String,
    refreshToken: json['refresh_token'] as String,
    expiresAt: DateTime.fromMillisecondsSinceEpoch(json['expires_at'] as int),
  );
}

/// Dónde se guarda la sesión entre arranques.
abstract class SessionStore {
  Future<Session?> read();
  Future<void> write(Session session);
  Future<void> clear();
}

/// Almacenamiento cifrado (Keystore en Android): el refresh token es sensible.
class SecureSessionStore implements SessionStore {
  SecureSessionStore([FlutterSecureStorage? storage])
    : _storage = storage ?? const FlutterSecureStorage();

  static const _key = 'session';
  final FlutterSecureStorage _storage;

  @override
  Future<Session?> read() async {
    final raw = await _storage.read(key: _key);
    if (raw == null) return null;
    try {
      return Session.fromJson(jsonDecode(raw) as Map<String, dynamic>);
    } on Object {
      return null; // dato corrupto: se trata como "sin sesión"
    }
  }

  @override
  Future<void> write(Session session) =>
      _storage.write(key: _key, value: jsonEncode(session.toJson()));

  @override
  Future<void> clear() => _storage.delete(key: _key);
}

/// Código de invitación del grupo: se pide una sola vez, en el primer arranque.
abstract class InvitationStore {
  Future<String?> read();
  Future<void> write(String code);
  Future<void> clear();
}

class SecureInvitationStore implements InvitationStore {
  SecureInvitationStore([FlutterSecureStorage? storage])
    : _storage = storage ?? const FlutterSecureStorage();

  static const _key = 'invitation';
  final FlutterSecureStorage _storage;

  @override
  Future<String?> read() => _storage.read(key: _key);

  @override
  Future<void> write(String code) => _storage.write(key: _key, value: code);

  @override
  Future<void> clear() => _storage.delete(key: _key);
}
