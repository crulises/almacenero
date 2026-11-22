import 'package:material_ui/material_ui.dart';

import '../app_deps.dart';
import '../data/api_client.dart';
import '../data/product_repository.dart';
import 'estandares_screen.dart';

/// Formulario de un moderador: corrige un producto del catálogo o da de alta uno nuevo.
/// No cambia el catálogo: manda una sugerencia que un admin aprueba o rechaza.
/// [producto] == null es un alta (el EAN no está en el catálogo).
class SugerirScreen extends StatefulWidget {
  const SugerirScreen({
    super.key,
    required this.ean,
    required this.deps,
    this.producto,
  });

  final String ean;
  final AppDeps deps;
  final Producto? producto;

  @override
  State<SugerirScreen> createState() => _SugerirScreenState();
}

class _SugerirScreenState extends State<SugerirScreen> {
  static const _unidades = ['g', 'kg', 'ml', 'l', 'u'];

  late final _nombre = TextEditingController(text: widget.producto?.nombre);
  late final _marca = TextEditingController(text: widget.producto?.marca);
  late final _tamano = TextEditingController(
    text: _numero(widget.producto?.tamanoValor),
  );
  late final _pack = TextEditingController(
    text: widget.producto?.packCantidad?.toString(),
  );
  late final _presentacion = TextEditingController(
    text: widget.producto?.presentacion,
  );
  final _motivo = TextEditingController();
  late String? _unidad = widget.producto?.tamanoUnidad;

  String? _error;
  bool _enviando = false;

  bool get _esAlta => widget.producto == null;

  static String? _numero(num? v) => v == null
      ? null
      : (v == v.roundToDouble() ? v.toInt().toString() : v.toString());

  @override
  void dispose() {
    for (final c in [_nombre, _marca, _tamano, _pack, _presentacion, _motivo]) {
      c.dispose();
    }
    super.dispose();
  }

  /// Los campos que cambian (corrección) o que se completaron (alta). `null` = borrar.
  /// Devuelve `null` y deja el motivo en [_error] si algo no cierra.
  Map<String, Object?>? _cambios() {
    final p = widget.producto;
    final cambios = <String, Object?>{};
    String? texto(TextEditingController c) {
      final t = c.text.trim();
      return t.isEmpty ? null : t;
    }

    void texto2(String clave, TextEditingController c, String? actual) {
      final nuevo = texto(c);
      if (nuevo != actual && !(nuevo == null && actual == null)) {
        cambios[clave] = nuevo;
      }
    }

    texto2('nombre', _nombre, p?.nombre);
    texto2('marca', _marca, p?.marca);
    texto2('presentacion', _presentacion, p?.presentacion?.toLowerCase());

    final tamanoTexto = texto(_tamano)?.replaceAll(',', '.');
    final valor = tamanoTexto == null ? null : num.tryParse(tamanoTexto);
    if (tamanoTexto != null && (valor == null || valor <= 0)) {
      _error = 'El tamaño tiene que ser un número mayor a cero.';
      return null;
    }
    if ((valor == null) != (_unidad == null)) {
      _error = 'El tamaño y la unidad van juntos (o los dos vacíos).';
      return null;
    }
    if (valor != p?.tamanoValor || _unidad != p?.tamanoUnidad) {
      cambios['tamano_valor'] = valor?.toString();
      cambios['tamano_unidad'] = _unidad;
    }

    final packTexto = texto(_pack);
    final packCargado = packTexto == null ? null : int.tryParse(packTexto);
    if (packTexto != null && (packCargado == null || packCargado < 1)) {
      _error = 'El pack tiene que ser un número entero desde 2 (o vacío).';
      return null;
    }
    // «Pack de 1» no es un pack: es lo mismo que dejarlo vacío.
    final pack = packCargado == 1 ? null : packCargado;
    if (pack != p?.packCantidad) cambios['pack_cantidad'] = pack;

    if (_esAlta && texto(_nombre) == null) {
      _error = 'Para dar de alta un producto hace falta el nombre.';
      return null;
    }
    if (!_esAlta && texto(_nombre) == null) {
      _error = 'El nombre no puede quedar vacío.';
      return null;
    }
    if (cambios.isEmpty) {
      _error = 'No cambiaste nada.';
      return null;
    }
    return cambios;
  }

