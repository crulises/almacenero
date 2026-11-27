import 'package:material_ui/material_ui.dart';

import '../app_deps.dart';
import '../data/location_service.dart';
import '../data/price_repository.dart';
import '../data/product_repository.dart';
import '../domain/historial.dart';
import '../domain/precio.dart';
import 'escanear_otro.dart';
import 'grafico_precios.dart';
import 'mapa_local.dart';

/// Historial de precios de **un producto en un local** (corte 22): por defecto el más
/// cercano, con un selector para ver los demás. Sirve para juzgar si un descuento es real:
/// se ve cómo se movió el precio de verdad.
class HistorialLocalScreen extends StatefulWidget {
  const HistorialLocalScreen({
    super.key,
    required this.producto,
    required this.deps,
  });

  final Producto producto;
  final AppDeps deps;

  @override
  State<HistorialLocalScreen> createState() => _HistorialLocalScreenState();
}

class _HistorialLocalScreenState extends State<HistorialLocalScreen>
    with SingleTickerProviderStateMixin {
  /// Alto de los tabs: el mismo que el del mapa de la ficha.
  static const _altoTabs = 240.0;

  // «Gráfico» (la principal) es el segundo tab y el que se abre.
  late final _tabs = TabController(length: 2, vsync: this, initialIndex: 1);

  Ubicacion? _ubicacion;
  List<LocalDelProducto>? _locales;
  LocalDelProducto? _elegido;
  List<PrecioHistorial>? _historial;
  bool _error = false;

  @override
  void initState() {
    super.initState();
    _cargar();
  }

  @override
  void dispose() {
    _tabs.dispose();
    super.dispose();
  }

  String get _ean => widget.producto.ean;

  Future<void> _cargar() async {
    setState(() {
      _error = false;
      _locales = null;
      _historial = null;
    });
    // Sin GPS no hay error: se muestran los locales con precio, sin distancia.
    Ubicacion? ubicacion;
    try {
      ubicacion = await widget.deps.obtenerUbicacion();
    } on Object {
      ubicacion = null;
    }
    try {
      final locales = await widget.deps.loadLocalesDelProducto(
        _ean,
        ubicacion: ubicacion,
      );
      if (!mounted) return;
      setState(() {
        _ubicacion = ubicacion;
        _locales = locales;
        _elegido = locales.isEmpty ? null : locales.first;
      });
      if (_elegido != null) await _cargarHistorial();
    } on Object {
      if (mounted) setState(() => _error = true);
    }
  }

  Future<void> _cargarHistorial() async {
    final local = _elegido!;
    setState(() {
      _error = false;
      _historial = null;
    });
    try {
      final historial = await widget.deps.loadHistorialLocal(
        _ean,
        local.localId,
      );
      // Si mientras tanto se eligió otro local, esta respuesta ya no vale.
      if (!mounted || _elegido != local) return;
      setState(() => _historial = historial);
    } on Object {
      if (mounted && _elegido == local) setState(() => _error = true);
    }
  }

  Future<void> _elegirLocal() async {
    final locales = _locales;
    if (locales == null || locales.length < 2) return;
    final elegido = await showModalBottomSheet<LocalDelProducto>(
      context: context,
      builder: (context) => SafeArea(
        child: ListView(
          shrinkWrap: true,
          children: [
            for (final l in locales)
              ListTile(
                selected: l.localId == _elegido?.localId,
                title: Text(l.localNombre),
                subtitle: Text(
                  [
                    if (l.distanciaM != null) formatearDistancia(l.distanciaM!),
                    if (!l.tienePrecios) 'sin precios',
                  ].join(' · '),
                ),
                onTap: () => Navigator.of(context).pop(l),
              ),
          ],
        ),
      ),
    );
    if (elegido == null || elegido.localId == _elegido?.localId) return;
    setState(() => _elegido = elegido);
    await _cargarHistorial();
  }

  @override
  Widget build(BuildContext context) {
    final local = _elegido;
    final puedeElegir = (_locales?.length ?? 0) > 1;
    return Scaffold(
      appBar: AppBar(
        title: local == null
            ? const Text('Historial')
            : InkWell(
                onTap: puedeElegir ? _elegirLocal : null,
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Flexible(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            local.localNombre,
                            overflow: TextOverflow.ellipsis,
                          ),
                          if (local.distanciaM != null)
                            Text(
                              formatearDistancia(local.distanciaM!),
                              style: Theme.of(context).textTheme.bodySmall,
                            ),
                        ],
                      ),
                    ),
                    if (puedeElegir) const Icon(Icons.arrow_drop_down),
                  ],
                ),
              ),
        actions: [
          TextButton.icon(
            onPressed: () =>
                escanearOtro(context, widget.deps, desdeHistorial: true),
            icon: const Icon(Icons.qr_code_scanner),
            label: const Text('Escanear otro'),
          ),
        ],
      ),
      body: _cuerpo(context),
    );
  }

  Widget _cuerpo(BuildContext context) {
    if (_error) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Flexible(child: Text('No pudimos cargar el historial.')),
              TextButton(
                onPressed: _elegido == null ? _cargar : _cargarHistorial,
                child: const Text('Reintentar'),
              ),
            ],
          ),
        ),
      );
    }
    if (_locales == null) {
      return const Center(child: CircularProgressIndicator());
    }
    if (_locales!.isEmpty) {
      return _sinPrecios(
        context,
        'No hay locales cercanos con precios de este producto',
      );
    }
    final historial = _historial;
    if (historial == null) {
      return const Center(child: CircularProgressIndicator());
    }
    if (historial.isEmpty) {
      return _sinPrecios(
        context,
        'Este local no tiene precios de este producto',
      );
    }
    final local = _elegido!;
    final texto = Theme.of(context).textTheme;
    final ahora = DateTime.now();
    return ListView(
      padding: const EdgeInsets.fromLTRB(16, 8, 16, 24),
      children: [
        Text(widget.producto.nombre, style: texto.titleMedium),
        if (widget.producto.detalle.isNotEmpty) Text(widget.producto.detalle),
        const SizedBox(height: 8),
        TabBar(
          controller: _tabs,
          tabs: const [
            Tab(text: 'Mapa'),
            Tab(text: 'Gráfico'),
          ],
        ),
        SizedBox(
          height: _altoTabs,
          child: TabBarView(
            controller: _tabs,
            // Se cambia de tab tocando: un deslizamiento horizontal es del mapa.
            physics: const NeverScrollableScrollPhysics(),
            children: [
              Padding(
                padding: const EdgeInsets.only(top: 8),
                child: MapaLocal(
                  localLat: local.lat,
                  localLng: local.lng,
                  usuario: _ubicacion,
                ),
              ),
              Padding(
                padding: const EdgeInsets.only(top: 8),
                child: GraficoPrecios(precios: historial),
              ),
            ],
          ),
        ),
        const SizedBox(height: 16),
        for (final punto in conVariacion(historial))
          ListTile(
            contentPadding: EdgeInsets.zero,
            title: Text(
              formatearPrecio(punto.precio.precio),
              style: texto.titleLarge,
            ),
            subtitle: Text(formatearFecha(punto.precio.fecha, ahora: ahora)),
            trailing: Text(
              etiquetaVariacion(punto.variacionPct),
              style: texto.bodyMedium?.copyWith(fontWeight: FontWeight.bold),
            ),
          ),
      ],
    );
  }

  /// Nunca un vacío mudo: dice qué pasa y deja dos salidas.
  Widget _sinPrecios(BuildContext context, String mensaje) {
    return Padding(
      padding: const EdgeInsets.all(24),
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text(
            mensaje,
            textAlign: TextAlign.center,
            style: Theme.of(context).textTheme.titleMedium,
          ),
          const SizedBox(height: 24),
          OutlinedButton(
            onPressed: () =>
                Navigator.of(context).popUntil((ruta) => ruta.isFirst),
            child: const Text('Ir al inicio'),
          ),
          const SizedBox(height: 12),
          FilledButton(
            onPressed: () =>
                escanearOtro(context, widget.deps, desdeHistorial: true),
            child: const Text('Escanear'),
          ),
        ],
      ),
    );
  }
}
