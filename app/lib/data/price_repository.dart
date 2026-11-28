import 'api_client.dart';
import 'authed_api.dart';
import 'location_service.dart';

/// Resultado de cargar un precio: su id y el karma ya actualizado del usuario.
class PrecioCargado {
  const PrecioCargado({
    required this.precioId,
    required this.karma,
    this.primerPrecio = false,
    this.karmaSumado = 0,
  });

  final String precioId;
  final int karma;

  /// Fue el primer precio de ese producto en cualquier local (lleva bonus de karma).
  final bool primerPrecio;
  final int karmaSumado;

  factory PrecioCargado.fromJson(Map<String, dynamic> json) => PrecioCargado(
    precioId: json['precio_id'] as String,
    karma: json['karma'] as int,
    primerPrecio: json['primer_precio'] as bool? ?? false,
    karmaSumado: json['karma_sumado'] as int? ?? 0,
  );
}

/// Un precio ya cargado, del historial de un producto.
class PrecioHistorial {
  const PrecioHistorial({
    required this.id,
    required this.localId,
    required this.localNombre,
    required this.precio,
    required this.fecha,
  });

  final String id;
  final String localId;
  final String localNombre;

  /// Formato canónico, p. ej. "1234.50" (el backend lo manda como string).
  final String precio;
  final DateTime fecha;

  factory PrecioHistorial.fromJson(Map<String, dynamic> json) =>
      PrecioHistorial(
        id: json['id'] as String,
        localId: json['local_id'] as String,
        localNombre: json['local_nombre'] as String,
        precio: json['precio'].toString(),
        fecha: DateTime.parse(json['fecha'] as String),
      );
}

/// Un local verificado entre los que se puede ver el historial de un producto, con su último
/// precio de ese producto (si tiene).
class LocalDelProducto {
  const LocalDelProducto({
    required this.localId,
    required this.localNombre,
    required this.lat,
    required this.lng,
    this.distanciaM,
    this.ultimoPrecio,
    this.fecha,
  });

  final String localId;
  final String localNombre;
  final double lat;
  final double lng;

  /// Solo viene si se pidió con ubicación.
  final double? distanciaM;

  /// Formato canónico, p. ej. "1234.50"; nulo si el local no tiene precios del producto.
  final String? ultimoPrecio;
  final DateTime? fecha;

  bool get tienePrecios => ultimoPrecio != null;

  factory LocalDelProducto.fromJson(Map<String, dynamic> json) =>
      LocalDelProducto(
        localId: json['local_id'] as String,
        localNombre: json['local_nombre'] as String,
        lat: (json['lat'] as num).toDouble(),
        lng: (json['lng'] as num).toDouble(),
        distanciaM: (json['distancia_m'] as num?)?.toDouble(),
        ultimoPrecio: json['ultimo_precio']?.toString(),
        fecha: json['fecha'] == null
            ? null
            : DateTime.parse(json['fecha'] as String),
      );
}

/// El último precio de un producto en un local, con su frescura (la calcula el
/// backend con los umbrales de `config`).
class PrecioVigente {
  const PrecioVigente({
    required this.localId,
    required this.localNombre,
    required this.localVerificado,
    required this.lat,
    required this.lng,
    required this.precio,
    required this.fecha,
    required this.edadDias,
    required this.frescura,
    required this.vencido,
    this.distanciaM,
  });

  final String localId;
  final String localNombre;
  final bool localVerificado;
  final double lat;
  final double lng;

  /// Formato canónico, p. ej. "1234.50".
  final String precio;
  final DateTime fecha;
  final int edadDias;

  /// `verde`, `amarillo` o `rojo`.
  final String frescura;

  /// Más viejo que la ventana de frescura.
  final bool vencido;

  /// Distancia al usuario; solo viene si se pidió con ubicación.
  final double? distanciaM;

  factory PrecioVigente.fromJson(Map<String, dynamic> json) => PrecioVigente(
    localId: json['local_id'] as String,
    localNombre: json['local_nombre'] as String,
    localVerificado: json['local_verificado'] as bool? ?? true,
    lat: (json['lat'] as num).toDouble(),
    lng: (json['lng'] as num).toDouble(),
    precio: json['precio'].toString(),
    fecha: DateTime.parse(json['fecha'] as String),
    edadDias: json['edad_dias'] as int,
    frescura: json['frescura'] as String,
    vencido: json['vencido'] as bool? ?? false,
    distanciaM: (json['distancia_m'] as num?)?.toDouble(),
  );

  /// Para guardarlo en el celular (Recientes): mismas claves que manda el backend.
  Map<String, Object?> toJson() => {
    'local_id': localId,
    'local_nombre': localNombre,
    'local_verificado': localVerificado,
    'lat': lat,
    'lng': lng,
    'precio': precio,
    'fecha': fecha.toUtc().toIso8601String(),
    'edad_dias': edadDias,
    'frescura': frescura,
    'vencido': vencido,
    'distancia_m': distanciaM,
  };
}

