import 'dart:async';
import 'dart:ui' show PlatformDispatcher;

import 'package:connectivity_plus/connectivity_plus.dart';
import 'package:device_info_plus/device_info_plus.dart';

import 'app_info.dart';

/// Qué celular y en qué condiciones se abrió la app, para el evento `app.abierta`
/// (docs/04 §11.2). Solo datos que Android da **sin pedir permisos al usuario**: nada de
/// ubicación, nombre de la red, batería ni identificadores del aparato.
///
/// Cada dato se lee por separado: si uno falla o tarda, se omite y el resto llega. Nunca
/// lanza ni demora la app (el evento se anota recién cuando esto termina).
Future<Map<String, Object?>> armarDatosApertura(
  Map<String, Future<Object?> Function()> lectores, {
  Duration esperaMaxima = const Duration(seconds: 3),
}) async {
  final datos = <String, Object?>{};
  await Future.wait(
    lectores.entries.map((e) async {
      try {
        var valor = await Future<Object?>.sync(e.value).timeout(esperaMaxima);
        if (valor is String) {
          final texto = valor.trim();
          if (texto.isEmpty) return;
          final tope = _recortes[e.key];
          valor = tope != null && texto.length > tope
              ? texto.substring(0, tope)
              : texto;
        }
        if (valor != null) datos[e.key] = valor;
      } catch (_) {
        // Esta lectura se omite; las demás siguen.
      }
    }),
  );
  return datos;
}

// Largos máximos que acepta el backend (services/eventos.py).
const _recortes = {
  'app_version': 40,
  'android': 20,
  'marca': 40,
  'modelo': 60,
  'idioma': 20,
};

/// De los tipos de conexión de `connectivity_plus` al vocabulario del backend.
String nombreDeRed(Iterable<String> conexiones) {
  final c = conexiones.toSet();
  if (c.contains('wifi')) return 'wifi';
  if (c.contains('ethernet')) return 'ethernet';
  if (c.contains('mobile')) return 'movil';
  if (c.isEmpty || (c.length == 1 && c.contains('none'))) return 'ninguna';
  return 'otra';
}

/// Las lecturas reales del celular.
Map<String, Future<Object?> Function()> lectoresReales() {
  final info = DeviceInfoPlugin();
  return {
    'app_version': () async => BuildInfo.actual.version,
    'android': () async => (await info.androidInfo).version.release,
    'sdk': () async => (await info.androidInfo).version.sdkInt,
    'marca': () async => (await info.androidInfo).manufacturer,
    'modelo': () async => (await info.androidInfo).model,
    'idioma': () async => PlatformDispatcher.instance.locale.toLanguageTag(),
    'red': () async => nombreDeRed(
      (await Connectivity().checkConnectivity()).map((r) => r.name),
    ),
  };
}
