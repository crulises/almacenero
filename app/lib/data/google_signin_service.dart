import 'package:google_sign_in/google_sign_in.dart';

import 'auth_repository.dart' show GoogleFallo;

/// Abre el selector de cuentas de Google y devuelve el `id_token` (que el backend
/// reenvía a GoTrue). Una interfaz aparte para poder probar sin Google.
abstract class GoogleSignInService {
  /// `null` si la persona cancela el selector.
  Future<String?> obtenerIdToken();
}

/// Google Sign-In nativo de Android. El `serverClientId` es el cliente **Web** de Google
/// Cloud (`GOOGLE_WEB_CLIENT_ID`, que `make apk` toma del `.env`): el `id_token` sale
/// emitido para ese cliente, que es el que valida GoTrue. El cliente de Android solo se
/// registra en Google Cloud (paquete + SHA-1), no se usa en el código.
class GoogleSignInNativo implements GoogleSignInService {
  GoogleSignInNativo({
    this.serverClientId = const String.fromEnvironment('GOOGLE_WEB_CLIENT_ID'),
  });

  final String serverClientId;
  Future<void>? _inicializado;

  @override
  Future<String?> obtenerIdToken() async {
    final google = GoogleSignIn.instance;
    await (_inicializado ??= google.initialize(
      serverClientId: serverClientId.isEmpty ? null : serverClientId,
    ));
    try {
      final cuenta = await google.authenticate();
      final idToken = cuenta.authentication.idToken;
      if (idToken == null) {
        throw GoogleFallo(
          serverClientId.isEmpty
              ? 'esta build no trae GOOGLE_WEB_CLIENT_ID: armá el APK con make apk'
              : 'Google no devolvió el id_token (¿el cliente Web es el correcto?)',
        );
      }
      return idToken;
    } on GoogleSignInException catch (e) {
      throw GoogleFallo(describirFalloGoogle(e.code, e.description, e.details));
    }
  }
}

/// Texto para la persona cuando Google corta el ingreso. En Android `canceled` también sale
/// cuando algo está mal configurado o Google no deja entrar a la cuenta elegida (la app en
/// modo de prueba y esa cuenta fuera de «Usuarios de prueba», paquete o SHA-1 sin registrar):
/// por eso se explica en vez de mostrar solo el código, y siempre queda el detalle técnico.
String describirFalloGoogle(
  GoogleSignInExceptionCode code,
  String? descripcion,
  Object? detalles,
) {
  final tecnico =
      '${code.name}: ${descripcion ?? 'sin descripción'}'
      '${detalles == null ? '' : ' ($detalles)'}';
  final causa = switch (code) {
    GoogleSignInExceptionCode.canceled =>
      'Google cerró el ingreso antes de terminar. Si no lo cancelaste vos, quizá '
          'Google no deja entrar a esa cuenta: mientras la app está en modo de prueba, '
          'solo entran las cuentas cargadas como usuarios de prueba.',
    GoogleSignInExceptionCode.interrupted =>
      'El ingreso se interrumpió. Probá de nuevo.',
    GoogleSignInExceptionCode.clientConfigurationError ||
    GoogleSignInExceptionCode.providerConfigurationError =>
      'Esta versión de la app no está bien configurada para Google.',
    GoogleSignInExceptionCode.uiUnavailable =>
      'No se pudo mostrar la pantalla de Google. Probá de nuevo.',
    _ => 'Google no pudo completar el ingreso.',
  };
  return '$causa [$tecnico]';
}
