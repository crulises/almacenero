import 'package:material_ui/material_ui.dart';

import '../app_deps.dart';
import '../data/api_client.dart';
import '../data/auth_repository.dart';
import '../data/user_repository.dart';
import '../domain/ean.dart';
import 'acerca_screen.dart';
import 'invitacion_screen.dart';
import 'moderacion.dart';
import 'product_screen.dart';
import 'scan_screen.dart';

/// Pantalla inicial: usuario actual (alias y karma) y búsqueda de un producto, ya sea
/// escaneando el código o ingresándolo a mano.
class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key, required this.deps});

  final AppDeps deps;

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  late Future<Me> _me = _cargarMe();
  final _eanController = TextEditingController();
  bool _yaEntro =
      false; // hubo una sesión: los recargos no vuelven a la pantalla de carga
  String? _eanError;

  @override
  void dispose() {
    _eanController.dispose();
    super.dispose();
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
    final ean = await Navigator.of(context)
        .push<String>(MaterialPageRoute(builder: (_) => const ScanScreen()));
    if (ean != null && mounted) _abrirProducto(ean);
  }

  void _buscarManual() {
    final ean = normalizarEan(_eanController.text);
    if (ean == null) {
      setState(() => _eanError = 'Ingresá entre 8 y 14 dígitos');
      return;
    }
    setState(() => _eanError = null);
    _abrirProducto(ean);
  }

  Future<void> _abrirProducto(String ean) async {
    await Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (_) => ProductScreen(ean: ean, deps: widget.deps),
      ),
    );
    if (!mounted) return;
    // Listo para el próximo producto: campo vacío y sin teclado.
    _eanController.clear();
    FocusScope.of(context).unfocus();
    // Al volver puede haber cambiado el karma (si se cargó un precio).
    _retry();
  }

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
      body: ListView(
        padding: const EdgeInsets.all(24),
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
        ],
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
            Text(me.alias, style: Theme.of(context).textTheme.headlineSmall),
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
