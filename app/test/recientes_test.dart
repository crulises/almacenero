import 'package:almacenero/data/location_service.dart';
import 'package:almacenero/data/price_repository.dart';
import 'package:almacenero/data/product_repository.dart';
import 'package:almacenero/data/recientes.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

const _aceite = Producto(
  id: 'p1',
  ean: '7790070411112',
  nombre: 'Aceite de girasol',
  marca: 'Ejemplo',
  tamanoValor: 900,
  tamanoUnidad: 'ml',
);
final _ahora = DateTime.utc(2026, 11, 25, 12);

PrecioVigente vig(String local, String precio, {double? dist, int edad = 0}) =>
    PrecioVigente(
      localId: local,
      localNombre: 'Local $local',
      localVerificado: true,
      lat: -34.6,
      lng: -58.4,
      precio: precio,
      fecha: _ahora.subtract(Duration(days: edad)),
      edadDias: edad,
      frescura: 'verde',
      vencido: false,
      distanciaM: dist,
    );

Reciente rec(String ean, {String nombre = 'X'}) => Reciente(
  ean: ean,
  nombre: nombre,
  detalle: '',
  consultadoEn: _ahora,
  precio: null,
  esReferencia: false,
);

void main() {
  group('resumirConsulta', () {
    test(
      'con precios en la zona toma el del local MÁS CERCANO, no el barato',
      () {
        final r = resumirConsulta(
          producto: _aceite,
          zona: [vig('a', '100', dist: 900), vig('b', '50', dist: 3000)],
          referencia: const [],
          conUbicacion: true,
          ahora: _ahora,
        );
        expect(r.precio!.localId, 'a');
        expect(r.esReferencia, isFalse);
        expect(r.nombre, 'Aceite de girasol');
        expect(r.detalle, 'Ejemplo · 900 ml');
      },
    );

    test(
      'sin nada en la zona amplía y lo MARCA como referencia con su distancia',
      () {
        final r = resumirConsulta(
          producto: _aceite,
          zona: const [],
          referencia: [
            vig('lejos', '80', dist: 120000),
            vig('mas', '70', dist: 250000),
          ],
          conUbicacion: true,
          ahora: _ahora,
        );
        expect(r.precio!.localId, 'lejos');
        expect(r.esReferencia, isTrue);
        expect(r.precio!.distanciaM, 120000);
      },
    );

    test(
      'sin precios en ningún radio: sin precio (la pantalla invita a cargar)',
      () {
        final r = resumirConsulta(
          producto: _aceite,
          zona: const [],
          referencia: const [],
          conUbicacion: true,
          ahora: _ahora,
        );
        expect(r.precio, isNull);
      },
    );

    test('sin ubicación no hay distancia: el precio es referencia', () {
      final r = resumirConsulta(
        producto: _aceite,
        zona: [vig('a', '100'), vig('b', '90')],
        referencia: const [],
        conUbicacion: false,
        ahora: _ahora,
      );
      expect(r.precio!.localId, 'b'); // sin distancia, el más barato
      expect(r.esReferencia, isTrue);
    });
  });

  test('Reciente va y vuelve por JSON sin perder nada', () {
    final r = Reciente(
      ean: _aceite.ean,
      nombre: 'Aceite',
      detalle: '900 ml',
      consultadoEn: _ahora,
      precio: vig('a', '100.50', dist: 350.5, edad: 3),
      esReferencia: true,
    );
    final vuelta = Reciente.fromJson(r.toJson());
    expect(vuelta.toJson(), r.toJson());
    expect(vuelta.precio!.distanciaM, 350.5);
    expect(vuelta.precio!.fecha, r.precio!.fecha);
    expect(vuelta.esReferencia, isTrue);
  });

  group('RecientesStore', () {
    setUp(() => SharedPreferences.setMockInitialValues({}));

    test('guarda hasta 4, el último consultado primero', () async {
      final s = RecientesStore();
      for (final e in ['1', '2', '3', '4', '5']) {
        await s.registrar(rec(e));
      }
      expect((await s.leer()).map((r) => r.ean), ['5', '4', '3', '2']);
    });

    test('reconsultar un EAN no lo repite: lo mueve al tope', () async {
      final s = RecientesStore();
      for (final e in ['1', '2', '3']) {
        await s.registrar(rec(e));
      }
      await s.registrar(rec('1', nombre: 'nuevo'));
      final r = await s.leer();
      expect(r.map((x) => x.ean), ['1', '3', '2']);
      expect(r.first.nombre, 'nuevo');
    });

    test('actualizar reemplaza en el lugar, sin mover ni resucitar', () async {
      final s = RecientesStore();
      for (final e in ['1', '2', '3']) {
        await s.registrar(rec(e));
      }
      await s.registrar(rec('2', nombre: 'fresco'), moverAlTope: false);
      await s.registrar(
        rec('9'),
        moverAlTope: false,
      ); // ya no estaba: se ignora
      final r = await s.leer();
      expect(r.map((x) => x.ean), ['3', '2', '1']);
      expect(r[1].nombre, 'fresco');
    });

    test('datos corruptos no rompen: lista vacía', () async {
      SharedPreferences.setMockInitialValues({
        'recientes_v1': 'esto no es json',
      });
      expect(await RecientesStore().leer(), isEmpty);
      await RecientesStore().registrar(rec('1')); // y sigue andando
      expect(await RecientesStore().leer(), hasLength(1));
    });

    test('dos registros a la vez no se pisan', () async {
      final s = RecientesStore();
      await Future.wait([s.registrar(rec('1')), s.registrar(rec('2'))]);
      expect((await s.leer()).map((r) => r.ean).toSet(), {'1', '2'});
    });
  });

  group('RecientesService.refrescar', () {
    RecientesService servicio({
      Future<Producto> Function(String)? producto,
      Future<List<PrecioVigente>> Function(
        String, {
        Ubicacion? ubicacion,
        bool referencia,
      })?
      vigentes,
      Future<Ubicacion> Function()? ubicacion,
    }) => RecientesService(
      loadProducto: producto ?? (_) async => _aceite,
      loadVigentes:
          vigentes ?? (_, {ubicacion, referencia = false}) async => [],
      obtenerUbicacion:
          ubicacion ??
          () async => const Ubicacion(lat: 0, lng: 0, precisionM: 5),
      ahora: () => _ahora,
    );

    test(
      'con red trae lo nuevo y conserva el instante de la consulta',
      () async {
        final viejo = rec(_aceite.ean).conInstante(DateTime.utc(2026, 11, 1));
        final s = servicio(
          vigentes: (_, {ubicacion, referencia = false}) async =>
              referencia ? [] : [vig('a', '10', dist: 100)],
        );
        final nuevo = (await s.refrescar(viejo))!;
        expect(nuevo.precio!.precio, '10');
        expect(nuevo.consultadoEn, DateTime.utc(2026, 11, 1));
      },
    );

    test('zona vacía: pide la referencia', () async {
      final pedidos = <bool>[];
      final s = servicio(
        vigentes: (_, {ubicacion, referencia = false}) async {
          pedidos.add(referencia);
          return referencia ? [vig('lejos', '5', dist: 120000)] : [];
        },
      );
      final nuevo = (await s.refrescar(rec(_aceite.ean)))!;
      expect(pedidos, [false, true]);
      expect(nuevo.esReferencia, isTrue);
    });

    test('sin red (o sin GPS) devuelve null y NO lanza', () async {
      final s = servicio(producto: (_) async => throw Exception('sin red'));
      expect(await s.refrescar(rec(_aceite.ean)), isNull);
      final g = servicio(ubicacion: () async => throw Exception('gps'));
      expect(await g.refrescar(rec(_aceite.ean)), isNull);
    });
  });
}
