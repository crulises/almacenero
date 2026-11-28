import 'package:almacenero/data/google_signin_service.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:google_sign_in/google_sign_in.dart';

void main() {
  test('canceled explica que Google puede no dejar entrar a esa cuenta', () {
    final t = describirFalloGoogle(
      GoogleSignInExceptionCode.canceled,
      'reauth failed',
      '[16]',
    );
    expect(t, contains('usuarios de prueba'));
    expect(t, contains('canceled: reauth failed ([16])'));
  });

  test('sin descripción ni detalles igual conserva el código técnico', () {
    final t = describirFalloGoogle(
      GoogleSignInExceptionCode.unknownError,
      null,
      null,
    );
    expect(t, contains('[unknownError: sin descripción]'));
  });
}
