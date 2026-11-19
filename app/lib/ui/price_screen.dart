import 'package:material_ui/material_ui.dart';

import '../app_deps.dart';
import '../data/local_repository.dart';
import '../data/location_service.dart';
import '../data/price_repository.dart';
import '../data/product_repository.dart';
import '../domain/precio.dart';
import 'create_local_dialog.dart';

/// Carga el precio de un producto en el local. Al terminar muestra el karma resultante.
class PriceScreen extends StatefulWidget {
  const PriceScreen({super.key, required this.producto, required this.deps});

  final Producto producto;
  final AppDeps deps;

  @override
  State<PriceScreen> createState() => _PriceScreenState();
}

class _PriceScreenState extends State<PriceScreen> {
  late Future<void> _contexto = _cargarContexto();
  final _precioController = TextEditingController();
  Ubicacion? _ubicacion;
  List<Local> _locales = [];
  Local? _elegido;
  String? _errorCampo;
  String? _errorEnvio;
  bool _enviando = false;
  PrecioCargado? _resultado;

  /// Ubicación del usuario y locales a su alrededor (el más cercano, elegido).
  Future<void> _cargarContexto() async {
    final ubicacion = await widget.deps.obtenerUbicacion();
    final locales = await widget.deps.loadLocalesCerca(ubicacion);
    _ubicacion = ubicacion;
    _locales = locales;
    _elegido = locales.isEmpty ? null : locales.first;
  }

  @override
  void dispose() {
    _precioController.dispose();
    super.dispose();
  }

  void _reintentarContexto() {
    setState(() {
      _contexto = _cargarContexto();
    });
  }

  Future<void> _crearLocal() async {
    final local = await mostrarCrearLocal(
      context,
      deps: widget.deps,
      ubicacion: _ubicacion!,
    );
    if (local == null || !mounted) return;
    setState(() {
      _locales = [local, ..._locales];
      _elegido = local;
    });
  }

  Future<void> _cambiarLocal() async {
    final elegido = await showModalBottomSheet<Object>(
      context: context,
      builder: (context) => SafeArea(
        child: ListView(
          shrinkWrap: true,
          children: [
            const ListTile(title: Text('¿En qué local estás?')),
            for (final l in _locales)
              ListTile(
                title: Text(l.nombre),
                subtitle: Text(_detalleLocal(l)),
                selected: l.id == _elegido?.id,
                onTap: () => Navigator.of(context).pop(l),
              ),
            ListTile(
              leading: const Icon(Icons.add_location_alt),
              title: const Text('Es otro local: crear uno nuevo aquí'),
              onTap: () => Navigator.of(context).pop('crear'),
            ),
          ],
        ),
      ),
    );
    if (!mounted) return;
    if (elegido is Local) {
      setState(() => _elegido = elegido);
    } else if (elegido == 'crear') {
      await _crearLocal();
    }
  }

  String _detalleLocal(Local l) => [
    if (l.distanciaM != null) 'a ${l.distanciaM!.round()} m',
    if (!l.verificado) 'sin verificar',
  ].join(' · ');

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
      // Ubicación fresca: el usuario pudo moverse desde que abrió la pantalla.
      final ubicacion = await widget.deps.obtenerUbicacion().catchError(
        (Object _) => _ubicacion!,
      );
      final resultado = await widget.deps.cargarPrecio(
        ean: widget.producto.ean,
        localId: local.id,
        precio: precio,
        ubicacion: ubicacion,
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
          CargaError.fueraDeRango =>
            'Estás a ${distanciaFueraDeRango(e) ?? '?'} m de ${local.nombre}. '
                'Acercate al local para cargar el precio.',
          CargaError.precisionBaja =>
            'Tu ubicación es muy imprecisa. Esperá unos segundos a que '
                'mejore el GPS y probá de nuevo.',
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
            : FutureBuilder<void>(
                future: _contexto,
                builder: (context, snapshot) {
                  if (snapshot.connectionState != ConnectionState.done) {
                    return const Center(child: CircularProgressIndicator());
                  }
                  if (snapshot.hasError) return _errorContexto(snapshot.error!);
                  final local = _elegido;
                  if (local == null) return _sinLocales();
                  return _formulario(context, local);
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
        Row(
          children: [
            Expanded(
              child: Text(
                'en ${local.nombre}'
                '${local.verificado ? '' : ' (sin verificar)'}',
                style: texto.bodyMedium,
              ),
            ),
            TextButton(
              onPressed: _enviando ? null : _cambiarLocal,
              child: const Text('Cambiar'),
            ),
          ],
        ),
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

  Widget _errorContexto(Object error) {
    final tipo = clasificarErrorUbicacion(error);
    final mensaje = switch (tipo) {
      UbicacionError.permisoDenegado =>
        'Necesitamos tu ubicación para saber en qué local estás.',
      UbicacionError.permisoDenegadoParaSiempre => 'Negaste el permiso de ubicación. Activalo desde los ajustes de la app.',
      UbicacionError.servicioApagado =>
        'Prendé la ubicación (GPS) del teléfono para continuar.',
      UbicacionError.otro =>
        'No pudimos obtener tu ubicación ni los locales cerca.',
    };
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(mensaje, textAlign: TextAlign.center),
          const SizedBox(height: 12),
          if (tipo == UbicacionError.permisoDenegadoParaSiempre) ...[
            FilledButton(
              onPressed: widget.deps.abrirAjustes,
              child: const Text('Abrir ajustes'),
            ),
            const SizedBox(height: 8),
          ],
          FilledButton(
            onPressed: _reintentarContexto,
            child: const Text('Reintentar'),
          ),
        ],
      ),
    );
  }

  Widget _sinLocales() {
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          const Text(
            'No hay locales registrados cerca de acá.',
            textAlign: TextAlign.center,
          ),
          const SizedBox(height: 12),
          FilledButton.icon(
            onPressed: _crearLocal,
            icon: const Icon(Icons.add_location_alt),
            label: const Text('Crear local aquí'),
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
