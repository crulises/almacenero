import 'package:almacenero/app_deps.dart';
import 'package:almacenero/data/auth_repository.dart';
import 'package:almacenero/data/user_repository.dart';
import 'package:almacenero/main.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:material_ui/material_ui.dart';

/// Estado de mentira del backend + del celular para probar los flujos de Google.
class _Mundo {
  bool ligada = false;
  bool sugerir = true;
  bool oculto = false;
  Object? errorAlLigar;
  Object? errorAlEntrar;
  final llamadas = <String>[];
  bool sinSesion = false;

  AppDeps deps() => AppDeps(
    loadMe: () async {
      if (sinSesion) throw const InvitacionRequerida();
      return Me(
        id: 'u1',
        alias: 'anon-abc123',
        karma: 5,
        ligada: ligada,
        sugerirLigar: sugerir && !ligada,
      );
    },
    ligarConGoogle: () async {
      llamadas.add('ligar');
      final e = errorAlLigar;
      if (e != null) throw e;
      ligada = true;
    },
    entrarConGoogle: ({String? codigoInvitacion}) async {
      llamadas.add('entrar:${codigoInvitacion ?? '-'}');
      final e = errorAlEntrar;
      if (e != null) {
        errorAlEntrar = null;
        throw e;
      }
      sinSesion = false;
    },
    leerAvisoLigarOculto: () async => oculto,
    ocultarAvisoLigar: () async {
      llamadas.add('ocultar');
      oculto = true;
    },
    guardarInvitacion: (_) async {},
    loadProducto: (_) => throw UnimplementedError(),
    obtenerUbicacion: () => throw UnimplementedError(),
    abrirAjustes: () async {},
    loadLocalesCerca: (_) => throw UnimplementedError(),
    crearLocal: ({required nombre, direccion, required ubicacion}) =>
        throw UnimplementedError(),
    loadHistorial: (_) => throw UnimplementedError(),
    loadVigentes: (_, {ubicacion, referencia = false}) =>
        throw UnimplementedError(),
    cargarPrecio: ({
      required ean,
      required localId,
      required precio,
      required ubicacion,
    }) => throw UnimplementedError(),
  );
}

