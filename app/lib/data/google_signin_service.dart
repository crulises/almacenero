import 'package:google_sign_in/google_sign_in.dart';

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
      return cuenta.authentication.idToken;
    } on GoogleSignInException catch (e) {
      if (e.code == GoogleSignInExceptionCode.canceled) return null;
      rethrow;
    }
  }
}
