import 'package:material_ui/material_ui.dart';

import '../app_deps.dart';
import '../data/location_service.dart';
import '../data/price_repository.dart';
import '../data/product_repository.dart';
import '../data/recientes.dart';
import '../data/user_repository.dart';
import '../domain/precio.dart';
import 'escanear_otro.dart';
import 'frescura.dart';
import 'historial_local_screen.dart';
import 'mapa_precios.dart';
import 'moderacion.dart';
import 'price_screen.dart';
import 'sugerir_screen.dart';

/// Ficha de un producto buscado por EAN: cuánto sale en cada local (mapa + lista
/// con la frescura de cada precio) y su historial.
class ProductScreen extends StatefulWidget {
  const ProductScreen({
    super.key,
    required this.ean,
    required this.deps,
    this.via,
  });

  final String ean;

  /// Cómo se llegó al código: `camara` o `manual` (tipeado). Si viene, se anota el evento
  /// `producto.escaneado` (con esa `via`) cuando se sabe si el producto está en el catálogo.
  final String? via;
  final AppDeps deps;

  @override
  State<ProductScreen> createState() => _ProductScreenState();
}

class _ProductScreenState extends State<ProductScreen> {
  late Future<Producto> _producto = widget.deps.loadProducto(widget.ean);

  @override
  void initState() {
    super.initState();
    if (widget.via != null) _anotarEscaneo();
    _anotarReciente();
  }

  /// Deja la consulta en «Recientes» (solo en el celular): qué es, dónde y a cuánto. Si no
  /// hay nada en la zona busca uno de referencia (radio ampliado) para no mostrar vacío.
  /// Silencioso: ni un fallo de red ni de almacenamiento molestan a la ficha.
  Future<void> _anotarReciente() async {
    try {
      final producto = await _producto;
      final zona = await _vigentes;
      if (_verTodos) return; // «ver todos» no es una consulta de la zona
      var referencia = <PrecioVigente>[];
      if (_conUbicacion && zona.isEmpty) {
        referencia = await widget.deps
            .loadVigentes(widget.ean, ubicacion: _ubicacion, referencia: true)
            .catchError((Object _) => <PrecioVigente>[]);
      }
      await widget.deps.guardarReciente(
        resumirConsulta(
          producto: producto,
          zona: zona,
          referencia: referencia,
          conUbicacion: _conUbicacion,
          ahora: DateTime.now(),
        ),
      );
    } on Object {
      // Recientes es una comodidad.
    }
  }

  /// `encontrado` se sabe recién con la respuesta: 200 = sí, 404 = no. Cualquier otro
  /// fallo (sin red, 5xx) no dice nada del catálogo y no se anota. Los reintentos de la
  /// pantalla no repiten el evento.
  void _anotarEscaneo() {
    final ean = widget.ean;
    final via = widget.via;
    _producto.then<void>(
      (_) => widget.deps.registrarEvento('producto.escaneado', {
        'ean': ean,
        'encontrado': true,
        'via': via,
      }),
      onError: (Object e) {
        if (clasificarError(e) == ProductoError.noEncontrado) {
          widget.deps.registrarEvento('producto.escaneado', {
            'ean': ean,
            'encontrado': false,
            'via': via,
          });
        }
      },
    );
  }

  late Future<List<PrecioVigente>> _vigentes = _cargarVigentes();

  /// Para saber si puede cargar. Si falla se asume que sí: el backend decide.
  late final Future<Me?> _me = widget.deps
      .loadMe()
      .then<Me?>((m) => m)
      .catchError((_) => null);
  late Future<List<PrecioHistorial>> _historial = widget.deps.loadHistorial(
    widget.ean,
  );

  /// `localId` del precio resaltado en el mapa y en la lista.
  String? _seleccionado;
  final _clavesLista = <String, GlobalKey>{};

  /// Cuántos precios se ven antes de «Mostrar más».
  static const _visiblesInicial = 5;

  OrdenPrecios _orden = OrdenPrecios.precio;
  bool _expandida = false;

  /// Si se pidió ver los precios de todos los locales, sin límite de distancia.
  bool _verTodos = false;

