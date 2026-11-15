/// Interpreta el precio tipeado por el usuario y lo devuelve en formato canónico
/// con dos decimales (`"1234.50"`), que es como se manda al backend (sin pasar por
/// `double`, para no perder exactitud). Devuelve null si no es un precio válido.
///
/// Acepta coma o punto como separador decimal (en Argentina se escribe `1234,5`), con
/// hasta 2 decimales. No acepta separador de miles: `1.234` se rechaza por ambiguo.
String? parsearPrecio(String? texto) {
  final t = texto?.trim().replaceAll(r'$', '').trim();
  if (t == null) return null;
  final m = RegExp(r'^(\d{1,10})(?:[.,](\d{1,2}))?$').firstMatch(t);
  if (m == null) return null;
  final entero = m.group(1)!;
  final decimales = (m.group(2) ?? '').padRight(2, '0');
  if (int.parse(entero) == 0 && int.parse(decimales) == 0) return null;
  return '$entero.$decimales';
}
