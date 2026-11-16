import 'package:material_ui/material_ui.dart';

import '../app_deps.dart';
import '../data/price_repository.dart';
import '../data/product_repository.dart';
import '../domain/precio.dart';
import 'frescura.dart';
import 'mapa_precios.dart';
import 'price_screen.dart';

/// Ficha de un producto buscado por EAN: cuánto sale en cada local (mapa + lista
/// con la frescura de cada precio) y su historial.
class ProductScreen extends StatefulWidget {
  const ProductScreen({super.key, required this.ean, required this.deps});

  final String ean;
  final AppDeps deps;

  @override
  State<ProductScreen> createState() => _ProductScreenState();
}

class _ProductScreenState extends State<ProductScreen> {
  late Future<Producto> _producto = widget.deps.loadProducto(widget.ean);
  late Future<List<PrecioVigente>> _vigentes = widget.deps.loadVigentes(
    widget.ean,
  );
  late Future<List<PrecioHistorial>> _historial = widget.deps.loadHistorial(
    widget.ean,
  );

  /// `localId` del precio resaltado en el mapa y en la lista.
  String? _seleccionado;
  final _clavesLista = <String, GlobalKey>{};

  void _recargarPrecios() {
    setState(() {
      _vigentes = widget.deps.loadVigentes(widget.ean);
      _historial = widget.deps.loadHistorial(widget.ean);
    });
  }

