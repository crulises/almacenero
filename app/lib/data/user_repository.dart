import 'authed_api.dart';

/// normal: nada. aviso: la app avisa, sigue usando todo. restringido: solo consulta.
enum Escalon { normal, aviso, restringido }

class Me {
  const Me({
    required this.id,
    required this.alias,
    required this.karma,
    this.escalon = Escalon.normal,
    this.umbralRestriccion = -15,
    this.rol = 'usuario',
  });

  final String id;
  final String alias;
  final int karma;

  /// Moderación por karma (docs/04 §9): lo decide el backend.
  final Escalon escalon;

  /// Karma desde el cual no se puede cargar (para explicarlo en el aviso).
  final int umbralRestriccion;

  /// usuario | moderador | admin.
  final String rol;

  /// Los moderadores (y admins) proponen correcciones y altas del catálogo.
  bool get puedeSugerir => rol == 'moderador' || rol == 'admin';

  factory Me.fromJson(Map<String, dynamic> json) => Me(
    id: json['id'] as String,
    alias: json['alias'] as String,
    karma: json['karma'] as int,
    escalon: switch (json['escalon']) {
      'aviso' => Escalon.aviso,
      'restringido' => Escalon.restringido,
      _ => Escalon.normal,
    },
    umbralRestriccion: json['umbral_restriccion'] as int? ?? -15,
    rol: json['rol'] as String? ?? 'usuario',
  );
}

class UserRepository {
  UserRepository({required this._api});

  final AuthedApi _api;

  Future<Me> me() async => Me.fromJson(await _api.get('/me'));
}
