import 'package:android_id/android_id.dart';
import 'package:material_ui/material_ui.dart';

import 'app_deps.dart';
import 'data/api_client.dart';
import 'data/app_info.dart';
import 'data/auth_repository.dart';
import 'data/authed_api.dart';
import 'data/local_repository.dart';
import 'data/location_service.dart';
import 'data/price_repository.dart';
import 'data/product_repository.dart';
import 'data/session.dart';
import 'data/user_repository.dart';
import 'ui/home_screen.dart';
import 'ui/moderacion.dart';

/// URL del backend. Desde el emulador Android, el host es 10.0.2.2.
/// Se cambia con `--dart-define=API_URL=...` (`make apk` lo hace para un celular).
const apiUrl = String.fromEnvironment(
  'API_URL',
  defaultValue: 'http://10.0.2.2:8000',
);

void main() {
  final cuentaBaja = ValueNotifier<bool>(false);
  final api = ApiClient(
    baseUrl: apiUrl,
    onCuentaBaja: () => cuentaBaja.value = true,
    idDispositivo: () => const AndroidId().getId(),
  );
  final auth = AuthRepository(
    api: api,
    store: SecureSessionStore(),
    invitations: SecureInvitationStore(),
  );
  final authed = AuthedApi(api: api, auth: auth);
  final location = LocationService();
  runApp(
    AlmaceneroApp(
      deps: AppDeps(
        cuentaBaja: cuentaBaja,
        verificarCada: const Duration(seconds: 30),
        guardarInvitacion: auth.guardarInvitacion,
        loadInfoApp: () async => InfoApp(
          build: BuildInfo.actual,
          apiUrl: apiUrl,
          ips: await ipsLocales(),
          servidor: await probarServidor(api),
        ),
        loadMe: UserRepository(api: authed).me,
        loadProducto: ProductRepository(api: authed).porEan,
        obtenerUbicacion: location.actual,
        abrirAjustes: location.abrirAjustes,
        loadLocalesCerca: LocalRepository(api: authed).cerca,
        crearLocal: LocalRepository(api: authed).crear,
        cargarPrecio: PriceRepository(api: authed).cargar,
        loadHistorial: PriceRepository(api: authed).historial,
        loadVigentes: PriceRepository(api: authed).vigentes,
      ),
    ),
  );
}

class AlmaceneroApp extends StatelessWidget {
  const AlmaceneroApp({super.key, required this.deps});

  final AppDeps deps;

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Almacenero',
      theme: ThemeData(colorSchemeSeed: Colors.green, useMaterial3: true),
      // La baja se avisa desde cualquier pantalla: reemplaza a toda la app.
      builder: (context, child) {
        final vigilado = VigilanteDeCuenta(deps: deps, child: child!);
        final baja = deps.cuentaBaja;
        if (baja == null) return vigilado;
        return ValueListenableBuilder<bool>(
          valueListenable: baja,
          builder: (_, estaDeBaja, _) =>
              estaDeBaja ? const CuentaBajaScreen() : vigilado,
        );
      },
      home: HomeScreen(deps: deps),
    );
  }
}
