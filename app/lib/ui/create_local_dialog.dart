import 'package:material_ui/material_ui.dart';

import '../app_deps.dart';
import '../data/local_repository.dart';
import '../data/location_service.dart';

/// Pide el nombre de un local nuevo y lo crea donde está parado el usuario.
/// Devuelve el [Local] creado, o null si se cancela.
Future<Local?> mostrarCrearLocal(
  BuildContext context, {
  required AppDeps deps,
  required Ubicacion ubicacion,
}) => showDialog<Local>(
  context: context,
  builder: (_) => _CrearLocalDialog(deps: deps, ubicacion: ubicacion),
);

class _CrearLocalDialog extends StatefulWidget {
  const _CrearLocalDialog({required this.deps, required this.ubicacion});

  final AppDeps deps;
  final Ubicacion ubicacion;

  @override
  State<_CrearLocalDialog> createState() => _CrearLocalDialogState();
}

class _CrearLocalDialogState extends State<_CrearLocalDialog> {
  final _nombre = TextEditingController();
  final _direccion = TextEditingController();
  String? _errorCampo;
  String? _error;
  bool _creando = false;

  @override
  void dispose() {
    _nombre.dispose();
    _direccion.dispose();
    super.dispose();
  }

  Future<void> _crear() async {
    final nombre = _nombre.text.trim();
    if (nombre.isEmpty) {
      setState(() => _errorCampo = 'Ingresá el nombre del local');
      return;
    }
    setState(() {
      _errorCampo = null;
      _error = null;
      _creando = true;
    });
    try {
      final local = await widget.deps.crearLocal(
        nombre: nombre,
        direccion: _direccion.text.trim(),
        ubicacion: widget.ubicacion,
      );
      if (mounted) Navigator.of(context).pop(local);
    } on Object catch (e) {
      if (!mounted) return;
      setState(() {
        _creando = false;
        _error = switch (clasificarErrorAltaLocal(e)) {
          AltaLocalError.duplicado =>
            'Ya hay un local con ese nombre acá. Elegilo de la lista, o '
                'ponele otro nombre si es distinto.',
          AltaLocalError.sinPermiso =>
            'Por ahora solo un administrador puede crear locales.',
          AltaLocalError.limiteDiario =>
            'Llegaste al máximo de locales nuevos por hoy.',
          AltaLocalError.datosInvalidos => 'Revisá el nombre del local.',
          AltaLocalError.otro => 'No pudimos crear el local. Probá de nuevo.',
        };
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('Crear local aquí'),
      content: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text(
              'Se crea en tu ubicación actual y queda sin verificar hasta '
              'que lo revise un administrador.',
            ),
            const SizedBox(height: 16),
            TextField(
              controller: _nombre,
              autofocus: true,
              enabled: !_creando,
              textCapitalization: TextCapitalization.words,
              decoration: InputDecoration(
                labelText: 'Nombre',
                errorText: _errorCampo,
              ),
            ),
            TextField(
              controller: _direccion,
              enabled: !_creando,
              decoration: const InputDecoration(
                labelText: 'Dirección (opcional)',
              ),
            ),
            if (_error != null) ...[
              const SizedBox(height: 12),
              Text(
                _error!,
                style: TextStyle(color: Theme.of(context).colorScheme.error),
              ),
            ],
          ],
        ),
      ),
      actions: [
        TextButton(
          onPressed: _creando ? null : () => Navigator.of(context).pop(),
          child: const Text('Cancelar'),
        ),
        FilledButton(
          onPressed: _creando ? null : _crear,
          child: const Text('Crear local'),
        ),
      ],
    );
  }
}
