import 'package:almacenero/data/aviso_ligar.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  late DateTime now;

  Future<AvisoLigar> build() async {
    final prefs = await SharedPreferences.getInstance();
    return AvisoLigar(prefs, now: () => now);
  }

  setUp(() {
    now = DateTime(2026, 11, 26, 12);
    SharedPreferences.setMockInitialValues({});
  });

  test('sin tocar «Luego» no está oculto', () async {
    expect((await build()).estaOculto(), false);
  });

  test('«Luego» la oculta 7 días y al octavo vuelve a mostrarse', () async {
    final aviso = await build();
    await aviso.ocultarSieteDias();

    expect(aviso.estaOculto(), true);
    now = now.add(const Duration(days: 6, hours: 23));
    expect(aviso.estaOculto(), true);
    now = now.add(const Duration(hours: 2));
    expect(aviso.estaOculto(), false);
  });

  test('sobrevive a cerrar la app', () async {
    await (await build()).ocultarSieteDias();
    expect((await build()).estaOculto(), true);
  });
}
