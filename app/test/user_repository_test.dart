import 'package:almacenero/data/user_repository.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('Me lee el escalón y el umbral que manda el backend', () {
    final me = Me.fromJson({
      'id': 'u1',
      'alias': 'anon-1',
      'karma': -7,
      'escalon': 'aviso',
      'umbral_restriccion': -20,
    });
    expect(me.escalon, Escalon.aviso);
    expect(me.umbralRestriccion, -20);
  });

  test('un backend viejo (sin escalón) se lee como normal', () {
    final me = Me.fromJson({'id': 'u1', 'alias': 'a', 'karma': 3});
    expect(me.escalon, Escalon.normal);
  });

  test('restringido', () {
    final me = Me.fromJson({
      'id': 'u1',
      'alias': 'a',
      'karma': -30,
      'escalon': 'restringido',
      'umbral_restriccion': -15,
    });
    expect(me.escalon, Escalon.restringido);
  });
}
