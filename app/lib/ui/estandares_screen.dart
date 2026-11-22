import 'package:material_ui/material_ui.dart';

import '../app_deps.dart';
import '../data/sugerencia_repository.dart';

/// Ayuda: los estándares de carga del catálogo (docs/08-estandares-de-carga.md). Se
/// abre desde el formulario de sugerencias.
class EstandaresScreen extends StatelessWidget {
  const EstandaresScreen({super.key, required this.deps});

  final AppDeps deps;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Estándares de carga')),
      body: FutureBuilder<List<Estandar>>(
        future: deps.loadEstandares(),
        builder: (context, snapshot) {
          if (snapshot.connectionState != ConnectionState.done) {
            return const Center(child: CircularProgressIndicator());
          }
          if (snapshot.hasError) {
            return const Padding(
              padding: EdgeInsets.all(24),
              child: Center(child: Text('No pudimos cargar los estándares.')),
            );
          }
          final texto = Theme.of(context).textTheme;
          return ListView(
            padding: const EdgeInsets.all(16),
            children: [
              Text(
                'Qué se le pide a quien carga o corrige un producto. Si el '
                'sistema ajusta algo de lo que cargaste, se basa en estas '
                'reglas. Un ajuste nunca cambia tu karma.',
                style: texto.bodyMedium,
              ),
              for (final e in snapshot.requireData) ...[
                const SizedBox(height: 20),
                Text(e.titulo, style: texto.titleMedium),
                const SizedBox(height: 4),
                Text(e.regla),
                const SizedBox(height: 6),
                Text('Mal: ${e.mal}', style: texto.bodySmall),
                Text('Bien: ${e.bien}', style: texto.bodySmall),
              ],
            ],
          );
        },
      ),
    );
  }
}
