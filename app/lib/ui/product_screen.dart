import 'package:material_ui/material_ui.dart';

import '../app_deps.dart';
import '../data/price_repository.dart';
import '../data/product_repository.dart';
import '../domain/precio.dart';
import 'price_screen.dart';

/// Ficha de un producto buscado por EAN en el catálogo canónico.
class ProductScreen extends StatefulWidget {
  const ProductScreen({super.key, required this.ean, required this.deps});

  final String ean;
  final AppDeps deps;

  @override
  State<ProductScreen> createState() => _ProductScreenState();
}

class _ProductScreenState extends State<ProductScreen> {
  late Future<Producto> _producto = widget.deps.loadProducto(widget.ean);

  late Future<List<PrecioHistorial>> _historial = widget.deps.loadHistorial(
    widget.ean,
  );

  void _recargarHistorial() {
    setState(() {
      _historial = widget.deps.loadHistorial(widget.ean);
    });
  }

  Future<void> _cargarPrecio(Producto p) async {
    await Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (_) => PriceScreen(producto: p, deps: widget.deps),
      ),
    );
    // Si se cargó un precio, tiene que aparecer en el historial.
    if (mounted) _recargarHistorial();
  }

  void _retry() {
    setState(() {
      _producto = widget.deps.loadProducto(widget.ean);
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Producto')),
      body: Padding(
        padding: const EdgeInsets.all(24),
        child: FutureBuilder<Producto>(
          future: _producto,
          builder: (context, snapshot) {
            if (snapshot.connectionState != ConnectionState.done) {
              return const Center(child: CircularProgressIndicator());
            }
            if (snapshot.hasError) {
              return Center(child: _error(context, snapshot.error!));
            }
            return _ficha(context, snapshot.requireData);
          },
        ),
      ),
    );
  }

  Widget _ficha(BuildContext context, Producto p) {
    final texto = Theme.of(context).textTheme;
    final detalle = [
      if (p.marca != null) p.marca!,
      if (p.tamano != null) p.tamano!,
    ].join(' · ');
    return ListView(
      children: [
        Text(p.nombre, style: texto.headlineSmall, textAlign: TextAlign.center),
        if (detalle.isNotEmpty) ...[
          const SizedBox(height: 8),
          Text(detalle, style: texto.bodyLarge, textAlign: TextAlign.center),
        ],
        const SizedBox(height: 8),
        Text(
          'EAN ${p.ean}',
          style: texto.bodySmall,
          textAlign: TextAlign.center,
        ),
        const SizedBox(height: 24),
        Center(
          child: FilledButton.icon(
            onPressed: () => _cargarPrecio(p),
            icon: const Icon(Icons.sell),
            label: const Text('Cargar precio'),
          ),
        ),
        const SizedBox(height: 32),
        Text('Historial de precios', style: texto.titleMedium),
        const SizedBox(height: 8),
        _historialPrecios(context),
      ],
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
                onPressed: _recargarHistorial,
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