  Future<void> _enviar() async {
    setState(() => _error = null);
    final cambios = _cambios();
    if (cambios == null) {
      setState(() {});
      return;
    }
    setState(() => _enviando = true);
    try {
      await widget.deps.sugerir(
        ean: widget.ean,
        cambios: cambios,
        motivo: _motivo.text,
      );
      if (!mounted) return;
      Navigator.of(context).pop(true);
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() {
        _enviando = false;
        _error = e.isCuentaRestringida
            ? 'Tu karma está muy bajo: por ahora no podés sugerir.'
            : (e.statusCode == null
                  ? 'No pudimos conectar con el servidor.'
                  : e.explicacion);
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final texto = Theme.of(context).textTheme;
    return Scaffold(
      appBar: AppBar(
        title: Text(_esAlta ? 'Dar de alta' : 'Sugerir corrección'),
      ),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Text('EAN ${widget.ean}', style: texto.bodySmall),
          const SizedBox(height: 4),
          Text(
            _esAlta
                ? 'Este producto no está en el catálogo. Cargá lo que figura en '
                      'el envase; un admin lo revisa antes de publicarlo.'
                : 'Cambiá lo que esté mal. Un admin lo revisa antes de '
                      'aplicarlo.',
          ),
          const SizedBox(height: 16),
          TextField(
            controller: _nombre,
            textCapitalization: TextCapitalization.words,
            decoration: const InputDecoration(
              labelText: 'Nombre',
              helperText: 'Sin marca, tamaño ni envase.',
            ),
          ),
          const SizedBox(height: 12),
          TextField(
            controller: _marca,
            textCapitalization: TextCapitalization.words,
            decoration: const InputDecoration(labelText: 'Marca'),
          ),
          const SizedBox(height: 12),
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(
                child: TextField(
                  controller: _tamano,
                  keyboardType: const TextInputType.numberWithOptions(
                    decimal: true,
                  ),
                  decoration: const InputDecoration(labelText: 'Tamaño'),
                ),
              ),
              const SizedBox(width: 12),
              SizedBox(
                width: 110,
                child: DropdownButtonFormField<String?>(
                  initialValue: _unidad,
                  decoration: const InputDecoration(labelText: 'Unidad'),
                  items: [
                    const DropdownMenuItem<String?>(
                      value: null,
                      child: Text('—'),
                    ),
                    for (final u in _unidades)
                      DropdownMenuItem<String?>(value: u, child: Text(u)),
                  ],
                  onChanged: (v) => setState(() => _unidad = v),
                ),
              ),
            ],
          ),
          const SizedBox(height: 12),
          TextField(
            controller: _pack,
            keyboardType: TextInputType.number,
            decoration: const InputDecoration(
              labelText: 'Pack de',
              helperText: 'Desde 2 unidades; el tamaño es el total.',
            ),
          ),
          const SizedBox(height: 12),
          TextField(
            controller: _presentacion,
            decoration: const InputDecoration(
              labelText: 'Presentación',
              helperText: 'botella, lata, caja, doypack…',
            ),
          ),
          const SizedBox(height: 12),
          TextField(
            controller: _motivo,
            maxLength: 300,
            maxLines: 2,
            decoration: const InputDecoration(labelText: 'Por qué (opcional)'),
          ),
          Align(
            alignment: Alignment.centerLeft,
            child: TextButton.icon(
              icon: const Icon(Icons.help_outline),
              label: const Text('Ver estándares de carga'),
              onPressed: () => Navigator.of(context).push(
                MaterialPageRoute<void>(
                  builder: (_) => EstandaresScreen(deps: widget.deps),
                ),
              ),
            ),
          ),
          if (_error != null) ...[
            const SizedBox(height: 8),
            Text(
              _error!,
              style: TextStyle(color: Theme.of(context).colorScheme.error),
            ),
          ],
          const SizedBox(height: 16),
          FilledButton(
            onPressed: _enviando ? null : _enviar,
            child: _enviando
                ? const SizedBox(
                    height: 20,
                    width: 20,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : const Text('Enviar sugerencia'),
          ),
        ],
      ),
    );
  }
}
