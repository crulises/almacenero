import 'dart:async';
import 'dart:convert';

import 'package:shared_preferences/shared_preferences.dart';

import 'location_service.dart';
import 'price_repository.dart';
import 'product_repository.dart';

/// Una consulta reciente: qué es, dónde y a cuánto, tal como se vio (una **foto**). Vive solo
/// en el celular: sin red se muestra esta foto, con red se refresca.
class Reciente {
  const Reciente({
    required this.ean,
    required this.nombre,
    required this.detalle,
    required this.consultadoEn,
    required this.precio,
    required this.esReferencia,
  });

  final String ean;
  final String nombre;

  /// «Marca · 900 ml»: lo que va debajo del nombre.
  final String detalle;
  final DateTime consultadoEn;

  /// El del local más cercano. `null` = no se vio ninguno (ni en la zona ni de referencia).
  final PrecioVigente? precio;

  /// El precio NO es de la zona (está más lejos que `config.radio_precios_m`, o no había
  /// ubicación): se muestra marcado y con su distancia, nunca como un precio de acá.
  final bool esReferencia;

  Reciente conInstante(DateTime instante) => Reciente(
    ean: ean,
    nombre: nombre,
    detalle: detalle,
    consultadoEn: instante,
    precio: precio,
    esReferencia: esReferencia,
  );

  Map<String, Object?> toJson() => {
    'ean': ean,
    'nombre': nombre,
    'detalle': detalle,
    'consultado_en': consultadoEn.toUtc().toIso8601String(),
    'precio': precio?.toJson(),
    'es_referencia': esReferencia,
  };

  factory Reciente.fromJson(Map<String, dynamic> json) => Reciente(
    ean: json['ean'] as String,
    nombre: json['nombre'] as String,
    detalle: json['detalle'] as String? ?? '',
    consultadoEn: DateTime.parse(json['consultado_en'] as String),
    precio: json['precio'] == null
        ? null
        : PrecioVigente.fromJson(json['precio'] as Map<String, dynamic>),
    esReferencia: json['es_referencia'] as bool? ?? false,
  );
}

/// Arma la foto de una consulta. El precio es el del local **más cercano** (no el más barato:
/// la app es una guía de dónde y a cuánto, no un ranking). Dentro de la zona es un precio
/// normal; si no hay ninguno, se usa el de [referencia] (radio ampliado) y queda marcado.
Reciente resumirConsulta({
  required Producto producto,
  required List<PrecioVigente> zona,
  required List<PrecioVigente> referencia,
  required bool conUbicacion,
  required DateTime ahora,
}) {
  PrecioVigente? masCerca(List<PrecioVigente> ps) => ps.isEmpty
      ? null
      : ([...ps]..sort(
              (a, b) => (a.distanciaM ?? double.infinity).compareTo(
                b.distanciaM ?? double.infinity,
              ),
            ))
            .first;
  PrecioVigente? masBarato(List<PrecioVigente> ps) => ps.isEmpty
      ? null
      : ([...ps]..sort(
              (a, b) =>
                  double.parse(a.precio).compareTo(double.parse(b.precio)),
            ))
            .first;

  PrecioVigente? elegido;
  var esReferencia = false;
  if (conUbicacion) {
    elegido = masCerca(zona);
    if (elegido == null) {
      elegido = masCerca(referencia);
      esReferencia = elegido != null;
    }
  } else {
    // Sin ubicación no hay distancia: no se puede decir que es de la zona.
    elegido = masBarato(zona);
    esReferencia = elegido != null;
  }
  return Reciente(
    ean: producto.ean,
    nombre: producto.nombre,
    detalle: [?producto.marca, ?producto.tamano].join(' · '),
    consultadoEn: ahora,
    precio: elegido,
    esReferencia: esReferencia,
  );
}

/// Las últimas consultas, guardadas en el celular (SharedPreferences). **Nunca lanza**: si el
/// almacenamiento falla o los datos están rotos, se ve una lista vacía y la app sigue.
class RecientesStore {
  static const maximo = 4;
  static const _clave = 'recientes_v1';

  // Leer-modificar-escribir en fila: dos anotaciones a la vez no se pisan.
  Future<void> _fila = Future.value();

  Future<List<Reciente>> leer() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      final crudo = prefs.getString(_clave);
      if (crudo == null) return [];
      return [
        for (final j in jsonDecode(crudo) as List<dynamic>)
          Reciente.fromJson(j as Map<String, dynamic>),
      ];
    } catch (_) {
      return [];
    }
  }

  /// Anota una consulta: sin repetir EAN (reconsultar lo mueve al tope), hasta [maximo].
  /// Con `moverAlTope: false` solo reemplaza la foto de uno que ya está (el refresco con red);
  /// si ya no estaba, lo ignora.
  Future<void> registrar(Reciente r, {bool moverAlTope = true}) {
    final hecho = _fila.then((_) async {
      try {
        final lista = await leer();
        final i = lista.indexWhere((x) => x.ean == r.ean);
        if (moverAlTope) {
          if (i >= 0) lista.removeAt(i);
          lista.insert(0, r);
        } else if (i >= 0) {
          lista[i] = r;
        } else {
          return;
        }
        final prefs = await SharedPreferences.getInstance();
        await prefs.setString(
          _clave,
          jsonEncode([for (final x in lista.take(maximo)) x.toJson()]),
        );
      } catch (_) {
        // Recientes es una comodidad: si no se puede guardar, no pasa nada.
      }
    });
    _fila = hecho;
    return hecho;
  }
}

/// Refresca una consulta con red. Sin red (o sin GPS, o lento) devuelve `null` y no lanza.
class RecientesService {
  RecientesService({
    required this.loadProducto,
    required this.loadVigentes,
    required this.obtenerUbicacion,
    DateTime Function()? ahora,
    this.espera = const Duration(seconds: 10),
  }) : ahora = ahora ?? DateTime.now;

  final Future<Producto> Function(String ean) loadProducto;
  final Future<List<PrecioVigente>> Function(
    String ean, {
    Ubicacion? ubicacion,
    bool referencia,
  })
  loadVigentes;
  final Future<Ubicacion> Function() obtenerUbicacion;
  final DateTime Function() ahora;
  final Duration espera;

  Future<Reciente?> refrescar(Reciente viejo) async {
    try {
      return await _refrescar(viejo).timeout(espera);
    } catch (_) {
      return null;
    }
  }

  Future<Reciente> _refrescar(Reciente viejo) async {
    final ubicacion = await obtenerUbicacion();
    final producto = await loadProducto(viejo.ean);
    final zona = await loadVigentes(viejo.ean, ubicacion: ubicacion);
    final referencia = zona.isEmpty
        ? await loadVigentes(viejo.ean, ubicacion: ubicacion, referencia: true)
        : const <PrecioVigente>[];
    return resumirConsulta(
      producto: producto,
      zona: zona,
      referencia: referencia,
      conUbicacion: true,
      ahora: ahora(),
    ).conInstante(viejo.consultadoEn);
  }
}
