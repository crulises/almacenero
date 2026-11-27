import 'package:flutter_map/flutter_map.dart';
import 'package:latlong2/latlong.dart';
import 'package:material_ui/material_ui.dart';

import '../data/location_service.dart';

/// Mapa de un local: un cartel «Local» donde está y, si se conoce, un «Vos» donde está
/// parada la persona. Sin ubicación del usuario solo se ve el local.
class MapaLocal extends StatelessWidget {
  const MapaLocal({
    super.key,
    required this.localLat,
    required this.localLng,
    this.usuario,
  });

  final double localLat;
  final double localLng;
  final Ubicacion? usuario;

  @override
  Widget build(BuildContext context) {
    final local = LatLng(localLat, localLng);
    final vos = usuario == null ? null : LatLng(usuario!.lat, usuario!.lng);
    final colores = Theme.of(context).colorScheme;
    return ClipRRect(
      borderRadius: BorderRadius.circular(12),
      child: FlutterMap(
        // La clave fuerza un mapa nuevo (y su encuadre) cuando cambia el local.
        key: ValueKey('mapa-$localLat-$localLng'),
        options: MapOptions(
          initialCameraFit: vos == null
              ? null
              : CameraFit.coordinates(
                  coordinates: [local, vos],
                  padding: const EdgeInsets.all(56),
                  maxZoom: 16,
                ),
          initialCenter: local,
          initialZoom: 16,
          interactionOptions: const InteractionOptions(
            flags: InteractiveFlag.all & ~InteractiveFlag.rotate,
          ),
        ),
        children: [
          TileLayer(
            urlTemplate: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
            userAgentPackageName: 'dev.crulises.almacenero',
          ),
          MarkerLayer(
            markers: [
              if (vos != null)
                Marker(
                  point: vos,
                  width: 64,
                  height: 42,
                  alignment: Alignment.topCenter,
                  child: _Cartel('Vos', colores.tertiary, colores.onTertiary),
                ),
              Marker(
                point: local,
                width: 64,
                height: 42,
                alignment: Alignment.topCenter,
                child: _Cartel('Local', colores.primary, colores.onPrimary),
              ),
            ],
          ),
          const SimpleAttributionWidget(
            source: Text('© OpenStreetMap contributors'),
          ),
        ],
      ),
    );
  }
}

class _Cartel extends StatelessWidget {
  const _Cartel(this.texto, this.fondo, this.letra);

  final String texto;
  final Color fondo;
  final Color letra;

  @override
  Widget build(BuildContext context) {
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        Container(
          height: 26,
          alignment: Alignment.center,
          padding: const EdgeInsets.symmetric(horizontal: 8),
          decoration: BoxDecoration(
            color: fondo,
            borderRadius: BorderRadius.circular(13),
            border: Border.all(color: Colors.white, width: 1.5),
            boxShadow: [
              BoxShadow(
                color: Colors.black.withValues(alpha: 0.25),
                blurRadius: 2,
              ),
            ],
          ),
          child: Text(
            texto,
            style: TextStyle(
              color: letra,
              fontWeight: FontWeight.bold,
              fontSize: 12,
            ),
          ),
        ),
        Icon(Icons.arrow_drop_down, color: fondo, size: 14),
      ],
    );
  }
}