/// Por qué falló la carga de un precio.
enum CargaError {
  noEncontrado,
  precioInvalido,

  /// Estás lejos del local (geofence).
  fueraDeRango,

  /// El GPS no es lo bastante preciso: esperar y reintentar.
  precisionBaja,

  /// Llegaste al tope de cargas por hora o por día (anti-spam).
  limite,

  /// Karma muy bajo: puede consultar, no cargar.
  cuentaRestringida,

  /// La cuenta fue dada de baja.
  cuentaBaja,
  otro,
}

CargaError clasificarErrorCarga(Object error) {
  if (error is ApiException) {
    if (error.statusCode == 404) return CargaError.noEncontrado;
    if (error.statusCode == 422) return CargaError.precioInvalido;
    if (error.isRateLimited) return CargaError.limite;
    if (error.statusCode == 403) {
      return switch (_codigo(error)) {
        'fuera_de_rango' => CargaError.fueraDeRango,
        'precision_baja' => CargaError.precisionBaja,
        'cuenta_restringida' => CargaError.cuentaRestringida,
        'cuenta_baja' => CargaError.cuentaBaja,
        _ => CargaError.otro,
      };
    }
  }
  return CargaError.otro;
}

String? _codigo(ApiException e) {
  final d = e.detail;
  return d is Map ? d['codigo'] as String? : null;
}

/// A cuántos metros del local estabas, cuando la carga se rechazó por lejos.
int? distanciaFueraDeRango(Object error) {
  if (error is! ApiException) return null;
  final d = error.detail;
  return d is Map ? (d['distancia_m'] as num?)?.round() : null;
}

class PriceRepository {
  PriceRepository({required this._api});

  final AuthedApi _api;

  /// Carga el precio de un producto en un local. [precio] ya viene en formato
  /// canónico (ver `parsearPrecio`). Suma karma al usuario.
  Future<PrecioCargado> cargar({
    required String ean,
    required String localId,
    required String precio,
    required Ubicacion ubicacion,
  }) async => PrecioCargado.fromJson(
    await _api.post('/precios', {
      'ean': ean,
      'local_id': localId,
      'precio': precio,
      // Dónde está el usuario: el backend valida que esté cerca del local.
      'lat': ubicacion.lat,
      'lng': ubicacion.lng,
      'precision_m': ubicacion.precisionM,
    }),
  );

  /// Precios cargados de un producto, el más nuevo primero.
  Future<List<PrecioHistorial>> historial(String ean) async => [
    for (final p in await _api.getList('/productos/$ean/precios'))
      PrecioHistorial.fromJson(p as Map<String, dynamic>),
  ];

  /// Precios de un producto en un solo local, el más nuevo primero.
  Future<List<PrecioHistorial>> historialDeLocal(
    String ean,
    String localId,
  ) async => [
    for (final p in await _api.getList(
      '/productos/$ean/precios?local_id=$localId',
    ))
      PrecioHistorial.fromJson(p as Map<String, dynamic>),
  ];

  /// Los locales verificados entre los que se puede elegir (ver el endpoint). Con
  /// [ubicacion]: los cercanos, tengan o no precio, por distancia; sin ella: solo los
  /// que tienen precio, el más reciente primero.
  Future<List<LocalDelProducto>> localesDelProducto(
    String ean, {
    Ubicacion? ubicacion,
  }) async {
    final consulta = ubicacion == null
        ? ''
        : '?lat=${ubicacion.lat}&lng=${ubicacion.lng}';
    return [
      for (final l in await _api.getList('/productos/$ean/locales$consulta'))
        LocalDelProducto.fromJson(l as Map<String, dynamic>),
    ];
  }

  /// El último precio de cada local, del más barato al más caro. Con [ubicacion]
  /// el backend trae solo los locales dentro del radio configurado (`config`) y la
  /// distancia a cada uno; sin ella, todos. Con [referencia] el radio es el ampliado de
  /// `config.radio_referencia_km` (lo de ahí NO es un precio de la zona: marcarlo así).
  Future<List<PrecioVigente>> vigentes(
    String ean, {
    Ubicacion? ubicacion,
    bool referencia = false,
  }) async {
    final consulta = ubicacion == null
        ? ''
        : '?lat=${ubicacion.lat}&lng=${ubicacion.lng}'
              '${referencia ? '&referencia=true' : ''}';
    return [
      for (final p in await _api.getList(
        '/productos/$ean/precios/vigentes$consulta',
      ))
        PrecioVigente.fromJson(p as Map<String, dynamic>),
    ];
  }
}
