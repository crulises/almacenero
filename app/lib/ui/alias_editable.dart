import 'package:material_ui/material_ui.dart';

import '../data/api_client.dart';
import '../data/user_repository.dart';

/// El alias de la pantalla de inicio. Si el backend habilitó el cambio para este usuario
/// (`Me.puedeCambiarAlias`) muestra un lápiz a la derecha: al tocarlo el texto pasa a ser
/// editable y, al salir del campo (pierde el foco o se confirma con el teclado), se manda al
/// servidor. Si no cambió no se manda nada; si el servidor lo rechaza vuelve al anterior y
/// explica por qué.
class AliasEditable extends StatefulWidget {
  const AliasEditable({super.key, required this.me, required this.onGuardar});

  final Me me;

  /// Guarda el alias y devuelve el que quedó. Lanza [ApiException] si lo rechazan.
  final Future<String> Function(String alias) onGuardar;

  @override
  State<AliasEditable> createState() => _AliasEditableState();
}

class _AliasEditableState extends State<AliasEditable> {
  late String _alias = widget.me.alias;
  final _controller = TextEditingController();
  final _foco = FocusNode();
  bool _editando = false;
  bool _guardando = false;

  @override
  void initState() {
    super.initState();
    _foco.addListener(() {
      if (!_foco.hasFocus && _editando) _guardar();
    });
  }

  @override
  void didUpdateWidget(AliasEditable anterior) {
    super.didUpdateWidget(anterior);
    // Si /me trae otro alias (lo cambió un admin, por ejemplo) y no estamos editando, se actualiza.
    if (!_editando && !_guardando && widget.me.alias != anterior.me.alias) {
      _alias = widget.me.alias;
    }
  }

  @override
  void dispose() {
    _controller.dispose();
    _foco.dispose();
    super.dispose();
  }

  void _editar() {
    setState(() {
      _controller.text = _alias;
      _controller.selection = TextSelection(
        baseOffset: 0,
        extentOffset: _alias.length,
      );
      _editando = true;
    });
    _foco.requestFocus();
  }

  Future<void> _guardar() async {
    // Confirmar con el teclado y perder el foco disparan esto dos veces: pasa una sola.
    if (!_editando || _guardando) return;
    final nuevo = _controller.text.trim();
    if (nuevo.isEmpty || nuevo == _alias) {
      setState(() => _editando = false);
      return;
    }
    // Se sigue viendo el anterior hasta que el servidor confirma; si lo rechaza, queda ese.
    setState(() {
      _guardando = true;
      _editando = false;
    });
    final mensajes = ScaffoldMessenger.maybeOf(context);
    try {
      final guardado = await widget.onGuardar(nuevo);
      if (mounted) setState(() => _alias = guardado);
    } on ApiException catch (e) {
      mensajes?.showSnackBar(
        SnackBar(
          content: Text(
            e.detail == null
                ? 'No se pudo cambiar el alias: ${e.message}'
                : e.explicacion,
          ),
        ),
      );
    } finally {
      if (mounted) setState(() => _guardando = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final estilo = Theme.of(context).textTheme.headlineSmall;
    if (_editando) {
      return Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 280),
          child: TextField(
            controller: _controller,
            focusNode: _foco,
            style: estilo,
            textAlign: TextAlign.center,
            maxLength: 24,
            textInputAction: TextInputAction.done,
            onSubmitted: (_) => _guardar(),
            decoration: const InputDecoration(
              counterText: '',
              hintText: 'Tu alias',
            ),
          ),
        ),
      );
    }
    return Row(
      mainAxisAlignment: MainAxisAlignment.center,
      children: [
        Flexible(child: Text(_alias, style: estilo)),
        if (widget.me.puedeCambiarAlias)
          IconButton(
            tooltip: 'Cambiar alias',
            icon: const Icon(Icons.edit),
            onPressed: _guardando ? null : _editar,
          ),
      ],
    );
  }
}
