import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;

/// Error de la API: respuesta no-2xx, o falla de red (statusCode == null).
class ApiException implements Exception {
  ApiException(this.message, {this.statusCode, this.detail});

  final String message;
  final int? statusCode;

  /// El `detail` de la respuesta de error (texto o JSON), si lo hay.
  final Object? detail;

  bool get isUnauthorized => statusCode == 401;

  /// Demasiados pedidos o cargas: hay que esperar.
  bool get isRateLimited => statusCode == 429;

  /// La cuenta fue dada de baja (403 `cuenta_baja`): ya no puede usar la app.
  /// No se reintenta ni se crea otra cuenta sola.
  bool get isCuentaBaja => statusCode == 403 && codigo == 'cuenta_baja';

  /// Karma muy bajo (403 `cuenta_restringida`): puede consultar pero no cargar.
  bool get isCuentaRestringida =>
      statusCode == 403 && codigo == 'cuenta_restringida';

  /// El `codigo` del backend dentro del `detail` (p. ej. `invitacion_invalida`).
  String? get codigo {
    final d = detail;
    return d is Map ? d['codigo'] as String? : null;
  }

  @override
  String toString() => 'ApiException($statusCode): $message';
}

/// Cliente HTTP del backend (`/v1`). El cliente habla SOLO con el backend.
class ApiClient {
  ApiClient({
    required this.baseUrl,
    http.Client? httpClient,
    this.onCuentaBaja,
    this.idDispositivo,
  }) : _http = httpClient ?? http.Client();

  final String baseUrl;

  /// Se llama cuando CUALQUIER pedido recibe 403 `cuenta_baja`, para que la app
  /// pase a la pantalla de baja en el momento, sin esperar a volver al inicio.
  final void Function()? onCuentaBaja;

  /// ANDROID_ID del celular (docs/04 §9, «Dispositivo»). Se manda SOLO en `/auth/*`
  /// (alta y renovación de sesión) y en `/me` (cada arranque), no en cada pedido. Si no se puede leer, no se manda.
  final Future<String?> Function()? idDispositivo;
  final http.Client _http;

  Future<Map<String, dynamic>> get(String path, {String? token}) async =>
      await _send('GET', path, token: token) as Map<String, dynamic>;

  /// Para endpoints que devuelven una lista JSON (por ejemplo `/locales`).
  Future<List<dynamic>> getList(String path, {String? token}) async =>
      await _send('GET', path, token: token) as List<dynamic>;

  Future<Map<String, dynamic>> post(
    String path, {
    Map<String, dynamic>? body,
    String? token,
  }) async =>
      await _send('POST', path, body: body, token: token)
          as Map<String, dynamic>;

  Future<Object?> _send(
    String method,
    String path, {
    Map<String, dynamic>? body,
    String? token,
  }) async {
    final request = http.Request(method, Uri.parse('$baseUrl/v1$path'));
    request.headers['Accept'] = 'application/json';
    if (token != null) request.headers['Authorization'] = 'Bearer $token';
    if (path.startsWith('/auth/') || path == '/me') {
      final id = await _idDispositivo();
      if (id != null) request.headers['X-Device-Id'] = id;
    }
    if (body != null) {
      request.headers['Content-Type'] = 'application/json';
      request.body = jsonEncode(body);
    }
    final http.Response response;
    try {
      response = await http.Response.fromStream(
        await _http.send(request).timeout(const Duration(seconds: 15)),
      );
    } on TimeoutException {
      throw ApiException('Tiempo de espera agotado');
    } on http.ClientException catch (e) {
      throw ApiException('Sin conexión con el servidor: ${e.message}');
    }
    if (response.statusCode >= 200 && response.statusCode < 300) {
      return jsonDecode(utf8.decode(response.bodyBytes));
    }
    final error = ApiException(
      'Error ${response.statusCode}',
      statusCode: response.statusCode,
      detail: _detalle(response),
    );
    if (error.isCuentaBaja) onCuentaBaja?.call();
    throw error;
  }

  Future<String?> _idDispositivo() async {
    try {
      final id = await idDispositivo?.call();
      return (id == null || id.isEmpty) ? null : id;
    } on Object {
      return null; // sin ID la app anda igual: solo no deja rastro
    }
  }

  static Object? _detalle(http.Response response) {
    try {
      final cuerpo = jsonDecode(utf8.decode(response.bodyBytes));
      return cuerpo is Map<String, dynamic> ? cuerpo['detail'] : null;
    } on Object {
      return null;
    }
  }
}
