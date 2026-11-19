import 'api_client.dart';
import 'authed_api.dart';
import 'location_service.dart';

/// Resultado de cargar un precio: su id y el karma ya actualizado del usuario.
class PrecioCargado {
  const PrecioCargado({required this.precioId, required this.karma});

  final String precioId;
  final int karma;

  factory PrecioCargado.fromJson(Map<String, dynamic> json) => PrecioCargado(
    precioId: json['precio_id'] as String,
    karma: json['karma'] as int,
  );
}

/// Un precio ya cargado, del historial de un producto.
class PrecioHistorial {
  const PrecioHistorial({
    required this.id,
    required this.localNombre,
    required this.precio,
    required this.fecha,
  });

  final String id;
  final String localNombre;

  /// Formato canónico, p. ej. "1234.50" (el backend lo manda como string).
  final String precio;
  final DateTime fecha;

  factory PrecioHistorial.fromJson(Map<String, dynamic> json) =>
      PrecioHistorial(
        id: json['id'] as String,
        localNombre: json['local_nombre'] as String,
        precio: json['precio'].toString(),
        fecha: DateTime.parse(json['fecha'] as String),
      );
}

/// El último precio de un producto en un local, con su frescura (la calcula el
/// backend con los umbrales de `config`).
class PrecioVigente {
  const PrecioVigente({
    required this.localId,
    required this.localNombre,
    required this.localVerificado,
    required this.lat,
    required this.lng,
    required this.precio,
    required this.fecha,
    required this.edadDias,
    required this.frescura,
    required this.vencido,
    this.distanciaM,
  });

  final String localId;
  final String localNombre;
  final bool localVerificado;
  final double lat;
  final double lng;

  /// Formato canónico, p. ej. "1234.50".
  final String precio;
  final DateTime fecha;
  final int edadDias;

  /// `verde`, `amarillo` o `rojo`.
  final String frescura;

  /// Más viejo que la ventana de frescura.
  final bool vencido;

  /// Distancia al usuario; solo viene si se pidió con ubicación.
  final double? distanciaM;

  factory PrecioVigente.fromJson(Map<String, dynamic> json) => PrecioVigente(
    localId: json['local_id'] as String,
    localNombre: json['local_nombre'] as String,
    localVerificado: json['local_verificado'] as bool? ?? true,
    lat: (json['lat'] as num).toDouble(),
    lng: (json['lng'] as num).toDouble(),
    precio: json['precio'].toString(),
    fecha: DateTime.parse(json['fecha'] as String),
    edadDias: json['edad_dias'] as int,
    frescura: json['frescura'] as String,
    vencido: json['vencido'] as bool? ?? false,
    distanciaM: (json['distancia_m'] as num?)?.toDouble(),
  );
}

/// Por qué falló la carga de un precio.
enum CargaError { noEncontrado, precioInvalido, otro }

CargaError clasificarErrorCarga(Object error) {
  if (error is ApiException) {
    if (error.statusCode == 404) return CargaError.noEncontrado;
    if (error.statusCode == 422) return CargaError.precioInvalido;
  }
  return CargaError.otro;
}

class PriceRepository {
  PriceRepository({required this._api});

  final AuthedApi _api;

  /// Carga el precio de un producto en un local. [precio] ya viene en formato
  /// canónico (ver `parsearPrecio`). Suma karma al usuario.
  Future<PrecioCargado> cargar({
    required String ean,
    required String localId,
    required String precio,
  }) async => PrecioCargado.fromJson(
    await _api.post('/precios', {
      'ean': ean,
      'local_id': localId,
      'precio': precio,
    }),
  );

  /// Precios cargados de un producto, el más nuevo primero.
  Future<List<PrecioHistorial>> historial(String ean) async => [
    for (final p in await _api.getList('/productos/$ean/precios'))
      PrecioHistorial.fromJson(p as Map<String, dynamic>),
  ];

  /// El último precio de cada local, del más barato al más caro. Con [ubicacion]
  /// el backend trae solo los locales dentro del radio configurado (`config`) y la
  /// distancia a cada uno; sin ella, todos.
  Future<List<PrecioVigente>> vigentes(
    String ean, {
    Ubicacion? ubicacion,
  }) async {
    final consulta = ubicacion == null
        ? ''
        : '?lat=${ubicacion.lat}&lng=${ubicacion.lng}';
    return [
      for (final p in await _api.getList(
        '/productos/$ean/precios/vigentes$consulta',
      ))
        PrecioVigente.fromJson(p as Map<String, dynamic>),
    ];
  }
}
