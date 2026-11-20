import 'package:flutter/foundation.dart';

import 'data/app_info.dart';
import 'data/local_repository.dart';
import 'data/location_service.dart';
import 'data/price_repository.dart';
import 'data/product_repository.dart';
import 'data/user_repository.dart';

/// Lo que las pantallas necesitan del backend, como funciones. Así los tests
/// reemplazan solo lo que les importa, sin armar una red falsa.
Future<void> _sinInvitacion(String codigo) async {}

Future<InfoApp> _infoDePrueba() async =>
    const InfoApp(build: BuildInfo.actual, apiUrl: '-', ips: [], servidor: '-');

class AppDeps {
  const AppDeps({
    this.guardarInvitacion = _sinInvitacion,
    this.loadInfoApp = _infoDePrueba,
    this.cuentaBaja,
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

  /// Guarda el código de invitación que el usuario escribió (primer arranque).
  final Future<void> Function(String codigo) guardarInvitacion;

  /// Versión, servidor e IP del celular, para mostrar en la pantalla principal.
  final Future<InfoApp> Function() loadInfoApp;

  /// Pasa a `true` cuando el backend avisa que la cuenta fue dada de baja, desde
  /// cualquier pantalla: la app entera se reemplaza por la pantalla de baja.
  final ValueListenable<bool>? cuentaBaja;
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
