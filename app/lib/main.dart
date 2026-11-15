import 'package:material_ui/material_ui.dart';

void main() => runApp(const AlmaceneroApp());

class AlmaceneroApp extends StatelessWidget {
  const AlmaceneroApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Almacenero',
      theme: ThemeData(colorSchemeSeed: Colors.green, useMaterial3: true),
      home: const HomeScreen(),
    );
  }
}

/// Pantalla inicial. TODO v0.0.1: auth anónima, escaneo EAN, carga de precio.
/// El cliente habla SOLO con el backend (`/v1`), nunca con Supabase directo.
class HomeScreen extends StatelessWidget {
  const HomeScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Almacenero')),
      body: const Center(child: Text('Escaneá un producto para empezar')),
    );
  }
}
