import 'data/local_repository.dart';
import 'data/price_repository.dart';
import 'data/product_repository.dart';
import 'data/user_repository.dart';

/// Lo que las pantallas necesitan del backend, como funciones. Así los tests
/// reemplazan solo lo que les importa, sin armar una red falsa.
class AppDeps {
  const AppDeps({
    required this.loadMe,
    required this.loadProducto,
    required this.loadLocales,
    required this.cargarPrecio,
    required this.loadHistorial,
  });

  final Future<Me> Function() loadMe;
  final Future<Producto> Function(String ean) loadProducto;
  final Future<List<Local>> Function() loadLocales;
  final Future<PrecioCargado> Function({
    required String ean,
    required String localId,
    required String precio,
  })
  cargarPrecio;
  final Future<List<PrecioHistorial>> Function(String ean) loadHistorial;
}
