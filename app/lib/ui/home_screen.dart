import 'package:material_ui/material_ui.dart';

import '../data/user_repository.dart';

/// Pantalla inicial. Muestra el usuario anónimo (alias y karma) como prueba de que la
/// sesión funciona contra el backend. TODO: escaneo EAN y carga de precio.
class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key, required this.loadMe});

  final Future<Me> Function() loadMe;

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  late Future<Me> _me = widget.loadMe();

  void _retry() {
    setState(() {
      _me = widget.loadMe();
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Almacenero')),
      body: Center(
        child: FutureBuilder<Me>(
          future: _me,
          builder: (context, snapshot) {
            if (snapshot.connectionState != ConnectionState.done) {
              return const CircularProgressIndicator();
            }
            if (snapshot.hasError) {
              return Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  const Text('No pudimos conectar con el servidor'),
                  const SizedBox(height: 12),
                  FilledButton(
                    onPressed: _retry,
                    child: const Text('Reintentar'),
                  ),
                ],
              );
            }
            final me = snapshot.requireData;
            return Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(
                  me.alias,
                  style: Theme.of(context).textTheme.headlineSmall,
                ),
                const SizedBox(height: 8),
                Text('Karma: ${me.karma}'),
              ],
            );
          },
        ),
      ),
    );
  }
}
