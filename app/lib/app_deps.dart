import 'package:flutter/foundation.dart';
import 'package:flutter/widgets.dart' show Widget;

import 'data/app_info.dart';
import 'data/local_repository.dart';
import 'data/location_service.dart';
import 'data/price_repository.dart';
import 'data/product_repository.dart';
import 'data/recientes.dart';
import 'data/sugerencia_repository.dart';
import 'data/user_repository.dart';
import 'ui/scan_screen.dart';

/// Lo que las pantallas necesitan del backend, como funciones. Así los tests
/// reemplazan solo lo que les importa, sin armar una red falsa.
Future<void> _sinInvitacion(String codigo) async {}

Future<void> _sinEnlaces(Uri url) async {}

Future<InfoApp> _infoDePrueba() async =>
    const InfoApp(build: BuildInfo.actual, apiUrl: '-', ips: [], servidor: '-');

Future<SugerenciaEnviada> _sinSugerir({
  required String ean,
  required Map<String, Object?> cambios,
  String? motivo,
}) async => SugerenciaEnviada(id: '-', tipo: 'correccion', estado: 'pendiente');

Future<List<Estandar>> _sinEstandares() async => const [];

void _sinEventos(String tipo, [Map<String, Object?> datos = const {}]) {}

Future<void> _sinVaciar() async {}

Future<List<Reciente>> _sinRecientes() async => const [];

Future<void> _sinGuardar(Reciente reciente) async {}

Future<Reciente?> _sinRefrescar(Reciente reciente) async => null;

Widget _escaner() => const ScanScreen();

class AppDeps {
  const AppDeps({
    this.pantallaEscaneo = _escaner,
    this.leerRecientes = _sinRecientes,
    this.guardarReciente = _sinGuardar,
    this.refrescarReciente = _sinRefrescar,
    this.registrarEvento = _sinEventos,
    this.vaciarEventos = _sinVaciar,
    this.sugerir = _sinSugerir,
    this.loadEstandares = _sinEstandares,
    this.guardarInvitacion = _sinInvitacion,
    this.loadInfoApp = _infoDePrueba,
    this.abrirEnlace = _sinEnlaces,
    this.cuentaBaja,
    this.despertando,
    this.verificarCada,
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

  /// Anota un evento de producto (`producto.escaneado`, `app.abierta`). Síncrono y que
  /// nunca falla: la cola los manda aparte (docs/04 §11.2). En los tests no hace nada.
  final void Function(String tipo, [Map<String, Object?> datos])
  registrarEvento;

  /// Manda ya los eventos pendientes (al irse la app a segundo plano). Nunca lanza.
  final Future<void> Function() vaciarEventos;

  /// Guarda el código de invitación que el usuario escribió (primer arranque).
  final Future<void> Function(String codigo) guardarInvitacion;

  /// Abre un enlace en el navegador (pantalla «Acerca de»).
  final Future<void> Function(Uri url) abrirEnlace;

  /// Versión, servidor e IP del celular, para la pantalla «Acerca de».
  final Future<InfoApp> Function() loadInfoApp;

  /// Pasa a `true` cuando el backend avisa que la cuenta fue dada de baja, desde
  /// cualquier pantalla: la app entera se reemplaza por la pantalla de baja.
  final ValueListenable<bool>? cuentaBaja;

  /// `true` cuando un pedido tarda más de lo normal (el backend arranca en frío):
  /// la app muestra «Despertando servidor…» sobre cualquier pantalla.
  final ValueListenable<bool>? despertando;

  /// Cada cuánto la app consulta `/me` mientras está abierta, para enterarse de una
  /// baja (o un cambio de escalón) sin que la persona toque nada. `null` = no consulta
  /// (los tests).
  final Duration? verificarCada;

  /// Propone una corrección o un alta del catálogo (solo moderadores).
  final Future<SugerenciaEnviada> Function({
    required String ean,
    required Map<String, Object?> cambios,
    String? motivo,
  })
  sugerir;

  /// Los estándares de carga (ayuda para quien sugiere).
  final Future<List<Estandar>> Function() loadEstandares;
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
  final Future<List<PrecioVigente>> Function(
    String ean, {
    Ubicacion? ubicacion,
    bool referencia,
  })
  loadVigentes;

  /// La pantalla que lee el código de barras: vuelve con el EAN (`pop`) o con nada si se
  /// cancela. Los tests ponen una de mentira (no hay cámara).
  final Widget Function() pantallaEscaneo;

  /// Recientes (corte 20): lo guardado en el celular, anotar una consulta y refrescar una
  /// con red. Ninguna lanza: sin red se ve lo guardado.
  final Future<List<Reciente>> Function() leerRecientes;
  final Future<void> Function(Reciente reciente) guardarReciente;
  final Future<Reciente?> Function(Reciente reciente) refrescarReciente;
}
