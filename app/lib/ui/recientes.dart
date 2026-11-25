import 'package:material_ui/material_ui.dart';

import '../data/recientes.dart';
import '../domain/precio.dart';
import 'frescura.dart';

/// Avisa a quien lo escucha (el inicio) cuando se vuelve a él desde otra pantalla, sin
/// importar cómo: la ficha puede haberse reemplazado por otra con «Escanear otro».
final routeObserver = RouteObserver<ModalRoute<void>>();

/// «Recientes»: las últimas consultas con qué es, dónde y a cuánto. Un precio que no es de la
/// zona va marcado como **referencia**, con su distancia: nunca parece uno de acá.
class RecientesSeccion extends StatelessWidget {
  const RecientesSeccion({
    super.key,
    required this.recientes,
    required this.onTap,
  });

  final List<Reciente> recientes;
  final void Function(Reciente reciente) onTap;

  @override
  Widget build(BuildContext context) {
    // Sin nada que mostrar no ocupa lugar: la primera vez no hay un título huérfano.
    if (recientes.isEmpty) return const SizedBox.shrink();
    final ahora = DateTime.now();
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const SizedBox(height: 24),
        Text('Recientes', style: Theme.of(context).textTheme.titleMedium),
        for (final r in recientes) _fila(context, r, ahora),
      ],
    );
  }

  Widget _fila(BuildContext context, Reciente r, DateTime ahora) {
    final tema = Theme.of(context);
    return ListTile(
      key: ValueKey('reciente-${r.ean}'),
      contentPadding: EdgeInsets.zero,
      onTap: () => onTap(r),
      title: Text(r.nombre),
      isThreeLine: true,
      subtitle: _detalle(context, r, ahora, tema),
    );
  }

  Widget _detalle(
    BuildContext context,
    Reciente r,
    DateTime ahora,
    ThemeData tema,
  ) {
    final p = r.precio;
    if (p == null) {
      return Text(
        [
          if (r.detalle.isNotEmpty) r.detalle,
          'Sin precios cargados · sé el primero en cargarlo',
        ].join('\n'),
      );
    }
    final color = colorFrescura(p);
    return Text.rich(
      TextSpan(
        children: [
          if (r.detalle.isNotEmpty) TextSpan(text: '${r.detalle}\n'),
          if (r.esReferencia)
            TextSpan(
              text: 'Referencia · ',
              style: TextStyle(
                fontWeight: FontWeight.bold,
                color: tema.colorScheme.tertiary,
              ),
            ),
          TextSpan(
            text: formatearPrecio(p.precio),
            style: const TextStyle(fontWeight: FontWeight.bold),
          ),
          TextSpan(text: ' · ${p.localNombre}'),
          if (p.distanciaM != null)
            TextSpan(text: ' · a ${formatearDistancia(p.distanciaM!)}')
          else if (r.esReferencia)
            const TextSpan(text: ' · sin ubicación'),
          const TextSpan(text: '\n'),
          TextSpan(
            text: etiquetaFrescura(p),
            style: TextStyle(color: color, fontWeight: FontWeight.bold),
          ),
          TextSpan(text: ' · ${formatearFecha(p.fecha, ahora: ahora)}'),
        ],
      ),
    );
  }
}
