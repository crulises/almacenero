import 'package:material_ui/material_ui.dart';

import '../app_deps.dart';
import '../data/product_repository.dart';
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
        child: Center(
          child: FutureBuilder<Producto>(
            future: _producto,
            builder: (context, snapshot) {
              if (snapshot.connectionState != ConnectionState.done) {
                return const CircularProgressIndicator();
              }
              if (snapshot.hasError) return _error(context, snapshot.error!);
              return _ficha(context, snapshot.requireData);
            },
          ),
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
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        Text(p.nombre, style: texto.headlineSmall, textAlign: TextAlign.center),
        if (detalle.isNotEmpty) ...[
          const SizedBox(height: 8),
          Text(detalle, style: texto.bodyLarge),
        ],
        const SizedBox(height: 8),
        Text('EAN ${p.ean}', style: texto.bodySmall),
        const SizedBox(height: 32),
        FilledButton.icon(
          onPressed: () => Navigator.of(context).push(
            MaterialPageRoute<void>(
              builder: (_) => PriceScreen(producto: p, deps: widget.deps),
            ),
          ),
          icon: const Icon(Icons.sell),
          label: const Text('Cargar precio'),
        ),
      ],
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
