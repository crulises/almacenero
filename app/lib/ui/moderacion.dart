import 'package:material_ui/material_ui.dart';

import '../data/user_repository.dart';

/// Mensajes de moderación (docs/04 §9): claros y sin tono de castigo.
const mensajeRestringido =
    'Tu karma está muy bajo, así que por ahora solo podés consultar precios, '
    'no cargarlos. Cuando suba, vas a poder cargar de nuevo.';

const mensajeBaja = 'Tu cuenta fue dada de baja y ya no podés usar Almacenero.';

/// Tarjeta de la pantalla principal según el escalón (nada si está normal).
class AvisoModeracion extends StatelessWidget {
  const AvisoModeracion({super.key, required this.me});

  final Me me;

  @override
  Widget build(BuildContext context) {
    final texto = switch (me.escalon) {
      Escalon.normal => null,
      Escalon.aviso =>
        'Tu karma está bajo (${me.karma}). Seguís usando todo, pero si baja '
            'de ${me.umbralRestriccion} no vas a poder cargar precios. '
            'Cargar precios correctos lo hace subir.',
      Escalon.restringido => mensajeRestringido,
    };
    if (texto == null) return const SizedBox.shrink();
    final colores = Theme.of(context).colorScheme;
    return Card(
      key: const Key('aviso-moderacion'),
      color: me.escalon == Escalon.restringido
          ? colores.errorContainer
          : colores.tertiaryContainer,
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Icon(Icons.info_outline),
            const SizedBox(width: 12),
            Expanded(child: Text(texto)),
          ],
        ),
      ),
    );
  }
}

/// La cuenta está de baja: reemplaza a la app (sin escanear ni nada más).
class CuentaBajaScreen extends StatelessWidget {
  const CuentaBajaScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Almacenero')),
      body: const Center(
        child: Padding(
          padding: EdgeInsets.all(32),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(Icons.block, size: 56),
              SizedBox(height: 16),
              Text(
                'Cuenta dada de baja',
                key: Key('cuenta-baja'),
                style: TextStyle(fontSize: 22),
              ),
              SizedBox(height: 12),
              Text(mensajeBaja, textAlign: TextAlign.center),
              SizedBox(height: 12),
              Text(
                'Si creés que es un error, hablá con quien te invitó.',
                textAlign: TextAlign.center,
              ),
            ],
          ),
        ),
      ),
    );
  }
}
