import 'dart:async';

import 'package:almacenero/data/cola_eventos.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  late List<List<Map<String, Object?>>> enviados;

  ColaEventos cola({
    Future<void> Function(List<Map<String, Object?>>)? enviar,
    int maxEnCola = 200,
    Duration espera = const Duration(milliseconds: 50),
    Duration? envioEn, // null: no se manda solo (los tests llaman a vaciar)
  }) => ColaEventos(
    enviar:
        enviar ??
        (lote) async {
          enviados.add(lote);
        },
    maxEnCola: maxEnCola,
    esperaMaxima: espera,
    envioEn: envioEn,
  );

  setUp(() => enviados = []);

  test(
    'registrar no espera nada y vaciar manda tipo, datos y reloj del cliente',
    () async {
      final c = cola();
      c.registrar('producto.escaneado', {
        'ean': '7790070411112',
        'encontrado': true,
      });
      expect(enviados, isEmpty); // registrar nunca manda en el momento
      await c.vaciar();
      expect(enviados, hasLength(1));
      final e = enviados.single.single;
      expect(e['tipo'], 'producto.escaneado');
      expect(e['datos'], {'ean': '7790070411112', 'encontrado': true});
      expect(DateTime.parse(e['ocurrio_en_cliente']! as String).isUtc, isTrue);
      expect(c.pendientes, 0);
    },
  );

  test('manda de a 50 como máximo por pedido', () async {
    final c = cola();
    for (var i = 0; i < 120; i++) {
      c.registrar('app.abierta');
    }
    await c.vaciar();
    expect(enviados.map((l) => l.length), [50, 50, 20]);
  });

  test(
    'si el envío falla, descarta el lote, no lanza y sigue andando',
    () async {
      var llamadas = 0;
      final c = cola(
        enviar: (lote) async {
          llamadas++;
          throw Exception('sin red');
        },
      );
      c.registrar('app.abierta');
      await c.vaciar(); // no tiene que lanzar
      expect(c.pendientes, 0);
      expect(llamadas, 1); // no reintenta: descarta
      c.registrar('app.abierta');
      expect(c.pendientes, 1); // y sigue aceptando eventos nuevos
    },
  );

  test('si enviar lanza de forma síncrona tampoco rompe', () async {
    final c = cola(enviar: (_) => throw StateError('mal'));
    c.registrar('app.abierta');
    await c.vaciar();
    expect(c.pendientes, 0);
  });

  test('si el servidor no contesta, se corta por tiempo y descarta', () async {
    final c = cola(
      enviar: (_) => Completer<void>().future, // nunca termina
      espera: const Duration(milliseconds: 20),
    );
    c.registrar('app.abierta');
    await c.vaciar().timeout(const Duration(seconds: 2));
    expect(c.pendientes, 0);
  });

  test('con más de maxEnCola se descartan los más viejos', () async {
    final c = cola(maxEnCola: 3);
    for (var i = 0; i < 5; i++) {
      c.registrar('producto.escaneado', {
        'ean': '1234567$i',
        'encontrado': true,
      });
    }
    expect(c.pendientes, 3);
    await c.vaciar();
    final eans = enviados.single
        .map((e) => (e['datos']! as Map)['ean'])
        .toList();
    expect(eans, ['12345672', '12345673', '12345674']);
  });

  test('dos vaciar a la vez no mandan lo mismo dos veces', () async {
    final liberar = Completer<void>();
    var llamadas = 0;
    final c = cola(
      enviar: (_) async {
        llamadas++;
        await liberar.future;
      },
      espera: const Duration(seconds: 5),
    );
    c.registrar('app.abierta');
    final a = c.vaciar();
    final b = c.vaciar();
    liberar.complete();
    await Future.wait([a, b]);
    expect(llamadas, 1);
  });

  test('vaciar con la cola vacía no hace ningún pedido', () async {
    final c = cola();
    await c.vaciar();
    expect(enviados, isEmpty);
  });

  test(
    'manda solo, poco después del último evento, y en un único lote',
    () async {
      final c = cola(envioEn: const Duration(milliseconds: 40));
      c.registrar('app.abierta');
      c.registrar('producto.escaneado', {
        'ean': '7790070411112',
        'encontrado': true,
      });
      expect(enviados, isEmpty); // todavía no: junta un ratito
      await Future<void>.delayed(const Duration(milliseconds: 200));
      expect(enviados, hasLength(1));
      expect(enviados.single.map((e) => e['tipo']), [
        'app.abierta',
        'producto.escaneado',
      ]);
      // y un evento posterior arma otro envío
      c.registrar('app.abierta');
      await Future<void>.delayed(const Duration(milliseconds: 200));
      expect(enviados, hasLength(2));
    },
  );

  test(
    'si falla el envío automático, tampoco hay error ni se traba el próximo',
    () async {
      var llamadas = 0;
      final c = cola(
        envioEn: const Duration(milliseconds: 20),
        enviar: (_) async {
          llamadas++;
          throw Exception('sin red');
        },
      );
      c.registrar('app.abierta');
      await Future<void>.delayed(const Duration(milliseconds: 150));
      c.registrar('app.abierta');
      await Future<void>.delayed(const Duration(milliseconds: 150));
      expect(llamadas, 2);
      expect(c.pendientes, 0);
    },
  );
}