void main() {
  late _Mundo m;
  setUp(() => m = _Mundo());

  Future<void> abrir(WidgetTester tester) async {
    await tester.pumpWidget(AlmaceneroApp(deps: m.deps()));
    await tester.pumpAndSettle();
  }

  group('tarjeta «Protegé tu cuenta»', () {
    testWidgets('aparece cuando el backend lo sugiere', (tester) async {
      await abrir(tester);
      expect(find.text('Protegé tu cuenta'), findsOneWidget);
    });

    testWidgets('no aparece si no se sugiere', (tester) async {
      m.sugerir = false;
      await abrir(tester);
      expect(find.text('Protegé tu cuenta'), findsNothing);
    });

    testWidgets('no aparece si se la ocultó con «Luego»', (tester) async {
      m.oculto = true;
      await abrir(tester);
      expect(find.text('Protegé tu cuenta'), findsNothing);
    });

    testWidgets('«Luego» la oculta y lo recuerda', (tester) async {
      await abrir(tester);
      await tester.tap(find.text('Luego'));
      await tester.pumpAndSettle();
      expect(find.text('Protegé tu cuenta'), findsNothing);
      expect(m.llamadas, ['ocultar']);
    });

    testWidgets('«Ligar con Google» liga, refresca /me y desaparece', (
      tester,
    ) async {
      await abrir(tester);
      await tester.tap(find.text('Ligar con Google'));
      await tester.pumpAndSettle();
      expect(m.llamadas, ['ligar']);
      expect(find.text('Protegé tu cuenta'), findsNothing);
    });

    testWidgets('si se cierra el selector de Google no pasa nada', (
      tester,
    ) async {
      m.errorAlLigar = const GoogleCancelado();
      await abrir(tester);
      await tester.tap(find.text('Ligar con Google'));
      await tester.pumpAndSettle();
      expect(find.text('Protegé tu cuenta'), findsOneWidget);
      expect(find.byType(SnackBar), findsNothing);
    });

    testWidgets('si ese Google ya tiene cuenta, ofrece entrar con ella', (
      tester,
    ) async {
      m.errorAlLigar = const GoogleYaLigado();
      await abrir(tester);
      await tester.tap(find.text('Ligar con Google'));
      await tester.pumpAndSettle();
      expect(find.text('Ese Google ya tiene una cuenta'), findsOneWidget);
      await tester.tap(find.text('Entrar con esa cuenta'));
      await tester.pumpAndSettle();
      expect(m.llamadas, ['ligar', 'entrar:-']);
    });

    testWidgets('un error inesperado se avisa sin romper', (tester) async {
      m.errorAlLigar = Exception('boom');
      await abrir(tester);
      await tester.tap(find.text('Ligar con Google'));
      await tester.pumpAndSettle();
      expect(find.byType(SnackBar), findsOneWidget);
      expect(find.text('Protegé tu cuenta'), findsOneWidget);
    });
  });

  group('Acerca de › Cuenta', () {
    Future<void> irAAcerca(WidgetTester tester) async {
      await abrir(tester);
      await tester.tap(find.byTooltip('Acerca de'));
      await tester.pumpAndSettle();
    }

    testWidgets('cuenta anónima: ofrece ligarla', (tester) async {
      m.sugerir = false; // aunque no haya tarjeta, desde Acerca se puede
      await irAAcerca(tester);
      expect(find.text('Ligar con Google'), findsOneWidget);
      await tester.tap(find.text('Ligar con Google'));
      await tester.pumpAndSettle();
      expect(m.llamadas, ['ligar']);
      expect(find.text('Tu cuenta está ligada a Google'), findsOneWidget);
    });

    testWidgets('cuenta ligada: lo dice y no ofrece nada', (tester) async {
      m.ligada = true;
      await irAAcerca(tester);
      expect(find.text('Tu cuenta está ligada a Google'), findsOneWidget);
      expect(find.text('Ligar con Google'), findsNothing);
    });
  });

  group('pantalla de invitación › Entrar con Google', () {
    setUp(() => m.sinSesion = true);

    testWidgets('cuenta ya ligada: entra y carga la app', (tester) async {
      await abrir(tester);
      expect(find.text('Código de invitación'), findsOneWidget);
      await tester.tap(find.text('Entrar con Google'));
      await tester.pumpAndSettle();
      expect(m.llamadas, ['entrar:-']);
      expect(find.text('anon-abc123'), findsOneWidget);
    });

    testWidgets('Google nuevo con invitación: pide el código y reintenta', (
      tester,
    ) async {
      m.errorAlEntrar = const InvitacionRequerida();
      await abrir(tester);
      await tester.tap(find.text('Entrar con Google'));
      await tester.pumpAndSettle();
      expect(find.text('Código de invitación'), findsOneWidget);
      await tester.enterText(find.byType(TextField).first, 'bueno');
      await tester.tap(find.text('Entrar'));
      await tester.pumpAndSettle();
      expect(m.llamadas, ['entrar:-', 'entrar:bueno']);
      expect(find.text('anon-abc123'), findsOneWidget);
    });

    testWidgets('código rechazado: lo avisa y sigue en la pantalla', (
      tester,
    ) async {
      m.errorAlEntrar = const InvitacionRequerida();
      await abrir(tester);
      await tester.tap(find.text('Entrar con Google'));
      await tester.pumpAndSettle();
      m.errorAlEntrar = const InvitacionRequerida(rechazada: true);
      await tester.enterText(find.byType(TextField).first, 'malo');
      await tester.tap(find.text('Entrar'));
      await tester.pumpAndSettle();
      expect(find.textContaining('Ese código no sirve'), findsOneWidget);
    });

    testWidgets('si se cierra el selector de Google no pasa nada', (
      tester,
    ) async {
      m.errorAlEntrar = const GoogleCancelado();
      await abrir(tester);
      await tester.tap(find.text('Entrar con Google'));
      await tester.pumpAndSettle();
      expect(find.text('Código de invitación'), findsOneWidget);
      expect(find.byType(SnackBar), findsNothing);
    });
  });
}
