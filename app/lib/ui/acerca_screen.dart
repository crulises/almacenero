import 'package:material_ui/material_ui.dart';

import '../app_deps.dart';
import '../data/app_info.dart';
import '../data/user_repository.dart';
import 'google_logo.dart';
import 'tarjeta_ligar.dart';

/// Un enlace tocable: texto visible y destino.
typedef Enlace = (String, String);

/// Una fuente de datos abiertos con lo que exige su licencia (docs/05, §4.3).
/// Los textos son los de ese doc: si cambian, que sea para nombrar más, nunca menos.
class FuenteDatos {
  const FuenteDatos({
    required this.nombre,
    required this.aporta,
    required this.licencia,
    required this.texto,
    required this.enlaces,
  });

  final String nombre;
  final String aporta;
  final String licencia;
  final String texto;
  final List<Enlace> enlaces;
}

const fuentesDatos = <FuenteDatos>[
  FuenteDatos(
    nombre: 'Open Food Facts',
    aporta: 'Productos: nombre, marca y tamaño',
    licencia: 'ODbL 1.0 · contenidos DbCL 1.0 · imágenes CC BY-SA 3.0',
    texto:
        'Datos de productos: Open Food Facts (openfoodfacts.org), una base '
        'colaborativa disponible bajo la Open Database License (ODbL) 1.0; sus '
        'contenidos individuales, bajo la Database Contents License (DbCL) 1.0. '
        'Las imágenes de productos se publican bajo Creative Commons '
        'Atribución-CompartirIgual (CC BY-SA) 3.0 y son de sus autores; '
        'Almacenero solo las enlaza.',
    enlaces: [
      ('Open Food Facts', 'https://openfoodfacts.org'),
      ('ODbL 1.0', 'https://opendatacommons.org/licenses/odbl/1-0/'),
      ('DbCL 1.0', 'https://opendatacommons.org/licenses/dbcl/1-0/'),
      ('CC BY-SA 3.0', 'https://creativecommons.org/licenses/by-sa/3.0/'),
      ('Términos', 'https://world.openfoodfacts.org/terms-of-use'),
    ],
  ),
  FuenteDatos(
    nombre: 'SEPA · Precios Claros',
    aporta: 'Productos y sucursales de Argentina',
    licencia: 'CC BY 4.0',
    texto:
        'Datos de productos y sucursales de Argentina: Secretaría de Comercio '
        'de la Nación, Sistema Electrónico de Publicidad de Precios Argentinos '
        '(SEPA, «Precios Claros»), licencia Creative Commons Atribución 4.0 '
        'Internacional (CC BY 4.0). Los datos fueron normalizados y combinados '
        'por Almacenero.',
    enlaces: [
      ('SEPA', 'https://datos.produccion.gob.ar/dataset/sepa-precios'),
      ('CC BY 4.0', 'https://creativecommons.org/licenses/by/4.0/deed.es'),
    ],
  ),
  FuenteDatos(
    nombre: 'OpenStreetMap',
    aporta: 'Locales (supermercados y almacenes) y el mapa',
    licencia: 'ODbL 1.0',
    texto:
        'Datos de locales: © colaboradores de OpenStreetMap. Disponibles bajo '
        'la Open Database License (ODbL) 1.0.',
    enlaces: [
      (
        '© colaboradores de OpenStreetMap',
        'https://www.openstreetmap.org/copyright',
      ),
      ('ODbL 1.0', 'https://opendatacommons.org/licenses/odbl/1-0/'),
    ],
  ),
];

/// «Acerca de»: qué app es, de dónde salen los datos y con qué licencia, y las
/// licencias de las librerías. Sirve también para diagnosticar la conexión (versión,
/// servidor, IP) sin adivinar.
class AcercaScreen extends StatefulWidget {
  const AcercaScreen({super.key, required this.deps});

  final AppDeps deps;

  @override
  State<AcercaScreen> createState() => _AcercaScreenState();
}

class _AcercaScreenState extends State<AcercaScreen> {
  late final Future<InfoApp> _info = widget.deps.loadInfoApp();
  late Future<Me> _me = widget.deps.loadMe()..ignore();

  Future<void> _ligar() async {
    final cambio = await ligarCuentaConGoogle(context, widget.deps);
    if (cambio && mounted) {
      setState(() {
        _me = widget.deps.loadMe()..ignore();
      });
    }
  }

