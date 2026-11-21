import 'dart:async';

import 'package:material_ui/material_ui.dart';

import '../app_deps.dart';

import '../data/user_repository.dart';

/// Mensajes de moderación (docs/04 §9): claros y sin tono de castigo.
///
/// El karma se escribe siempre igual: `en -6`, sin paréntesis (misma forma que el
/// «Karma: -6» de la pantalla principal y el «Tu karma ahora es -6» de la carga).
const tituloRestringido = 'Por ahora solo podés consultar.';

String cuerpoRestringido(int? karma) =>
    '${karma == null ? 'Tu karma está muy bajo' : 'Tu karma está en $karma'} '
    'y la carga de precios está pausada para tu cuenta. Un administrador '
    'revisa estos casos y puede ajustarlo.';

/// Versión de una línea, para los errores que aparecen en formularios.
String mensajeRestringido([int? karma]) =>
    '$tituloRestringido ${cuerpoRestringido(karma)}';

const mensajeBaja = 'Tu cuenta fue dada de baja y ya no podés usar Almacenero.';

/// Tarjeta de la pantalla principal según el escalón (nada si está normal).
class AvisoModeracion extends StatelessWidget {
  const AvisoModeracion({super.key, required this.me});

  final Me me;

  @override
  Widget build(BuildContext context) {
    final (titulo, cuerpo) = switch (me.escalon) {
      Escalon.normal => (null, ''),
      Escalon.aviso => (
        'Tu karma está en ${me.karma}.',
        'Seguís usando todo, pero si llega a ${me.umbralRestriccion} vas a '
            'poder consultar y no cargar. Cargar precios correctos lo hace '
            'subir.',
      ),
      Escalon.restringido => (tituloRestringido, cuerpoRestringido(me.karma)),
    };
    if (titulo == null) return const SizedBox.shrink();
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
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    titulo,
                    style: const TextStyle(fontWeight: FontWeight.bold),
                  ),
                  Text(cuerpo),
                ],
              ),
            ),
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
                'Si creés que es un error, contactá a los administradores de Almacenero.',
                textAlign: TextAlign.center,
              ),
            ],
          ),
        ),
      ),
    );
  }
}

/// Mientras la app está abierta, consulta `/me` cada tanto y al volver al primer plano.
/// Si el backend contesta `cuenta_baja`, el cliente HTTP avisa y la app pasa a la pantalla
/// de baja sin que la persona toque nada (el backend no puede «empujar» el aviso).
class VigilanteDeCuenta extends StatefulWidget {
  const VigilanteDeCuenta({super.key, required this.deps, required this.child});

  final AppDeps deps;
  final Widget child;

  @override
  State<VigilanteDeCuenta> createState() => _VigilanteDeCuentaState();
}

class _VigilanteDeCuentaState extends State<VigilanteDeCuenta>
    with WidgetsBindingObserver {
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    final cada = widget.deps.verificarCada;
    if (cada != null) _timer = Timer.periodic(cada, (_) => _verificar());
  }

  /// El error se ignora: si es una baja, ya lo avisó el cliente HTTP.
  void _verificar() => widget.deps.loadMe().ignore();

  @override
  void didChangeAppLifecycleState(AppLifecycleState estado) {
    if (estado == AppLifecycleState.resumed &&
        widget.deps.verificarCada != null) {
      _verificar();
    }
  }

  @override
  void dispose() {
    _timer?.cancel();
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => widget.child;
}
