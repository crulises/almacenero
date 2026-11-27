import 'package:almacenero/data/price_repository.dart';
import 'package:almacenero/domain/historial.dart';
import 'package:flutter_test/flutter_test.dart';

PrecioHistorial _p(String precio, int dia) => PrecioHistorial(
  id: '$precio-$dia',
  localId: 'l1',
  localNombre: 'Local',
  precio: precio,
  fecha: DateTime.utc(2026, 11, dia),
);

void main() {
  group('conVariacion', () {
    test(
      'compara contra el anterior en el tiempo y devuelve el más nuevo primero',
      () {
        // Llega más nuevo primero: 99 (día 3), 110 (día 2), 100 (día 1).
        final r = conVariacion([
          _p('99.00', 3),
          _p('110.00', 2),
          _p('100.00', 1),
        ]);

        expect(r.map((x) => x.precio.precio), ['99.00', '110.00', '100.00']);
        expect(r[0].variacionPct, closeTo(-10, 0.001));
        expect(r[1].variacionPct, closeTo(10, 0.001));
        expect(r[2].variacionPct, isNull);
      },
    );

    test('un solo precio no tiene variación', () {
      expect(conVariacion([_p('100.00', 1)]).single.variacionPct, isNull);
    });

    test('mismo precio dos veces da 0', () {
      final r = conVariacion([_p('100.00', 2), _p('100.00', 1)]);
      expect(r.first.variacionPct, 0);
    });

    test('la entrada desordenada da lo mismo que ordenada', () {
      final ordenada = conVariacion([
        _p('120.00', 3),
        _p('110.00', 2),
        _p('100.00', 1),
      ]);
      final desordenada = conVariacion([
        _p('100.00', 1),
        _p('120.00', 3),
        _p('110.00', 2),
      ]);
      expect(
        desordenada.map((x) => (x.precio.id, x.variacionPct)),
        ordenada.map((x) => (x.precio.id, x.variacionPct)),
      );
    });

    test('lista vacía', () => expect(conVariacion([]), isEmpty));
  });

  test('etiquetaVariacion', () {
    expect(etiquetaVariacion(8.4), 'subió 8%');
    expect(etiquetaVariacion(-12.2), 'bajó 12%');
    expect(etiquetaVariacion(0.2), 'sin cambios');
    expect(etiquetaVariacion(0), 'sin cambios');
    expect(etiquetaVariacion(null), '');
  });

  group('rangoEje', () {
    test('todos iguales: nunca rango cero', () {
      final r = rangoEje([100, 100, 100]);
      expect(r.min, lessThan(100));
      expect(r.max, greaterThan(100));
    });

    test('un solo valor', () {
      final r = rangoEje([100]);
      expect(r.max - r.min, greaterThan(0));
    });

    test('margen del 10 % del rango', () {
      final r = rangoEje([100, 200]);
      expect(r.min, closeTo(90, 0.001));
      expect(r.max, closeTo(210, 0.001));
    });
  });
}
