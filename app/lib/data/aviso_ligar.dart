import 'package:shared_preferences/shared_preferences.dart';

/// «Luego» de la tarjeta «Protegé tu cuenta»: la oculta unos días. Vive en el celular
/// (no en el servidor): es una comodidad de cada persona, no un dato de la cuenta.
class AvisoLigar {
  AvisoLigar(this._prefs, {DateTime Function()? now})
    : _now = now ?? DateTime.now;

  static const _clave = 'aviso_ligar_oculto_hasta';
  static const dias = 7;

  final SharedPreferences _prefs;
  final DateTime Function() _now;

  bool estaOculto() {
    final hasta = DateTime.tryParse(_prefs.getString(_clave) ?? '');
    return hasta != null && _now().isBefore(hasta);
  }

  Future<void> ocultarSieteDias() => _prefs.setString(
    _clave,
    _now().add(const Duration(days: dias)).toIso8601String(),
  );
}
