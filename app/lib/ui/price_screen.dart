import 'package:material_ui/material_ui.dart';

import '../app_deps.dart';
import '../data/local_repository.dart';
import '../data/price_repository.dart';
import '../data/product_repository.dart';
import '../domain/precio.dart';

/// Carga el precio de un producto en el local. Al terminar muestra el karma resultante.
class PriceScreen extends StatefulWidget {
  const PriceScreen({super.key, required this.producto, required this.deps});

  final Producto producto;
  final AppDeps deps;

  @override
  State<PriceScreen> createState() => _PriceScreenState();
}

class _PriceScreenState extends State<PriceScreen> {
  // v0.0.1: un solo local (el del admin), así que se usa el primero.
  late Future<Local> _local = _cargarLocal();
  final _precioController = TextEditingController();
  String? _errorCampo;
  String? _errorEnvio;
  bool _enviando = false;
  PrecioCargado? _resultado;

  Future<Local> _cargarLocal() async {
    final locales = await widget.deps.loadLocales();
    if (locales.isEmpty) throw StateError('No hay locales cargados');
    return locales.first;
  }

  @override
  void dispose() {
    _precioController.dispose();
    super.dispose();
  }

  void _reintentarLocal() {
    setState(() {
      _local = _cargarLocal();
    });
  }

  Future<void> _enviar(Local local) async {
    final precio = parsearPrecio(_precioController.text);
    if (precio == null) {
      setState(() {
        _errorCampo = 'Ingresá un precio mayor a 0 (ej. 1234,50)';
        _errorEnvio = null;
      });
      return;
    }
    setState(() {
      _errorCampo = null;
      _errorEnvio = null;
      _enviando = true;
    });
    try {
      final resultado = await widget.deps.cargarPrecio(
        ean: widget.producto.ean,
        localId: local.id,
        precio: precio,
      );
      if (!mounted) return;
      setState(() {
        _resultado = resultado;
        _enviando = false;
      });
    } on Object catch (e) {
      if (!mounted) return;
      setState(() {
        _enviando = false;
        _errorEnvio = switch (clasificarErrorCarga(e)) {
          CargaError.noEncontrado =>
            'No encontramos el producto o el local. Probá de nuevo más tarde.',
          CargaError.precioInvalido => 'El servidor rechazó ese precio.',
          CargaError.otro => 'No pudimos cargar el precio. Probá de nuevo.',
        };
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Cargar precio')),
      body: Padding(
        padding: const EdgeInsets.all(24),
        child: _resultado != null
            ? _exito(context, _resultado!)
            : FutureBuilder<Local>(
                future: _local,
                builder: (context, snapshot) {
                  if (snapshot.connectionState != ConnectionState.done) {
                    return const Center(child: CircularProgressIndicator());
                  }
                  if (snapshot.hasError) return _errorLocal();
                  return _formulario(context, snapshot.requireData);
                },
              ),
      ),
    );
  }

  Widget _formulario(BuildContext context, Local local) {
    final texto = Theme.of(context).textTheme;
    final p = widget.producto;
    return ListView(
      children: [
        Text(p.nombre, style: texto.headlineSmall),
        if (p.tamano != null) Text(p.tamano!, style: texto.bodyLarge),
        const SizedBox(height: 4),
        Text('en ${local.nombre}', style: texto.bodyMedium),
        const SizedBox(height: 24),
        TextField(
          controller: _precioController,
          autofocus: true,
          enabled: !_enviando,
          keyboardType: const TextInputType.numberWithOptions(decimal: true),
          textInputAction: TextInputAction.done,
          onSubmitted: (_) => _enviar(local),
          decoration: InputDecoration(
            labelText: 'Precio de góndola',
            prefixText: r'$ ',
            errorText: _errorCampo,
          ),
        ),
        if (_errorEnvio != null) ...[
          const SizedBox(height: 12),
          Text(
            _errorEnvio!,
            style: TextStyle(color: Theme.of(context).colorScheme.error),
          ),
        ],
        const SizedBox(height: 24),
        FilledButton(
          onPressed: _enviando ? null : () => _enviar(local),
          child: _enviando
              ? const SizedBox(
                  height: 20,
                  width: 20,
                  child: CircularProgressIndicator(strokeWidth: 2),
                )
              : const Text('Cargar precio'),
        ),
      ],
    );
  }

  Widget _errorLocal() {
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          const Text('No pudimos obtener el local'),
          const SizedBox(height: 12),
          FilledButton(
            onPressed: _reintentarLocal,
            child: const Text('Reintentar'),
          ),
        ],
      ),
    );
  }

  Widget _exito(BuildContext context, PrecioCargado resultado) {
    final texto = Theme.of(context).textTheme;
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(
            Icons.check_circle,
            size: 72,
            color: Theme.of(context).colorScheme.primary,
          ),
          const SizedBox(height: 16),
          Text('¡Precio cargado!', style: texto.headlineSmall),
          const SizedBox(height: 8),
          Text('Tu karma ahora es ${resultado.karma}'),
          const SizedBox(height: 24),
          FilledButton(
            onPressed: () =>
                Navigator.of(context).popUntil((ruta) => ruta.isFirst),
            child: const Text('Listo'),
          ),
        ],
      ),
    );
  }
}
