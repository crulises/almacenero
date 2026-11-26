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
      // Ojo: en Android `canceled` también sale cuando la configuración está mal (paquete o
      // SHA-1 sin registrar en Google Cloud); por eso se avisa y se deja el detalle.
      if (e.code == GoogleSignInExceptionCode.canceled) return null;
      throw GoogleFallo('${e.code.name}: ${e.description ?? 'sin detalle'}');
    }
  }
}
