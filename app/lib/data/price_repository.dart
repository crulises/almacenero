import 'api_client.dart';
import 'authed_api.dart';

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
}
