import 'api_client.dart';
import 'authed_api.dart';

class Producto {
  const Producto({
    required this.id,
    required this.ean,
    required this.nombre,
    this.marca,
    this.tamanoValor,
    this.tamanoUnidad,
  });

  final String id;
  final String ean;
  final String nombre;
  final String? marca;
  final num? tamanoValor;
  final String? tamanoUnidad;

  /// "900 ml", o null si el producto no tiene tamaño cargado.
  String? get tamano {
    final valor = tamanoValor;
    final unidad = tamanoUnidad;
    if (valor == null || unidad == null) return null;
    final texto = valor == valor.roundToDouble()
        ? valor.toInt().toString()
        : valor.toString();
    return '$texto ${unidad == 'u' ? 'un.' : unidad}';
  }

  factory Producto.fromJson(Map<String, dynamic> json) => Producto(
    id: json['id'] as String,
    ean: json['ean'] as String,
    nombre: json['nombre'] as String,
    marca: json['marca'] as String?,
    // El backend serializa los Decimal como string ("900").
    tamanoValor: json['tamano_valor'] == null
        ? null
        : num.parse(json['tamano_valor'].toString()),
    tamanoUnidad: json['tamano_unidad'] as String?,
  );
}

/// Por qué no se pudo obtener un producto.
enum ProductoError { noEncontrado, eanDeBalanza, otro }

ProductoError clasificarError(Object error) {
  if (error is ApiException) {
    if (error.statusCode == 404) return ProductoError.noEncontrado;
    if (error.statusCode == 422) return ProductoError.eanDeBalanza;
  }
  return ProductoError.otro;
}

class ProductRepository {
  ProductRepository({required this._api});

  final AuthedApi _api;

  /// Busca un producto del catálogo canónico por EAN. Lanza [ApiException]:
  /// 404 si no está en el catálogo, 422 si es un EAN de balanza (empieza con 2).
  Future<Producto> porEan(String ean) async =>
      Producto.fromJson(await _api.get('/productos/$ean'));
}
