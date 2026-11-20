import 'dart:io';

import 'api_client.dart';

/// Datos de la compilación, grabados por `make apk` con `--dart-define`.
/// Sin ellos (flutter run, tests) se ven como «dev».
class BuildInfo {
  const BuildInfo({
    required this.version,
    required this.commit,
    required this.compilado,
  });

  static const actual = BuildInfo(
    version: String.fromEnvironment('APP_VERSION', defaultValue: 'dev'),
    commit: String.fromEnvironment('APP_COMMIT', defaultValue: '-'),
    compilado: String.fromEnvironment('APP_BUILT_AT', defaultValue: '-'),
  );

  final String version;
  final String commit;
  final String compilado;
}

/// Una IP del celular en una interfaz de red (p. ej. `wlan0`).
class IpLocal {
  const IpLocal({required this.interfaz, required this.ip});

  final String interfaz;
  final String ip;
}

/// Lo que se muestra en la pantalla principal para saber qué app es esta y a
/// dónde habla. La lista crece a medida que haga falta (ver docs/04).
class InfoApp {
  const InfoApp({
    required this.build,
    required this.apiUrl,
    required this.ips,
    required this.servidor,
  });

  final BuildInfo build;
  final String apiUrl;

  /// IPv4 del celular, sin loopback. Vacío si no hay red.
  final List<IpLocal> ips;

  /// Resultado de probar `/v1/health`: «responde (35 ms)» o el motivo del fallo.
  final String servidor;
}

/// IPv4 del celular en todas sus interfaces, menos loopback.
Future<List<IpLocal>> ipsLocales() async {
  final interfaces = await NetworkInterface.list(
    type: InternetAddressType.IPv4,
    includeLoopback: false,
  );
  return [
    for (final i in interfaces)
      for (final a in i.addresses) IpLocal(interfaz: i.name, ip: a.address),
  ];
}

/// Prueba el servidor sin sesión (`/v1/health`) y describe el resultado en una
/// frase. Sirve para separar «no hay red» de «hay red pero el backend falla».
Future<String> probarServidor(ApiClient api) async {
  final reloj = Stopwatch()..start();
  try {
    await api.get('/health');
    return 'responde (${reloj.elapsedMilliseconds} ms)';
  } on ApiException catch (e) {
    return e.statusCode == null
        ? 'sin conexión (${e.message})'
        : 'respondió error ${e.statusCode}';
  }
}
