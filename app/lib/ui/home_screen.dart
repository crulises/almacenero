import 'package:material_ui/material_ui.dart';

import '../data/product_repository.dart';
import '../data/user_repository.dart';
import '../domain/ean.dart';
import 'product_screen.dart';
import 'scan_screen.dart';

/// Pantalla inicial: usuario actual (alias y karma) y búsqueda de un producto, ya sea
/// escaneando el código o ingresándolo a mano.
class HomeScreen extends StatefulWidget {
  const HomeScreen({
    super.key,
    required this.loadMe,
    required this.loadProducto,
  });

  final Future<Me> Function() loadMe;
  final Future<Producto> Function(String ean) loadProducto;

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  late Future<Me> _me = widget.loadMe();
  final _eanController = TextEditingController();
  String? _eanError;

  @override
  void dispose() {
    _eanController.dispose();
    super.dispose();
  }

  void _retry() {
    setState(() {
      _me = widget.loadMe();
    });
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

  void _abrirProducto(String ean) {
    Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (_) =>
            ProductScreen(ean: ean, loadProducto: widget.loadProducto),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Almacenero')),
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
        if (snapshot.hasError) {
          return Column(
            children: [
              const Text('No pudimos conectar con el servidor'),
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
          ],
        );
      },
    );
  }
}
