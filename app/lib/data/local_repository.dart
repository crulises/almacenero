import 'authed_api.dart';

class Local {
  const Local({required this.id, required this.nombre, this.direccion});

  final String id;
  final String nombre;
  final String? direccion;

  factory Local.fromJson(Map<String, dynamic> json) => Local(
    id: json['id'] as String,
    nombre: json['nombre'] as String,
    direccion: json['direccion'] as String?,
  );
}

class LocalRepository {
  LocalRepository({required this._api});

  final AuthedApi _api;

  /// Locales disponibles. En v0.0.1 hay uno solo (el del admin).
  Future<List<Local>> listar() async => [
    for (final l in await _api.getList('/locales'))
      Local.fromJson(l as Map<String, dynamic>),
  ];
}
