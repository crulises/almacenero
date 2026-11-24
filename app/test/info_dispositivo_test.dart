import 'package:almacenero/data/info_dispositivo.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('junta lo que se pudo leer', () async {
    final d = await armarDatosApertura({
      'marca': () async => 'Google',
      'sdk': () async => 34,
    });
    expect(d, {'marca': 'Google', 'sdk': 34});
  });

  test('si una lectura falla, se omite y el resto llega', () async {
    final d = await armarDatosApertura({
      'marca': () async => throw Exception('no hay'),
      'modelo': () async => 'Pixel 7',
    });
    expect(d, {'modelo': 'Pixel 7'});
  });

  test('una lectura que cuelga se corta y no demora a las demás', () async {
    final d = await armarDatosApertura({
      'red': () => Future<Object?>.delayed(const Duration(seconds: 30)),
      'idioma': () async => 'es-AR',
    }, esperaMaxima: const Duration(milliseconds: 30));
    expect(d, {'idioma': 'es-AR'});
  });

  test('los textos largos se recortan y los vacíos se omiten', () async {
    final d = await armarDatosApertura({
      'modelo': () async => 'x' * 200,
      'marca': () async => '  ',
    });
    expect((d['modelo']! as String).length, 60);
    expect(d.containsKey('marca'), isFalse);
  });

  test('traduce el tipo de red', () {
    expect(nombreDeRed(['wifi']), 'wifi');
    expect(nombreDeRed(['mobile']), 'movil');
    expect(nombreDeRed(['none']), 'ninguna');
    expect(nombreDeRed(['vpn', 'wifi']), 'wifi'); // la VPN va sobre otra red
    expect(nombreDeRed(['bluetooth']), 'otra');
    expect(nombreDeRed([]), 'ninguna');
  });
}
