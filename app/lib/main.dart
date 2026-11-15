import 'package:material_ui/material_ui.dart';

import 'data/api_client.dart';
import 'data/auth_repository.dart';
import 'data/authed_api.dart';
import 'data/product_repository.dart';
import 'data/session.dart';
import 'data/user_repository.dart';
import 'ui/home_screen.dart';

/// URL del backend. Desde el emulador Android, el host es 10.0.2.2.
/// Se cambia con `--dart-define=API_URL=...`.
const apiUrl = String.fromEnvironment(
  'API_URL',
  defaultValue: 'http://10.0.2.2:8000',
);

void main() {
  final api = ApiClient(baseUrl: apiUrl);
  final auth = AuthRepository(api: api, store: SecureSessionStore());
  final authed = AuthedApi(api: api, auth: auth);
  runApp(
    AlmaceneroApp(
      loadMe: UserRepository(api: authed).me,
      loadProducto: ProductRepository(api: authed).porEan,
    ),
  );
}

class AlmaceneroApp extends StatelessWidget {
  const AlmaceneroApp({
    super.key,
    required this.loadMe,
    required this.loadProducto,
  });

  final Future<Me> Function() loadMe;
  final Future<Producto> Function(String ean) loadProducto;

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Almacenero',
      theme: ThemeData(colorSchemeSeed: Colors.green, useMaterial3: true),
      home: HomeScreen(loadMe: loadMe, loadProducto: loadProducto),
    );
  }
}
