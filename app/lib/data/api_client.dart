import 'dart:async';
import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;

/// Error de la API: respuesta no-2xx, o falla de red (statusCode == null).
class ApiException implements Exception {
  ApiException(
    this.message, {
    this.statusCode,
    this.detail,
    this.esTimeout = false,
  });

  final String message;
  final int? statusCode;

  /// El servidor no contestó a tiempo (hay red, pero no respondió). Se distingue de
  /// «sin red» (statusCode == null y esTimeout == false) porque se arreglan distinto.
  final bool esTimeout;

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

  /// Qué pasó y cómo resolverlo, tal como lo explica el backend (Doc 4 §10-E): el `mensaje` de
  /// la regla violada más su guía; si el `detail` es un texto, ese texto; si no, [message].
  String get explicacion {
    final d = detail;
    if (d is Map && d['mensaje'] is String) {
      final guia = d['como_resolver'];
      final campos = d['campos'];
      final extra = campos is List && campos.isNotEmpty
          ? ' (${campos.whereType<Map>().map((c) => '${c['campo']} ${c['problema']}').join('; ')})'
          : '';
      return '${d['mensaje']}$extra${guia is String ? ' $guia' : ''}';
    }
    if (d is String && d.isNotEmpty) return d;
    return message;
  }

  @override
  String toString() => 'ApiException($statusCode): $message';
}

/// Tiempo de espera por pedido, en segundos: `--dart-define=API_TIMEOUT_S=40` al
/// compilar (`make apk API_TIMEOUT_S=40`). El backend en Fly.io se apaga solo y el
/// primer pedido después de un rato espera el arranque en frío.
const apiTimeoutS = int.fromEnvironment('API_TIMEOUT_S', defaultValue: 20);

/// Cliente HTTP del backend (`/v1`). El cliente habla SOLO con el backend.
///
/// Si el servidor no contesta (timeout o sin conexión), los pedidos que se pueden
/// repetir sin efectos (todos los GET y `/auth/refresh`) se reintentan con backoff
/// exponencial acotado. Un POST común (cargar un precio, crear un local) NUNCA se
/// reintenta solo: si el servidor lo procesó pero la respuesta se perdió, se duplicaría.
class ApiClient {
  ApiClient({
    required this.baseUrl,
    http.Client? httpClient,
    this.onCuentaBaja,
    this.idDispositivo,
    this.timeout = const Duration(seconds: apiTimeoutS),
    this.reintentos = 2,
    this.esperaBase = const Duration(seconds: 1),
    this.avisarTras = const Duration(seconds: 4),
  }) : _http = httpClient ?? http.Client();

  /// Cuánto se espera la respuesta de CADA intento.
  final Duration timeout;

  /// Cuántas veces más se intenta un pedido repetible que no obtuvo respuesta.
  final int reintentos;

  /// Espera antes del primer reintento; se duplica en cada uno (1 s, 2 s, ...).
  final Duration esperaBase;

  /// Si un pedido lleva más que esto sin respuesta, `despertando` pasa a `true`.
  final Duration avisarTras;

  /// `true` mientras algún pedido tarda más de lo normal: la app muestra
  /// «Despertando servidor…» (el backend arranca en frío).
  final ValueNotifier<bool> despertando = ValueNotifier(false);
  int _lentos = 0;

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
    bool silencioso = false,
  }) async => await _send(
    'POST',
    path,
    body: body,
    token: token,
    silencioso: silencioso,
  ) as Map<String, dynamic>;

  Future<Object?> _send(
    String method,
    String path, {
    Map<String, dynamic>? body,
    String? token,
    bool silencioso = false,
  }) async {
    // El primer pedido tras un rato puede tardar (arranque en frío): se avisa. Los pedidos
    // `silencioso` (eventos de estadística) nunca muestran el aviso.
    var marcado = false;
    final aviso = Timer(avisarTras, () {
      if (silencioso) return;
      marcado = true;
      despertando.value = ++_lentos > 0;
    });
    try {
      final repetible = method == 'GET' || path == '/auth/refresh';
      for (var intento = 0; ; intento++) {
        try {
          return await _enviar(method, path, body: body, token: token);
        } on ApiException catch (e) {
          final sinRespuesta = e.statusCode == null;
          if (!sinRespuesta || !repetible || intento >= reintentos) rethrow;
          await Future<void>.delayed(esperaBase * (1 << intento));
        }
      }
    } finally {
      aviso.cancel();
      if (marcado) despertando.value = --_lentos > 0;
    }
  }

  /// Un intento. Falla con `statusCode == null` si no hubo respuesta.
  Future<Object?> _enviar(
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
        await _http.send(request).timeout(timeout),
      );
    } on TimeoutException {
      throw ApiException(
        'El servidor tardó demasiado en responder (${timeout.inSeconds} s)',
        esTimeout: true,
      );
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
