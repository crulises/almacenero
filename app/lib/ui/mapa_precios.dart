import 'dart:math' as math;
import 'dart:ui' as ui;

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
            userAgentPackageName: 'dev.crulises.almacenero',
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
                  width: 76,
                  height: 38,
                  // La punta (abajo) señala el local: el globo queda por encima.
                  alignment: Alignment.topCenter,
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
    final color = colorFrescura(precio);
    return GestureDetector(
      onTap: onTap,
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(
            key: ValueKey(
              'cartel-${precio.localId}${elegido ? '-elegido' : ''}',
            ),
            height: 26,
            alignment: Alignment.center,
            padding: const EdgeInsets.symmetric(horizontal: 7),
            decoration: BoxDecoration(
              color: color,
              borderRadius: BorderRadius.circular(13),
              border: Border.all(
                color: Colors.white,
                width: elegido ? 2.5 : 1.5,
              ),
              boxShadow: [
                BoxShadow(
                  color: Colors.black.withValues(alpha: elegido ? 0.5 : 0.25),
                  blurRadius: elegido ? 6 : 2,
                ),
              ],
            ),
            child: Text(
              formatearPrecioCorto(precio.precio),
              maxLines: 1,
              style: TextStyle(
                color: Colors.white,
                fontWeight: FontWeight.bold,
                fontSize: elegido ? 14 : 12,
              ),
            ),
          ),
          CustomPaint(size: const Size(12, 8), painter: _Punta(color)),
        ],
      ),
    );
  }
}

/// El triángulo de abajo del globo: su vértice es la posición exacta del local.
class _Punta extends CustomPainter {
  const _Punta(this.color);

  final Color color;

  @override
  void paint(Canvas canvas, Size size) {
    final path = ui.Path()
      ..moveTo(0, 0)
      ..lineTo(size.width, 0)
      ..lineTo(size.width / 2, size.height)
      ..close();
    canvas.drawPath(path, Paint()..color = color);
  }

  @override
  bool shouldRepaint(_Punta anterior) => anterior.color != color;
}
