import 'api_client.dart';
import 'authed_api.dart';
import 'location_service.dart';

class Local {
  const Local({
    required this.id,
    required this.nombre,
    this.direccion,
    this.verificado = true,
    this.distanciaM,
  });

  final String id;
  final String nombre;
  final String? direccion;

  /// Un local creado por un usuario nace sin verificar hasta que lo revisa el admin.
  final bool verificado;

  /// Distancia al usuario, solo cuando viene de «locales cerca».
  final double? distanciaM;

  factory Local.fromJson(Map<String, dynamic> json) => Local(
    id: json['id'] as String,
    nombre: json['nombre'] as String,
    direccion: json['direccion'] as String?,
    verificado: json['verificado'] as bool? ?? true,
    distanciaM: (json['distancia_m'] as num?)?.toDouble(),
  );
}

/// Por qué falló el alta de un local.
enum AltaLocalError {
  duplicado,
  sinPermiso,
  limiteDiario,
  datosInvalidos,
  otro,
}

AltaLocalError clasificarErrorAltaLocal(Object error) {
  if (error is ApiException) {
    return switch (error.statusCode) {
      409 => AltaLocalError.duplicado,
      403 => AltaLocalError.sinPermiso,
      429 => AltaLocalError.limiteDiario,
      422 => AltaLocalError.datosInvalidos,
      _ => AltaLocalError.otro,
    };
  }
  return AltaLocalError.otro;
}

class LocalRepository {
  LocalRepository({required this._api});

  final AuthedApi _api;

  /// Locales dentro del geofence de [u], del más cercano al más lejano.
  Future<List<Local>> cerca(Ubicacion u) async => [
    for (final l in await _api.getList(
      '/locales/cerca?lat=${u.lat}&lng=${u.lng}',
    ))
      Local.fromJson(l as Map<String, dynamic>),
  ];

  /// Crea un local donde está parado el usuario. Nace sin verificar.
  Future<Local> crear({
    required String nombre,
    String? direccion,
    required Ubicacion ubicacion,
  }) async => Local.fromJson(
    await _api.post('/locales', {
      'nombre': nombre,
      if (direccion != null && direccion.isNotEmpty) 'direccion': direccion,
      'lat': ubicacion.lat,
      'lng': ubicacion.lng,
    }),
  );
}
