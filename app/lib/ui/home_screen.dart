import 'package:material_ui/material_ui.dart';

import '../app_deps.dart';
import '../data/api_client.dart';
import '../data/auth_repository.dart';
import '../data/user_repository.dart';
import '../data/recientes.dart';
import '../domain/ean.dart';
import 'acerca_screen.dart';
import 'alias_editable.dart';
import 'invitacion_screen.dart';
import 'moderacion.dart';
import 'product_screen.dart';
import 'recientes.dart';

/// Pantalla inicial: usuario actual (alias y karma) y búsqueda de un producto, ya sea
/// escaneando el código o ingresándolo a mano.
class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key, required this.deps});

  final AppDeps deps;

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> with RouteAware {
  late Future<Me> _me = _cargarMe();
  final _eanController = TextEditingController();
  bool _yaEntro =
      false; // hubo una sesión: los recargos no vuelven a la pantalla de carga
  String? _eanError;

  /// Últimas consultas, de lo guardado en el celular (se ven siempre, con o sin red).
  List<Reciente> _recientes = const [];

  /// Cuándo se refrescó cada una con red: no se vuelve a pedir a cada vuelta.
  final _refrescados = <String, DateTime>{};
  static const _cadaCuanto = Duration(minutes: 5);

  @override
  void initState() {
    super.initState();
    _cargarRecientes();
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final ruta = ModalRoute.of(context);
    if (ruta != null) routeObserver.subscribe(this, ruta);
  }

  @override
  void dispose() {
    routeObserver.unsubscribe(this);
    _eanController.dispose();
    super.dispose();
  }

  /// Se volvió al inicio desde otra pantalla (la ficha, o la ficha de otro producto escaneado
  /// desde ella): campo vacío, karma al día y recientes actualizados.
  @override
  void didPopNext() {
    _eanController.clear();
    FocusScope.of(context).unfocus();
    _retry();
    _cargarRecientes(alVolver: true);
  }

  /// Muestra lo guardado enseguida y, aparte, lo refresca con red. Si no hay red no pasa
  /// nada: se ve la foto guardada, sin errores ni esperas.
  Future<void> _cargarRecientes({bool alVolver = false}) async {
    final guardados = await widget.deps.leerRecientes();
    if (!mounted) return;
    setState(() => _recientes = guardados);
    final ahora = DateTime.now();
    for (final r in guardados) {
      // Recién consultado en la ficha (está al día) o ya refrescado hace poco.
      if (alVolver &&
          ahora.difference(r.consultadoEn) < const Duration(minutes: 1)) {
        continue;
      }
      final ultimo = _refrescados[r.ean];
      if (ultimo != null && ahora.difference(ultimo) < _cadaCuanto) continue;
      _refrescados[r.ean] = ahora;
      widget.deps.refrescarReciente(r).then((nuevo) {
        if (nuevo == null || !mounted) return;
        setState(() {
          _recientes = [
            for (final x in _recientes) x.ean == nuevo.ean ? nuevo : x,
          ];
        });
      }).ignore();
    }
  }

  /// El error lo muestra el FutureBuilder; `ignore()` evita que, si falla antes del
  /// próximo frame (sin red, por ejemplo), Dart lo cuente como error sin manejar.
  Future<Me> _cargarMe() => widget.deps.loadMe()..ignore();

  void _retry() {
    setState(() {
      _me = _cargarMe();
    });
  }

  Future<void> _enviarInvitacion(String codigo) async {
    await widget.deps.guardarInvitacion(codigo);
    if (mounted) _retry();
  }

  Future<void> _escanear() async {
    final ean = await Navigator.of(context).push<String>(
      MaterialPageRoute(builder: (_) => widget.deps.pantallaEscaneo()),
    );
    if (ean != null && mounted) _abrirProducto(ean, via: 'camara');
  }

  void _buscarManual() {
    final ean = normalizarEan(_eanController.text);
    if (ean == null) {
      setState(() => _eanError = 'Ingresá entre 8 y 14 dígitos');
      return;
    }
    setState(() => _eanError = null);
    _abrirProducto(ean, via: 'manual');
  }

  /// [via] es cómo se llegó al código (`camara` / `manual`); `null` si no fue un escaneo
  /// (se tocó un reciente): ahí no se anota el evento `producto.escaneado`.
  /// Al volver, [didPopNext] deja el inicio al día.
  Future<void> _abrirProducto(String ean, {String? via}) =>
      Navigator.of(context).push(
        MaterialPageRoute<void>(
          builder: (_) => ProductScreen(ean: ean, deps: widget.deps, via: via),
        ),
      );

  @override
  Widget build(BuildContext context) {
    // Sin sesión y con el backend pidiendo invitación: es lo ÚNICO que se muestra.
    return FutureBuilder<Me>(
      future: _me,
      builder: (context, snapshot) {
        final error = snapshot.error;
        if (error is InvitacionRequerida) {
          return InvitacionScreen(
            rechazada: error.rechazada,
            onEnviar: _enviarInvitacion,
          );
        }
        // Cuenta de baja: pantalla final, sin reintentos ni cuenta nueva.
        if (error is ApiException && error.isCuentaBaja) {
          return const CuentaBajaScreen();
        }
        if (snapshot.hasData) _yaEntro = true;
        if (snapshot.connectionState != ConnectionState.done && !_yaEntro) {
          return const Scaffold(
            body: Center(child: CircularProgressIndicator()),
          );
        }
        return _principal(context);
      },
    );
  }

  Widget _principal(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Almacenero'),
        actions: [
          IconButton(
            tooltip: 'Acerca de',
            icon: const Icon(Icons.info_outline),
            onPressed: () => Navigator.of(context).push(
              MaterialPageRoute<void>(
                builder: (_) => AcercaScreen(deps: widget.deps),
              ),
            ),
          ),
        ],
      ),
      // El teclado tapa la lista en vez de apretarla: lo de arriba no cambia de tamaño.
      resizeToAvoidBottomInset: false,
      body: Padding(
        padding: const EdgeInsets.fromLTRB(24, 24, 24, 0),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            _usuario(context),
            const SizedBox(height: 32),
            FilledButton.icon(
              onPressed: _escanear,
              icon: const Icon(Icons.qr_code_scanner),
              label: const Text('Escanear código'),
            ),
            const SizedBox(height: 24),
            TextField(
              controller: _eanController,
              keyboardType: TextInputType.number,
              textInputAction: TextInputAction.search,
              onSubmitted: (_) => _buscarManual(),
              decoration: InputDecoration(
                labelText: 'O ingresá el código',
                errorText: _eanError,
                suffixIcon: IconButton(
                  tooltip: 'Buscar',
                  icon: const Icon(Icons.search),
                  onPressed: _buscarManual,
                ),
              ),
            ),
            Expanded(
              child: RecientesSeccion(
                recientes: _recientes,
                onTap: (r) => _abrirProducto(r.ean),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _usuario(BuildContext context) {
    return FutureBuilder<Me>(
      future: _me,
      builder: (context, snapshot) {
        if (snapshot.connectionState != ConnectionState.done) {
          return const Center(child: CircularProgressIndicator());
        }
        final error = snapshot.error;
        if (error is ApiException && error.isRateLimited) {
          return Column(
            children: [
              const Text(
                'Demasiados intentos. Esperá un rato y probá de nuevo.',
              ),
              const SizedBox(height: 12),
              FilledButton(onPressed: _retry, child: const Text('Reintentar')),
            ],
          );
        }
        if (snapshot.hasError) {
          return Column(
            children: [
              const Text('No pudimos conectar con el servidor'),
              // La causa real: «no hay red» y «el servidor dijo 403» se arreglan distinto.
              if (error is ApiException)
                Text(
                  error.statusCode == null
                      ? error.message
                      : 'El servidor respondió ${error.statusCode}'
                            '${error.codigo == null ? '' : ' (${error.codigo})'}',
                  style: Theme.of(context).textTheme.bodySmall,
                ),
              const SizedBox(height: 12),
              FilledButton(onPressed: _retry, child: const Text('Reintentar')),
            ],
          );
        }
        final me = snapshot.requireData;
        return Column(
          children: [
            AliasEditable(me: me, onGuardar: widget.deps.cambiarAlias),
            const SizedBox(height: 8),
            Text('Karma: ${me.karma}'),
            if (me.escalon != Escalon.normal) ...[
              const SizedBox(height: 16),
              AvisoModeracion(me: me),
            ],
          ],
        );
      },
    );
  }
}
