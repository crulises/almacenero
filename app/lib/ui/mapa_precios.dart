import 'dart:math' as math;

import 'package:flutter_map/flutter_map.dart';
import 'package:latlong2/latlong.dart';
import 'package:material_ui/material_ui.dart';

import '../data/price_repository.dart';
import '../domain/precio.dart';
import 'frescura.dart';

/// Mapa con un cartel de precio por local, coloreado por frescura. El local
/// elegido (desde el mapa o desde la lista) se resalta y el mapa se centra en él.
class MapaPrecios extends StatefulWidget {
  const MapaPrecios({
    super.key,
    required this.precios,
    required this.seleccionado,
    required this.onSeleccion,
  });

  final List<PrecioVigente> precios;

  /// `localId` del precio resaltado.
  final String? seleccionado;
  final ValueChanged<String> onSeleccion;

  @override
  State<MapaPrecios> createState() => _MapaPreciosState();
}

class _MapaPreciosState extends State<MapaPrecios> {
  final _controller = MapController();

  LatLng _punto(PrecioVigente p) => LatLng(p.lat, p.lng);

  @override
  void didUpdateWidget(MapaPrecios anterior) {
    super.didUpdateWidget(anterior);
    final id = widget.seleccionado;
    if (id == null || id == anterior.seleccionado) return;
    final elegido = widget.precios.where((p) => p.localId == id);
    if (elegido.isEmpty) return;
    // Centra en el local elegido sin alejar el zoom que ya tenía el usuario.
    final zoom = math.max(_controller.camera.zoom, 15.0);
    _controller.move(_punto(elegido.first), zoom);
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final puntos = [for (final p in widget.precios) _punto(p)];
    return ClipRRect(
      borderRadius: BorderRadius.circular(12),
      child: FlutterMap(
        mapController: _controller,
        options: MapOptions(
          initialCameraFit: CameraFit.coordinates(
            coordinates: puntos,
            padding: const EdgeInsets.fromLTRB(56, 56, 56, 56),
            maxZoom: 16,
          ),
          interactionOptions: const InteractionOptions(
            flags: InteractiveFlag.all & ~InteractiveFlag.rotate,
          ),
        ),
        children: [
          TileLayer(
            urlTemplate: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
            userAgentPackageName: 'ar.almacenero.almacenero',
          ),
          MarkerLayer(
            markers: [
              // El elegido va último para quedar por encima de los demás.
              for (final p in [
                ...widget.precios.where(
                  (p) => p.localId != widget.seleccionado,
                ),
                ...widget.precios.where(
                  (p) => p.localId == widget.seleccionado,
                ),
              ])
                Marker(
                  point: _punto(p),
                  width: 92,
                  height: 40,
                  child: _Cartel(
                    precio: p,
                    elegido: p.localId == widget.seleccionado,
                    onTap: () => widget.onSeleccion(p.localId),
                  ),
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
  const _Cartel({
    required this.precio,
    required this.elegido,
    required this.onTap,
  });

  final PrecioVigente precio;
  final bool elegido;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      child: Container(
        key: ValueKey('cartel-${precio.localId}${elegido ? '-elegido' : ''}'),
        alignment: Alignment.center,
        padding: const EdgeInsets.symmetric(horizontal: 8),
        decoration: BoxDecoration(
          color: colorFrescura(precio),
          borderRadius: BorderRadius.circular(20),
          border: Border.all(color: Colors.white, width: elegido ? 3 : 1.5),
          boxShadow: [
            BoxShadow(
              color: Colors.black.withValues(alpha: elegido ? 0.5 : 0.25),
              blurRadius: elegido ? 8 : 3,
            ),
          ],
        ),
        child: Text(
          formatearPrecioCorto(precio.precio),
          maxLines: 1,
          style: TextStyle(
            color: Colors.white,
            fontWeight: FontWeight.bold,
            fontSize: elegido ? 16 : 13,
          ),
        ),
      ),
    );
  }
}