  /// Si se pudo filtrar por cercanía (hay ubicación del usuario).
  bool _conUbicacion = false;
  Ubicacion? _ubicacion;

  /// Precios vigentes cerca del usuario. Sin ubicación (permiso, GPS apagado)
  /// trae todos: la ficha no se rompe por eso.
  Future<List<PrecioVigente>> _cargarVigentes() async {
    Ubicacion? ubicacion;
    if (!_verTodos) {
      try {
        ubicacion = await widget.deps.obtenerUbicacion();
      } on Object {
        ubicacion = null;
      }
    }
    _conUbicacion = ubicacion != null;
    _ubicacion = ubicacion;
    return widget.deps.loadVigentes(widget.ean, ubicacion: ubicacion);
  }

  void _verTodosLosLocales() {
    setState(() {
      _verTodos = true;
      _vigentes = _cargarVigentes();
    });
  }

  void _recargarPrecios() {
    setState(() {
      _vigentes = _cargarVigentes();
      _historial = widget.deps.loadHistorial(widget.ean);
    });
  }

  void _verHistorial(Producto p) {
    Navigator.of(context).push<void>(
      MaterialPageRoute<void>(
        builder: (_) => HistorialLocalScreen(producto: p, deps: widget.deps),
      ),
    );
  }

  Future<void> _cargarPrecio(Producto p) async {
    final cargado = await Navigator.of(context).push<PrecioCargado>(
      MaterialPageRoute<PrecioCargado>(
        builder: (_) => PriceScreen(producto: p, deps: widget.deps),
      ),
    );
    if (!mounted) return;
    // Si se cargó un precio, tiene que aparecer en el mapa, la lista y el historial.
    _recargarPrecios();
    if (cargado == null) return; // se volvió sin guardar
    _anotarReciente(); // la foto de Recientes, con el precio nuevo
    final aviso = 'Precio cargado · karma ${cargado.karma}';
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(
          cargado.primerPrecio
              ? '¡Fuiste el primero en cargarlo! $aviso'
              : aviso,
        ),
      ),
    );
  }

  /// Menú ⋮ de la barra: «Sugerir corrección», solo para moderadores con el producto
  /// cargado.
  List<Widget> _acciones() => [
    TextButton.icon(
      onPressed: () => escanearOtro(context, widget.deps),
      icon: const Icon(Icons.qr_code_scanner),
      label: const Text('Escanear otro'),
    ),
    FutureBuilder<Producto>(
      future: _producto,
      builder: (context, prod) => FutureBuilder<Me?>(
        future: _me,
        builder: (context, me) {
          final p = prod.data;
          final usuario = me.data;
          if (p == null ||
              usuario == null ||
              !usuario.puedeSugerir ||
              usuario.escalon == Escalon.restringido) {
            return const SizedBox.shrink();
          }
          return PopupMenuButton<String>(
            tooltip: 'Más opciones',
            onSelected: (_) => _sugerir(p),
            itemBuilder: (_) => const [
              PopupMenuItem<String>(
                value: 'sugerir',
                child: Text('Sugerir corrección'),
              ),
            ],
          );
        },
      ),
    ),
  ];

  Future<void> _sugerir(Producto? p) async {
    final enviada = await Navigator.of(context).push<bool>(
      MaterialPageRoute<bool>(
        builder: (_) =>
            SugerirScreen(ean: widget.ean, deps: widget.deps, producto: p),
      ),
    );
    if (enviada == true && mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('Sugerencia enviada. Un admin la va a revisar.'),
        ),
      );
    }
  }

  void _retry() {
    setState(() {
      _producto = widget.deps.loadProducto(widget.ean);
    });
  }

  void _elegir(String localId, {bool desplazarLista = false}) {
    setState(() {
      _seleccionado = localId;
      // Un precio tocado en el mapa puede estar oculto en la lista.
      if (desplazarLista) _expandida = true;
    });
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
      appBar: AppBar(title: const Text('Producto'), actions: _acciones()),
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
    final detalle = p.detalle;
    return Column(
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 4, 16, 8),
          child: FutureBuilder<Me?>(
            future: _me,
            builder: (context, me) => FutureBuilder<List<PrecioHistorial>>(
              future: _historial,
              builder: (context, historial) {
                final restringido = me.data?.escalon == Escalon.restringido;
                // Nadie cargó nada en ningún local: nunca un vacío, una invitación.
                final primero =
                    historial.hasData && historial.requireData.isEmpty;
                final info = Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(p.nombre, style: texto.titleLarge),
                    if (detalle.isNotEmpty) Text(detalle),
                    Text('EAN ${p.ean}', style: texto.bodySmall),
                  ],
                );
                final boton = FilledButton.icon(
                  // Restringido: se ve, pero apagado y con el motivo abajo.
                  onPressed: restringido ? null : () => _cargarPrecio(p),
                  icon: const Icon(Icons.sell),
                  label: Text(
                    primero ? 'Sé el primero en cargarlo' : 'Cargar precio',
                  ),
                );
                // Los botones van debajo, a lo ancho: al lado le robarían el lugar al nombre.
                return Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    info,
                    const SizedBox(height: 8),
                    // Sin ningún precio no hay historial que ver.
                    if (!primero) ...[
                      OutlinedButton.icon(
                        onPressed: () => _verHistorial(p),
                        icon: const Icon(Icons.show_chart),
                        label: const Text('Ver historial por local'),
                      ),
                      const SizedBox(height: 8),
                    ],
                    boton,
                  ],
                );
              },
            ),
          ),
        ),
        FutureBuilder<Me?>(
          future: _me,
          builder: (context, snapshot) {
            final me = snapshot.data;
            if (me == null || me.escalon != Escalon.restringido) {
              return const SizedBox.shrink();
            }
            return Padding(
              padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
              child: AvisoModeracion(me: me),
            );
          },
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
            children: [..._listaVigentes(context, snapshot)],
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
        if (_conUbicacion && !_verTodos) ...[
          const SizedBox(height: 4),
          const Text('No hay precios cargados cerca tuyo.'),
          const SizedBox(height: 8),
          OutlinedButton.icon(
            onPressed: _verTodosLosLocales,
            icon: const Icon(Icons.public),
            label: const Text('Ver precios en otros lugares'),
          ),
        ] else
          const Text('Todavía nadie cargó un precio de este producto.'),
      ];
    }
    final ahora = DateTime.now();
    // El más barato se marca siempre, sin importar cómo se ordene la lista.
    final masBaratoId = precios.first.localId;
    final ordenados = ordenarPrecios(precios, _orden);
    final visibles = _expandida
        ? ordenados
        : ordenados.take(_visiblesInicial).toList();
    return [
      titulo,
      if (precios.length > 1)
        Wrap(
          spacing: 8,
          children: [
            for (final o in OrdenPrecios.values)
              if (o != OrdenPrecios.cercania || _conUbicacion)
                ChoiceChip(
                  label: Text(o.etiqueta),
                  selected: _orden == o,
                  onSelected: (_) => setState(() => _orden = o),
                ),
          ],
        ),
      for (final p in visibles)
        _fila(
          context,
          p,
          ahora,
          masBarato: p.localId == masBaratoId && precios.length > 1,
        ),
      if (ordenados.length > _visiblesInicial)
        TextButton(
          onPressed: () => setState(() => _expandida = !_expandida),
          child: Text(
            _expandida
                ? 'Mostrar menos'
                : 'Mostrar más (${ordenados.length - _visiblesInicial})',
          ),
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
            if (p.distanciaM != null)
              TextSpan(text: ' · ${formatearDistancia(p.distanciaM!)}'),
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
        if (tipo == ProductoError.noEncontrado)
          FutureBuilder<Me?>(
            future: _me,
            builder: (context, me) {
              final usuario = me.data;
              if (usuario == null ||
                  !usuario.puedeSugerir ||
                  usuario.escalon == Escalon.restringido) {
                return const SizedBox.shrink();
              }
              return Padding(
                padding: const EdgeInsets.only(top: 12),
                child: FilledButton(
                  onPressed: () => _sugerir(null),
                  child: const Text('Dar de alta este producto'),
                ),
              );
            },
          ),
      ],
    );
  }
}
