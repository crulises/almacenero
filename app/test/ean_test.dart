import 'package:almacenero/domain/ean.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('acepta de 8 a 14 dígitos y recorta espacios', () {
    expect(normalizarEan('7790070411112'), '7790070411112');
    expect(normalizarEan('  7790070411112\n'), '7790070411112');
    expect(normalizarEan('12345678'), '12345678');
    expect(normalizarEan('12345678901234'), '12345678901234');
  });

  test('rechaza lo que no es un código de barras', () {
    expect(normalizarEan(null), isNull);
    expect(normalizarEan(''), isNull);
    expect(normalizarEan('1234567'), isNull);
    expect(normalizarEan('123456789012345'), isNull);
    expect(normalizarEan('77900704111a2'), isNull);
    expect(normalizarEan('7790 0704 1111'), isNull);
  });
}