  /// «Cuenta»: si ya está asociada a Google lo dice; si no, deja asociarla (sin esperar a que
  /// aparezca la tarjeta del inicio). Si no se pudo saber, no se muestra nada.
  Widget _cuenta(BuildContext context) {
    return FutureBuilder<Me>(
      future: _me,
      builder: (context, snapshot) {
        final me = snapshot.data;
        if (me == null) return const SizedBox.shrink();
        final tema = Theme.of(context).textTheme;
        return Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('Cuenta', style: tema.titleLarge),
            const SizedBox(height: 8),
            if (me.ligada)
              const Text('Tu cuenta está asociada a Google')
            else ...[
              const Text(
                'Asociá una cuenta de Google para poder iniciar sesión en esta '
                'cuenta desde otro celular o después de reinstalar la app.',
              ),
              const SizedBox(height: 8),
              OutlinedButton.icon(
                onPressed: _ligar,
                icon: const GoogleLogo(),
                label: const Text('Asociar cuenta de Google'),
              ),
            ],
            const SizedBox(height: 32),
          ],
        );
      },
    );
  }

  @override
  Widget build(BuildContext context) {
    final tema = Theme.of(context).textTheme;
    return Scaffold(
      appBar: AppBar(title: const Text('Acerca de')),
      body: ListView(
        padding: const EdgeInsets.all(24),
        children: [
          Text('Almacenero', style: tema.headlineMedium),
          Text('Versión ${BuildInfo.actual.version}', style: tema.bodyMedium),
          const SizedBox(height: 16),
          _tarjetaInfo(context),
          const SizedBox(height: 32),
          _cuenta(context),
          Text('Fuentes de datos', style: tema.titleLarge),
          const SizedBox(height: 8),
          const Text(
            'Almacenero usa datos abiertos de estas fuentes. Gracias a quienes '
            'los mantienen.',
          ),
          const SizedBox(height: 8),
          for (final f in fuentesDatos) _tarjetaFuente(context, f),
          const SizedBox(height: 8),
          const Text(
            'Los precios que ves los cargan personas como vos; no provienen de '
            'estas fuentes.',
          ),
          const SizedBox(height: 24),
          OutlinedButton.icon(
            icon: const Icon(Icons.description_outlined),
            label: const Text('Licencias de librerías'),
            onPressed: () => showLicensePage(
              context: context,
              applicationName: 'Almacenero',
              applicationVersion: BuildInfo.actual.version,
            ),
          ),
        ],
      ),
    );
  }

  /// Qué app es esta y a dónde habla: para confirmar que se instaló el APK correcto
  /// y diagnosticar la conexión.
  Widget _tarjetaInfo(BuildContext context) {
    final estilo = Theme.of(context).textTheme.bodySmall;
    return FutureBuilder<InfoApp>(
      future: _info,
      builder: (context, snapshot) {
        final info = snapshot.data;
        final filas = <(String, String)>[
          (
            'Versión',
            info == null
                ? BuildInfo.actual.version
                : '${info.build.version} (${info.build.commit})',
          ),
          if (info != null) ('Compilada', info.build.compilado),
          if (info != null) ('Servidor', info.apiUrl),
          if (info != null) ('Estado', info.servidor),
          if (info != null)
            (
              'IP del celular',
              info.ips.isEmpty
                  ? 'sin red'
                  : info.ips.map((i) => '${i.ip} (${i.interfaz})').join(', '),
            ),
        ];
        return Card(
          child: Padding(
            padding: const EdgeInsets.all(12),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                for (final (nombre, valor) in filas)
                  Text('$nombre: $valor', style: estilo),
              ],
            ),
          ),
        );
      },
    );
  }

  Widget _tarjetaFuente(BuildContext context, FuenteDatos f) {
    final tema = Theme.of(context).textTheme;
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(f.nombre, style: tema.titleMedium),
            const SizedBox(height: 4),
            Text('Aporta: ${f.aporta}', style: tema.bodySmall),
            Text('Licencia: ${f.licencia}', style: tema.bodySmall),
            const SizedBox(height: 8),
            Text(f.texto),
            Wrap(
              spacing: 4,
              children: [
                for (final (texto, url) in f.enlaces)
                  TextButton(
                    onPressed: () => widget.deps.abrirEnlace(Uri.parse(url)),
                    child: Text(texto),
                  ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}
