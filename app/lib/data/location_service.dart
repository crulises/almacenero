import 'package:geolocator/geolocator.dart';

/// Dónde está parado el usuario.
class Ubicacion {
  const Ubicacion({required this.lat, required this.lng, this.precisionM = 0});

  final double lat;
  final double lng;

  /// Precisión del GPS, en metros (para el geofence).
  final double precisionM;
}

/// Por qué no se pudo obtener la ubicación.
enum UbicacionError {
  /// El usuario negó el permiso (esta vez).
  permisoDenegado,

  /// Negado para siempre: solo se arregla desde los ajustes del teléfono.
  permisoDenegadoParaSiempre,

  /// El GPS del teléfono está apagado.
  servicioApagado,

  /// Tardó demasiado o falló por otra razón.
  otro,
}

class UbicacionException implements Exception {
  const UbicacionException(this.tipo);

  final UbicacionError tipo;

  @override
  String toString() => 'UbicacionException($tipo)';
}

UbicacionError clasificarErrorUbicacion(Object error) =>
    error is UbicacionException ? error.tipo : UbicacionError.otro;

/// Pide permiso y lee el GPS. Es lo único que toca `geolocator`, así el resto de la
/// app (y los tests) trabajan con [Ubicacion] y funciones.
class LocationService {
  Future<Ubicacion> actual() async {
    if (!await Geolocator.isLocationServiceEnabled()) {
      throw const UbicacionException(UbicacionError.servicioApagado);
    }
    var permiso = await Geolocator.checkPermission();
    if (permiso == LocationPermission.denied) {
      permiso = await Geolocator.requestPermission();
    }
    if (permiso == LocationPermission.deniedForever) {
      throw const UbicacionException(UbicacionError.permisoDenegadoParaSiempre);
    }
    if (permiso == LocationPermission.denied) {
      throw const UbicacionException(UbicacionError.permisoDenegado);
    }
    try {
      final p = await Geolocator.getCurrentPosition(
        locationSettings: const LocationSettings(
          accuracy: LocationAccuracy.high,
          timeLimit: Duration(seconds: 20),
        ),
      );
      return Ubicacion(
        lat: p.latitude,
        lng: p.longitude,
        precisionM: p.accuracy,
      );
    } on Object {
      throw const UbicacionException(UbicacionError.otro);
    }
  }

  /// Abre los ajustes de la app (para dar el permiso a mano).
  Future<void> abrirAjustes() => Geolocator.openAppSettings();

  /// Abre los ajustes de ubicación (para prender el GPS).
  Future<void> abrirAjustesDeUbicacion() => Geolocator.openLocationSettings();
}
