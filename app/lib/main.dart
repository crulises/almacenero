import 'package:android_id/android_id.dart';
import 'package:flutter/foundation.dart';
import 'package:material_ui/material_ui.dart';
import 'package:url_launcher/url_launcher.dart';

import 'app_deps.dart';
import 'data/api_client.dart';
import 'data/app_info.dart';
import 'data/auth_repository.dart';
import 'data/cola_eventos.dart';
import 'data/info_dispositivo.dart';
import 'data/authed_api.dart';
import 'data/local_repository.dart';
import 'data/location_service.dart';
import 'data/price_repository.dart';
import 'data/product_repository.dart';
import 'data/recientes.dart';
import 'data/session.dart';
import 'data/sugerencia_repository.dart';
import 'data/user_repository.dart';
import 'ui/home_screen.dart';
import 'ui/moderacion.dart';
import 'ui/recientes.dart';

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
  // Eventos de estadística: en memoria, por lotes, y si no hay red se descartan.
  final eventos = ColaEventos(enviar: EventosRepository(api: authed).enviar);
  // `app.abierta` lleva datos del celular; si leerlos falla igual se anota, sin ellos.
  armarDatosApertura(lectoresReales())
      .catchError((_) => <String, Object?>{})
      .then((datos) => eventos.registrar('app.abierta', datos));
  final productos = ProductRepository(api: authed);
  final precios = PriceRepository(api: authed);
  // Recientes: solo en el celular. Con red se refrescan; sin red se ve lo guardado.
  final recientes = RecientesStore();
  // Cuántos recientes mostrar lo decide el servidor (`config.recientes_max`); sin red se usa lo
  // último que se supo, o el valor por defecto.
  _leerMaximoRecientes(authed).then((n) {
    if (n != null) recientes.fijarMaximo(n);
  }).ignore();
  final recientesService = RecientesService(
    loadProducto: productos.porEan,
    loadVigentes: precios.vigentes,
    obtenerUbicacion: location.actual,
  );
  runApp(
    AlmaceneroApp(
      deps: AppDeps(
        leerRecientes: recientes.leer,
        guardarReciente: recientes.registrar,
        refrescarReciente: (r) async {
          final nuevo = await recientesService.refrescar(r);
          if (nuevo != null) {
            await recientes.registrar(nuevo, moverAlTope: false);
          }
          return nuevo;
        },
        registrarEvento: eventos.registrar,
        vaciarEventos: eventos.vaciar,
        cuentaBaja: cuentaBaja,
        despertando: api.despertando,
        verificarCada: const Duration(seconds: 30),
        guardarInvitacion: auth.guardarInvitacion,
        abrirEnlace: (url) async {
          await launchUrl(url, mode: LaunchMode.externalApplication);
        },
        loadInfoApp: () async => InfoApp(
          build: BuildInfo.actual,
          apiUrl: apiUrl,
          ips: await ipsLocales(),
          servidor: await probarServidor(api),
        ),
        sugerir: SugerenciaRepository(api: authed).enviar,
        loadEstandares: SugerenciaRepository(api: authed).estandares,
        loadMe: UserRepository(api: authed).me,
        cambiarAlias: UserRepository(api: authed).cambiarAlias,
        loadProducto: productos.porEan,
        obtenerUbicacion: location.actual,
        abrirAjustes: location.abrirAjustes,
        loadLocalesCerca: LocalRepository(api: authed).cerca,
        crearLocal: LocalRepository(api: authed).crear,
        cargarPrecio: precios.cargar,
        loadHistorial: precios.historial,
        loadVigentes: precios.vigentes,
      ),
    ),
  );
}

Future<int?> _leerMaximoRecientes(AuthedApi api) async {
  try {
    for (final c in await api.getList('/config')) {
      if (c is Map && c['clave'] == 'recientes_max' && c['valor'] is int) {
        return c['valor'] as int;
      }
    }
  } catch (_) {}
  return null;
}

class AlmaceneroApp extends StatelessWidget {
  const AlmaceneroApp({super.key, required this.deps});

  final AppDeps deps;

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Almacenero',
      theme: ThemeData(colorSchemeSeed: Colors.green, useMaterial3: true),
      navigatorObservers: [routeObserver],
      // La baja se avisa desde cualquier pantalla: reemplaza a toda la app.
      builder: (context, child) {
        final vigilado = AvisoDespertando(
          despertando: deps.despertando,
          child: VigilanteDeCuenta(deps: deps, child: child!),
        );
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

/// «Despertando servidor…» sobre cualquier pantalla mientras un pedido tarda: el backend
/// (Fly.io) se apaga solo y el primer pedido después de un rato espera su arranque.
class AvisoDespertando extends StatelessWidget {
  const AvisoDespertando({super.key, this.despertando, required this.child});

  final ValueListenable<bool>? despertando;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    final escucha = despertando;
    if (escucha == null) return child;
    return Stack(
      children: [
        child,
        ValueListenableBuilder<bool>(
          valueListenable: escucha,
          builder: (context, activo, _) {
            if (!activo) return const SizedBox.shrink();
            return Positioned(
              left: 0,
              right: 0,
              bottom: 0,
              child: SafeArea(
                child: Material(
                  color: Theme.of(context).colorScheme.inverseSurface,
                  child: Padding(
                    padding: const EdgeInsets.all(12),
                    child: Row(
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        const SizedBox(
                          width: 16,
                          height: 16,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        ),
                        const SizedBox(width: 12),
                        Text(
                          'Despertando servidor…',
                          style: TextStyle(
                            color: Theme.of(context)
                                .colorScheme
                                .onInverseSurface,
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
              ),
            );
          },
        ),
      ],
    );
  }
}