  Future<void> _cargarPrecio(Producto p) async {
    await Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (_) => PriceScreen(producto: p, deps: widget.deps),
      ),
    );
    // Si se cargó un precio, tiene que aparecer en el mapa, la lista y el historial.
    if (mounted) _recargarPrecios();
  }

  void _retry() {
    setState(() {
      _producto = widget.deps.loadProducto(widget.ean);
    });
  }

  void _elegir(String localId, {bool desplazarLista = false}) {
    setState(() => _seleccionado = localId);
    if (!desplazarLista) return;
    // Desde el mapa: lleva la lista hasta el precio tocado.
    WidgetsBinding.instance.addPostFrameCallback((_) {
      final contexto = _clavesLista[localId]?.currentContext;
      if (contexto != null) {
        Scrollable.ensureVisible(
          contexto,
          duration: const Duration(milliseconds: 250),
          alignment: 0.1,
        );
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Producto')),
      body: FutureBuilder<Producto>(
        future: _producto,
        builder: (context, snapshot) {
          if (snapshot.connectionState != ConnectionState.done) {
            return const Center(child: CircularProgressIndicator());
          }
          if (snapshot.hasError) {
            return Padding(
              padding: const EdgeInsets.all(24),
              child: Center(child: _error(context, snapshot.error!)),
            );
          }
          return _ficha(context, snapshot.requireData);
        },
      ),
    );
  }

  Widget _ficha(BuildContext context, Producto p) {
    final texto = Theme.of(context).textTheme;
    final detalle = [
      if (p.marca != null) p.marca!,
      if (p.tamano != null) p.tamano!,
    ].join(' · ');
    return Column(
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 4, 16, 8),
          child: Row(
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(p.nombre, style: texto.titleLarge),
                    if (detalle.isNotEmpty) Text(detalle),
                    Text('EAN ${p.ean}', style: texto.bodySmall),
                  ],
                ),
              ),
              const SizedBox(width: 8),
              FilledButton.icon(
                onPressed: () => _cargarPrecio(p),
                icon: const Icon(Icons.sell),
                label: const Text('Cargar precio'),
              ),
            ],
          ),
        ),
        Expanded(
          child: FutureBuilder<List<PrecioVigente>>(
            future: _vigentes,
            builder: (context, snapshot) => _cuerpoPrecios(context, snapshot),
          ),
        ),
      ],
    );
  }

  /// Mapa fijo arriba y, debajo, la lista que se desplaza.
  Widget _cuerpoPrecios(
    BuildContext context,
    AsyncSnapshot<List<PrecioVigente>> snapshot,
  ) {
    final hayMapa = snapshot.hasData && snapshot.requireData.isNotEmpty;
    return Column(
      children: [
        if (hayMapa)
          SizedBox(
            height: 240,
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16),
              child: MapaPrecios(
                precios: snapshot.requireData,
                seleccionado: _seleccionado,
                onSeleccion: (id) => _elegir(id, desplazarLista: true),
              ),
            ),
          ),
        Expanded(
          child: ListView(
            padding: const EdgeInsets.fromLTRB(16, 8, 16, 24),
            children: [
              ..._listaVigentes(context, snapshot),
              const SizedBox(height: 24),
              Text(
                'Historial de precios',
                style: Theme.of(context).textTheme.titleMedium,
              ),
              const SizedBox(height: 8),
              _historialPrecios(context),
            ],
          ),
        ),
      ],
    );
  }

  List<Widget> _listaVigentes(
    BuildContext context,
    AsyncSnapshot<List<PrecioVigente>> snapshot,
  ) {
    final titulo = Text(
      'Precios por local',
      style: Theme.of(context).textTheme.titleMedium,
    );
    if (snapshot.connectionState != ConnectionState.done) {
      return [titulo, const Center(child: CircularProgressIndicator())];
    }
    if (snapshot.hasError) {
      return [
        titulo,
        Row(
          children: [
            const Expanded(child: Text('No pudimos cargar los precios.')),
            TextButton(
              onPressed: _recargarPrecios,
              child: const Text('Reintentar'),
            ),
          ],
        ),
      ];
    }
    final precios = snapshot.requireData;
    if (precios.isEmpty) {
      return [
        titulo,
        const Text('Todavía nadie cargó un precio de este producto.'),
      ];
    }
    final ahora = DateTime.now();
    return [
      titulo,
      for (var i = 0; i < precios.length; i++)
        _fila(
          context,
          precios[i],
          ahora,
          masBarato: i == 0 && precios.length > 1,
        ),
    ];
  }

  Widget _fila(
    BuildContext context,
    PrecioVigente p,
    DateTime ahora, {
    required bool masBarato,
  }) {
    final color = colorFrescura(p);
    return ListTile(
      key: _clavesLista.putIfAbsent(p.localId, GlobalKey.new),
      contentPadding: EdgeInsets.zero,
      selected: p.localId == _seleccionado,
      selectedTileColor: Theme.of(context).colorScheme.primaryContainer
          .withValues(alpha: 0.5),
      onTap: () => _elegir(p.localId),
      leading: Icon(Icons.circle, color: color, size: 16),
      title: Row(
        children: [
          Text(
            formatearPrecio(p.precio),
            style: Theme.of(context).textTheme.titleLarge,
          ),
          if (masBarato) ...[
            const SizedBox(width: 8),
            Text(
              'Más barato',
              style: TextStyle(
                color: Theme.of(context).colorScheme.primary,
                fontWeight: FontWeight.bold,
              ),
            ),
          ],
        ],
      ),
      subtitle: Text.rich(
        TextSpan(
          children: [
            TextSpan(text: p.localNombre),
            if (!p.localVerificado) const TextSpan(text: ' (sin verificar)'),
            const TextSpan(text: '\n'),
            TextSpan(
              text: etiquetaFrescura(p),
              style: TextStyle(color: color, fontWeight: FontWeight.bold),
            ),
            TextSpan(text: ' · ${formatearFecha(p.fecha, ahora: ahora)}'),
          ],
        ),
      ),
      isThreeLine: true,
    );
  }

  Widget _historialPrecios(BuildContext context) {
    return FutureBuilder<List<PrecioHistorial>>(
      future: _historial,
      builder: (context, snapshot) {
        if (snapshot.connectionState != ConnectionState.done) {
          return const Center(child: CircularProgressIndicator());
        }
        if (snapshot.hasError) {
          return Row(
            children: [
              const Expanded(child: Text('No pudimos cargar el historial.')),
              TextButton(
                onPressed: _recargarPrecios,
                child: const Text('Reintentar'),
              ),
            ],
          );
        }
        final precios = snapshot.requireData;
        if (precios.isEmpty) {
          return const Text('Todavía nadie cargó un precio de este producto.');
        }
        final ahora = DateTime.now();
        return Column(
          children: [
            for (final precio in precios)
              ListTile(
                contentPadding: EdgeInsets.zero,
                title: Text(
                  formatearPrecio(precio.precio),
                  style: Theme.of(context).textTheme.titleLarge,
                ),
                subtitle: Text(
                  '${precio.localNombre}\n'
                  '${formatearFecha(precio.fecha, ahora: ahora)}',
                ),
                isThreeLine: true,
              ),
          ],
        );
      },
    );
  }

  Widget _error(BuildContext context, Object error) {
    final tipo = clasificarError(error);
    final mensaje = switch (tipo) {
      ProductoError.noEncontrado =>
        'Este producto todavía no está en el catálogo.',
      ProductoError.eanDeBalanza =>
        'Es un código interno de balanza: todavía no se pueden cargar '
            'productos de balanza.',
      ProductoError.otro => 'No pudimos conectar con el servidor.',
    };
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        Text('EAN ${widget.ean}', style: Theme.of(context).textTheme.bodySmall),
        const SizedBox(height: 8),
        Text(mensaje, textAlign: TextAlign.center),
        if (tipo == ProductoError.otro) ...[
          const SizedBox(height: 12),
          FilledButton(onPressed: _retry, child: const Text('Reintentar')),
        ],
      ],
    );
  }
}
