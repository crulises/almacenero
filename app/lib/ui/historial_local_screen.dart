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

  /// Alto mínimo del cuerpo para fijar la cabecera y desplazar solo la lista.
  static const _altoMinimoFijo = 640.0;

  // «Gráfico» (la principal) es el primer tab y el que se abre; «Mapa» va a la derecha.
  late final _tabs = TabController(length: 2, vsync: this);

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
                      child: Text(
                        local.localNombre,
                        overflow: TextOverflow.ellipsis,
                      ),
                    ),
                    if (local.distanciaM != null) ...[
                      const SizedBox(width: 8),
                      Text(
                        formatearDistancia(local.distanciaM!),
                        style: Theme.of(context).textTheme.bodySmall,
                      ),
                    ],
                    if (puedeElegir) const Icon(Icons.arrow_drop_down),
                  ],
                ),
              ),
        actions: [
          TextButton.icon(
            onPressed: () =>
                escanearOtro(context, widget.deps, desdeHistorial: true),
            icon: const Icon(Icons.barcode_reader),
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
    final cabecera = <Widget>[
      Text(widget.producto.nombre, style: texto.titleMedium),
      if (widget.producto.detalle.isNotEmpty) Text(widget.producto.detalle),
      const SizedBox(height: 8),
      _SelectorTabs(controller: _tabs),
      SizedBox(
        height: _altoTabs,
        child: TabBarView(
          controller: _tabs,
          // Se cambia de tab tocando: un deslizamiento horizontal es del mapa.
          physics: const NeverScrollableScrollPhysics(),
          children: [
            Padding(
              padding: const EdgeInsets.only(top: 8),
              child: GraficoPrecios(precios: historial),
            ),
            Padding(
              padding: const EdgeInsets.only(top: 8),
              child: MapaLocal(
                localLat: local.lat,
                localLng: local.lng,
                usuario: _ubicacion,
              ),
            ),
          ],
        ),
      ),
      const SizedBox(height: 16),
      Text('Historial de precios', style: texto.titleSmall),
      const Divider(height: 16),
    ];
    final filas = [
      for (final punto in conVariacion(historial))
        _FilaPrecio(punto: punto, ahora: ahora),
    ];
    return LayoutBuilder(
      builder: (context, c) {
        // Con espacio, la cabecera queda fija y solo la lista se desplaza. En una
        // pantalla muy baja no entraría la lista: se desplaza todo junto.
        if (c.maxHeight < _altoMinimoFijo) {
          return ListView(
            padding: const EdgeInsets.fromLTRB(16, 8, 16, 24),
            children: [...cabecera, ...filas],
          );
        }
        return Padding(
          padding: const EdgeInsets.fromLTRB(16, 8, 16, 0),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              ...cabecera,
              Expanded(
                child: ListView(
                  padding: const EdgeInsets.only(bottom: 16),
                  children: filas,
                ),
              ),
            ],
          ),
        );
      },
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

/// Los tabs «Gráfico | Mapa» con la misma forma que los botones de la app: una píldora
/// redondeada, no la raya cuadrada de un `TabBar` común.
class _SelectorTabs extends StatelessWidget {
  const _SelectorTabs({required this.controller});

  final TabController controller;

  @override
  Widget build(BuildContext context) {
    final colores = Theme.of(context).colorScheme;
    return Container(
      padding: const EdgeInsets.all(4),
      decoration: ShapeDecoration(
        shape: const StadiumBorder(),
        color: colores.surfaceContainerHighest,
      ),
      child: TabBar(
        controller: controller,
        dividerColor: Colors.transparent,
        indicatorSize: TabBarIndicatorSize.tab,
        indicator: ShapeDecoration(
          shape: const StadiumBorder(),
          color: colores.primary,
        ),
        labelColor: colores.onPrimary,
        unselectedLabelColor: colores.onSurfaceVariant,
        overlayColor: const WidgetStatePropertyAll(Colors.transparent),
        splashFactory: NoSplash.splashFactory,
        tabs: const [
          Tab(text: 'Gráfico', height: 40),
          Tab(text: 'Mapa', height: 40),
        ],
      ),
    );
  }
}

/// Un precio del historial en una línea: el precio en negrita, la fecha en gris al lado y,
/// a la derecha, cuánto cambió contra el anterior (flecha + porcentaje).
class _FilaPrecio extends StatelessWidget {
  const _FilaPrecio({required this.punto, required this.ahora});

  final PuntoHistorial punto;
  final DateTime ahora;

  @override
  Widget build(BuildContext context) {
    final tema = Theme.of(context);
    final gris = tema.colorScheme.onSurfaceVariant;
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: Row(
        children: [
          Text(
            formatearPrecio(punto.precio.precio),
            style: tema.textTheme.bodyLarge?.copyWith(
              fontWeight: FontWeight.bold,
            ),
          ),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              formatearFecha(punto.precio.fecha, ahora: ahora),
              overflow: TextOverflow.ellipsis,
              style: tema.textTheme.bodySmall?.copyWith(color: gris),
            ),
          ),
          _Variacion(pct: punto.variacionPct),
        ],
      ),
    );
  }
}

/// «↑ 8%» (sube: rojo), «↓ 12%» (baja: verde) o «–» sin cambios. Nada si no hay con qué comparar.
class _Variacion extends StatelessWidget {
  const _Variacion({required this.pct});

  final double? pct;

  @override
  Widget build(BuildContext context) {
    final p = pct;
    if (p == null) return const SizedBox.shrink();
    final tema = Theme.of(context);
    final (icono, color, texto) = p.abs() < 0.5
        ? (Icons.remove, tema.colorScheme.onSurfaceVariant, '0%')
        : p > 0
        ? (Icons.arrow_upward, tema.colorScheme.error, '${p.round()}%')
        : (Icons.arrow_downward, Colors.green.shade700, '${p.abs().round()}%');
    return Semantics(
      label: etiquetaVariacion(p),
      excludeSemantics: true,
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icono, size: 16, color: color),
          const SizedBox(width: 2),
          Text(
            texto,
            style: tema.textTheme.bodyMedium?.copyWith(
              color: color,
              fontWeight: FontWeight.bold,
            ),
          ),
        ],
      ),
    );
  }
}
