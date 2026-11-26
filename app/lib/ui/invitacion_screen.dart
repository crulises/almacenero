import 'package:material_ui/material_ui.dart';

import '../data/app_info.dart';
import 'google_logo.dart';

/// Primer arranque: la ÚNICA opción es escribir el código (PIN) de invitación.
/// Mientras no haya sesión no se muestra nada más de la app.
class InvitacionScreen extends StatefulWidget {
  const InvitacionScreen({
    super.key,
    required this.onEnviar,
    this.rechazada = false,
    this.onGoogle,
  });

  /// «Iniciar sesión con Google»: para quien ya asoció su cuenta (reinstalación u otro celular).
  /// Sin esto el botón no se muestra.
  final Future<void> Function()? onGoogle;

  /// Guarda el código y reintenta el alta. La pantalla la reemplaza el home.
  final Future<void> Function(String codigo) onEnviar;

  /// El backend rechazó el último código (inválido, vencido o ya usado).
  final bool rechazada;

  @override
  State<InvitacionScreen> createState() => _InvitacionScreenState();
}

class _InvitacionScreenState extends State<InvitacionScreen> {
  final _controller = TextEditingController();
  bool _enviando = false;

  Future<void> _google() async {
    if (_enviando) return;
    setState(() => _enviando = true);
    try {
      await widget.onGoogle!();
    } finally {
      if (mounted) setState(() => _enviando = false);
    }
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  Future<void> _enviar() async {
    final codigo = _controller.text.trim();
    if (codigo.isEmpty || _enviando) return;
    setState(() => _enviando = true);
    try {
      await widget.onEnviar(codigo);
    } finally {
      if (mounted) setState(() => _enviando = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final tema = Theme.of(context);
    return Scaffold(
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(32),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 360),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Text(
                    'Almacenero',
                    textAlign: TextAlign.center,
                    style: tema.textTheme.headlineMedium,
                  ),
                  const SizedBox(height: 12),
                  const Text(
                    'Para entrar, ingresá el código de invitación '
                    'que te dieron.',
                    textAlign: TextAlign.center,
                  ),
                  const SizedBox(height: 32),
                  TextField(
                    controller: _controller,
                    autofocus: true,
                    autocorrect: false,
                    enableSuggestions: false,
                    maxLength: 64,
                    textAlign: TextAlign.center,
                    textInputAction: TextInputAction.done,
                    onSubmitted: (_) => _enviar(),
                    style: tema.textTheme.headlineSmall?.copyWith(
                      letterSpacing: 4,
                    ),
                    decoration: InputDecoration(
                      labelText: 'Código de invitación',
                      counterText: '',
                      errorText: widget.rechazada
                          ? 'Ese código no sirve: ya se usó, venció o está '
                                'mal escrito. Pedí uno nuevo.'
                          : null,
                      errorMaxLines: 3,
                    ),
                  ),
                  const SizedBox(height: 16),
                  FilledButton(
                    onPressed: _enviando ? null : _enviar,
                    child: const Text('Entrar'),
                  ),
                  if (widget.onGoogle != null) ...[
                    const SizedBox(height: 24),
                    const Text(
                      '¿Ya tenés cuenta?',
                      textAlign: TextAlign.center,
                    ),
                    const SizedBox(height: 8),
                    OutlinedButton.icon(
                      onPressed: _enviando ? null : _google,
                      icon: const GoogleLogo(),
                      label: const Text('Iniciar sesión con Google'),
                    ),
                  ],
                  const SizedBox(height: 32),
                  Text(
                    'Versión ${BuildInfo.actual.version}',
                    textAlign: TextAlign.center,
                    style: tema.textTheme.bodySmall,
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}
