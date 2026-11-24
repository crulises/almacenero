import 'dart:async';
import 'dart:collection';

import 'package:flutter/foundation.dart' show debugPrint;

import 'authed_api.dart';

/// Cola en memoria de eventos de producto (docs/04 §11.2): `producto.escaneado`,
/// `app.abierta`. Se juntan y se mandan por lotes de hasta 50.
///
/// Regla de oro: **nunca estorba**. `registrar` es síncrono y no puede fallar; `vaciar` no
/// lanza jamás. Si no hay red, el servidor no contesta o el pedido falla por lo que sea, el
/// lote **se descarta** (los eventos son estadística, no datos del usuario) y no se muestra
/// ningún error. Tampoco se reintenta: no se acumula nada que después pese.
class ColaEventos {
  ColaEventos({
    required this.enviar,
    this.maxEnCola = 200,
    this.esperaMaxima = const Duration(seconds: 10),
    this.envioEn = const Duration(seconds: 5),
  });

  /// Cuánto se junta antes de mandar solo (se cuenta desde el primer evento nuevo): así
  /// llega todo junto en un pedido y el celular no manda uno por escaneo. `null` = no manda
  /// solo (los tests llaman a [vaciar]).
  final Duration? envioEn;

  /// Manda un lote al backend. Puede fallar como quiera: acá se ignora.
  final Future<void> Function(List<Map<String, Object?>> lote) enviar;

  /// Tope en memoria: pasado esto se descartan los más viejos.
  final int maxEnCola;

  /// Cuánto se espera la respuesta de un lote antes de darlo por perdido.
  final Duration esperaMaxima;

  static const _loteMax = 50;

  final _cola = Queue<Map<String, Object?>>();
  Future<void>? _vaciando;
  Timer? _timer;
  int _descartados = 0;

  int get pendientes => _cola.length;

  /// Anota un evento. El instante lo pone el servidor; el reloj del celular viaja aparte
  /// (`ocurrio_en_cliente`) y el backend nunca lo usa para agrupar.
  void registrar(String tipo, [Map<String, Object?> datos = const {}]) {
    try {
      _cola.add({
        'tipo': tipo,
        'datos': datos,
        'ocurrio_en_cliente': DateTime.now().toUtc().toIso8601String(),
      });
      while (_cola.length > maxEnCola) {
        _cola.removeFirst();
        _descartados++;
      }
      final espera = envioEn;
      if (espera != null && _timer == null) {
        _timer = Timer(espera, () {
          _timer = null;
          vaciar();
        });
      }
    } catch (_) {
      // Nada de esto puede romper la app.
    }
  }

  /// Manda lo pendiente, de a 50. No lanza nunca; si ya hay un envío en curso, espera ese.
  Future<void> vaciar() =>
      _vaciando ??= _vaciar().whenComplete(() => _vaciando = null);

  Future<void> _vaciar() async {
    while (_cola.isNotEmpty) {
      final lote = <Map<String, Object?>>[];
      while (_cola.isNotEmpty && lote.length < _loteMax) {
        lote.add(_cola.removeFirst());
      }
      try {
        await Future<void>.sync(() => enviar(lote)).timeout(esperaMaxima);
      } catch (e) {
        // Sin red, timeout, 4xx, 5xx, sesión vencida…: se descarta y se sigue. En la
        // compilación de prueba queda en el log (`adb logcat | grep eventos`).
        _descartados += lote.length;
        debugPrint(
          'eventos: se descartaron ${lote.length} (total $_descartados): $e',
        );
      }
    }
  }
}

/// Manda los eventos al backend (`POST /v1/eventos`).
class EventosRepository {
  EventosRepository({required this._api});

  final AuthedApi _api;

  Future<void> enviar(List<Map<String, Object?>> lote) async {
    // `silencioso`: un pedido de estadística no prende «Despertando servidor…».
    await _api.post('/eventos', {'eventos': lote}, silencioso: true);
  }
}
