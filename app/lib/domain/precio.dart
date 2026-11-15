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

/// Muestra un precio canónico ("1234.50") como se lee acá: `$ 1.234,50`.
String formatearPrecio(String canonico) {
  final partes = canonico.split('.');
  final entero = partes.first.replaceAllMapped(
    RegExp(r'\B(?=(\d{3})+(?!\d))'),
    (_) => '.',
  );
  final decimales = partes.length > 1 ? partes[1].padRight(2, '0') : '00';
  return '\$ $entero,$decimales';
}

/// Fecha de un precio para mostrar: `15/11/2026 (hace 3 días)`. La frescura
/// importa (la inflación envejece los precios), así que va siempre visible.
String formatearFecha(DateTime fecha, {required DateTime ahora}) {
  final f = fecha.toLocal();
  String dos(int n) => n.toString().padLeft(2, '0');
  final dia = '${dos(f.day)}/${dos(f.month)}/${f.year}';
  final dias = DateTime(
    ahora.year,
    ahora.month,
    ahora.day,
  ).difference(DateTime(f.year, f.month, f.day)).inDays;
  final hace = switch (dias) {
    <= 0 => 'hoy',
    1 => 'ayer',
    _ => 'hace $dias días',
  };
  return '$dia ($hace)';
}
