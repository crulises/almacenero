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

  test('formatearPrecio: miles con punto y coma decimal', () {
    expect(formatearPrecio('1234.50'), r'$ 1.234,50');
    expect(formatearPrecio('0.99'), r'$ 0,99');
    expect(formatearPrecio('999.00'), r'$ 999,00');
    expect(formatearPrecio('1234567.05'), r'$ 1.234.567,05');
  });

  test('formatearFecha: día y antigüedad', () {
    final ahora = DateTime(2026, 11, 15, 10);
    expect(
      formatearFecha(DateTime(2026, 11, 15, 8), ahora: ahora),
      '15/11/2026 (hoy)',
    );
    expect(
      formatearFecha(DateTime(2026, 11, 14, 23), ahora: ahora),
      '14/11/2026 (ayer)',
    );
    expect(
      formatearFecha(DateTime(2026, 11, 2), ahora: ahora),
      '02/11/2026 (hace 13 días)',
    );
  });

  test('formatearPrecioCorto: sin centavos si son cero', () {
    expect(formatearPrecioCorto('1234.00'), r'$ 1.234');
    expect(formatearPrecioCorto('1234.50'), r'$ 1.234,50');
    expect(formatearPrecioCorto('0.99'), r'$ 0,99');
  });

  test('formatearDistancia: metros o kilómetros', () {
    expect(formatearDistancia(350.4), '350 m');
    expect(formatearDistancia(1449), '1,4 km');
    expect(
      formatearDistancia(120000),
      '120 km',
    ); // lejos no hace falta el decimal
  });
}
