import 'package:material_ui/material_ui.dart';

import '../app_deps.dart';
import '../data/auth_repository.dart';
import 'google_logo.dart';

void _avisar(ScaffoldMessengerState mensajes, String texto) =>
    mensajes.showSnackBar(SnackBar(content: Text(texto)));

/// Liga la cuenta actual a un Google (el flujo que comparten la tarjeta y «Acerca de»).
/// Devuelve `true` si la sesión cambió (se ligó, o se entró a la cuenta que ese Google ya
/// tenía): quien llama refresca lo que muestra. Cerrar el selector no hace nada; un fallo
/// inesperado se avisa con un mensaje.
Future<bool> ligarCuentaConGoogle(BuildContext context, AppDeps deps) async {
  final mensajes = ScaffoldMessenger.of(context);
  try {
    await deps.ligarConGoogle();
    return true;
  } on GoogleCancelado {
    _avisar(mensajes, 'Se canceló el ingreso con Google.');
    return false;
  } on GoogleFallo catch (e) {
    _avisar(mensajes, 'Google falló: ${e.detalle}');
    return false;
  } on GoogleYaLigado {
    if (!context.mounted) return false;
    final entrar = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Ese Google ya tiene una cuenta'),
        content: const Text(
          'No se puede asociar a esta cuenta porque ese Google ya está asociado '
          'a otra. Podés entrar con esa cuenta: esta quedará aparte.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(ctx).pop(false),
            child: const Text('Cancelar'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(ctx).pop(true),
            child: const Text('Entrar con esa cuenta'),
          ),
        ],
      ),
    );
    if (entrar != true) return false;
    try {
      await deps.entrarConGoogle();
      return true;
    } on GoogleCancelado {
      _avisar(mensajes, 'Se canceló el ingreso con Google.');
      return false;
    } on GoogleFallo catch (e) {
      _avisar(mensajes, 'Google falló: ${e.detalle}');
      return false;
    } catch (_) {
      mensajes.showSnackBar(
        const SnackBar(content: Text('No pudimos entrar. Probá de nuevo.')),
      );
      return false;
    }
  } catch (_) {
    mensajes.showSnackBar(
      const SnackBar(
        content: Text('No pudimos ligar la cuenta. Probá de nuevo.'),
      ),
    );
    return false;
  }
}

/// «Protegé tu cuenta»: se ofrece cuando el karma ya vale la pena cuidar (lo decide el
/// backend con `sugerir_ligar`). «Luego» la oculta unos días.
class TarjetaLigar extends StatefulWidget {
  const TarjetaLigar({
    super.key,
    required this.deps,
    required this.onLigada,
    required this.onLuego,
  });

  final AppDeps deps;

  /// La sesión cambió: refrescar `/me`.
  final VoidCallback onLigada;
  final VoidCallback onLuego;

  @override
  State<TarjetaLigar> createState() => _TarjetaLigarState();
}

class _TarjetaLigarState extends State<TarjetaLigar> {
  bool _ocupada = false;

  Future<void> _ligar() async {
    if (_ocupada) return;
    setState(() => _ocupada = true);
    final cambio = await ligarCuentaConGoogle(context, widget.deps);
    if (!mounted) return;
    setState(() => _ocupada = false);
    if (cambio) widget.onLigada();
  }

  @override
  Widget build(BuildContext context) {
    final tema = Theme.of(context);
    return Card(
      color: tema.colorScheme.secondaryContainer,
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('Protegé tu cuenta', style: tema.textTheme.titleMedium),
            const SizedBox(height: 8),
            const Text(
              'Asociá una cuenta de Google para poder iniciar sesión en esta '
              'cuenta desde otro celular o después de reinstalar la app.',
            ),
            const SizedBox(height: 12),
            Row(
              mainAxisAlignment: MainAxisAlignment.end,
              children: [
                TextButton(
                  onPressed: _ocupada ? null : widget.onLuego,
                  child: const Text('Luego'),
                ),
                const SizedBox(width: 8),
                FilledButton.icon(
                  onPressed: _ocupada ? null : _ligar,
                  icon: const GoogleLogo(),
                  label: const Text('Asociar cuenta de Google'),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}
