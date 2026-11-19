import 'data/local_repository.dart';
import 'data/location_service.dart';
import 'data/price_repository.dart';
import 'data/product_repository.dart';
import 'data/user_repository.dart';

/// Lo que las pantallas necesitan del backend, como funciones. Así los tests
/// reemplazan solo lo que les importa, sin armar una red falsa.
class AppDeps {
  const AppDeps({
    required this.loadMe,
    required this.loadProducto,
    required this.obtenerUbicacion,
    required this.abrirAjustes,
    required this.loadLocalesCerca,
    required this.crearLocal,
    required this.cargarPrecio,
    required this.loadHistorial,
    required this.loadVigentes,
  });

  final Future<Me> Function() loadMe;
  final Future<Producto> Function(String ean) loadProducto;
  final Future<Ubicacion> Function() obtenerUbicacion;
  final Future<void> Function() abrirAjustes;
  final Future<List<Local>> Function(Ubicacion ubicacion) loadLocalesCerca;
  final Future<Local> Function({
    required String nombre,
    String? direccion,
    required Ubicacion ubicacion,
  })
  crearLocal;
  final Future<PrecioCargado> Function({
    required String ean,
    required String localId,
    required String precio,
    required Ubicacion ubicacion,
  })
  cargarPrecio;
  final Future<List<PrecioHistorial>> Function(String ean) loadHistorial;
  final Future<List<PrecioVigente>> Function(String ean, {Ubicacion? ubicacion})
  loadVigentes;
}
