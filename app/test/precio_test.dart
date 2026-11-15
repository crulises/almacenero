import 'package:almacenero/domain/precio.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('devuelve el formato canónico con dos decimales', () {
    expect(parsearPrecio('1234.50'), '1234.50');
    expect(parsearPrecio('1234,5'), '1234.50');
    expect(parsearPrecio('1234'), '1234.00');
    expect(parsearPrecio('0,99'), '0.99');
    expect(parsearPrecio('0.05'), '0.05');
    expect(parsearPrecio('  \$ 850 '), '850.00');
    expect(parsearPrecio('007'), '007.00');
  });

  test('no pasa por double: conserva la exactitud', () {
    expect(parsearPrecio('0.1'), '0.10');
    expect(parsearPrecio('9999999999.99'), '9999999999.99');
  });

  test('rechaza lo que no es un precio válido', () {
    for (final malo in [
      null,
      '',
      ' ',
      '0',
      '0,00',
      '-5',
      'abc',
      '12a',
      '1,234',
      '1.234,50', // separador de miles: ambiguo
      '10,999',
      ',5',
      '5,',
      '99999999999', // más de 10 dígitos enteros: no entra en numeric(12,2)
    ]) {
      expect(parsearPrecio(malo), isNull, reason: '"$malo"');
    }
  });
}
