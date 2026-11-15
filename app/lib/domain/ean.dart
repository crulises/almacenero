/// Un código de barras (EAN/UPC) son entre 8 y 14 dígitos.
final _eanRegExp = RegExp(r'^[0-9]{8,14}$');

/// Quita espacios alrededor y devuelve el EAN si tiene forma válida; si no, null.
String? normalizarEan(String? texto) {
  final ean = texto?.trim();
  if (ean == null || !_eanRegExp.hasMatch(ean)) return null;
  return ean;
}
