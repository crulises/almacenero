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
}
