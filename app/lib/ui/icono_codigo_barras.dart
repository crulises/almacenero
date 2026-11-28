import 'package:material_ui/material_ui.dart';

/// Un código de barras dibujado (barras verticales de distinto grosor): Material no trae
/// uno, y el de «lector de códigos» confundía más de lo que aclaraba. Toma el tamaño y el
/// color del `IconTheme`, así que sirve en cualquier `icon:` de un botón.
class IconoCodigoBarras extends StatelessWidget {
  const IconoCodigoBarras({super.key, this.size, this.color});

  final double? size;
  final Color? color;

  /// Grosores de las barras y de los huecos, intercalados, en unidades relativas.
  static const _barras = [
    2.0,
    1.0,
    1.0,
    1.0,
    3.0,
    1.0,
    1.0,
    2.0,
    2.0,
    1.0,
    3.0,
  ];

  @override
  Widget build(BuildContext context) {
    final tema = IconTheme.of(context);
    final lado = size ?? tema.size ?? 24;
    return Semantics(
      label: 'Código de barras',
      child: CustomPaint(
        size: Size.square(lado),
        painter: _PintorBarras(color ?? tema.color ?? Colors.black),
      ),
    );
  }
}

class _PintorBarras extends CustomPainter {
  const _PintorBarras(this.color);

  final Color color;

  @override
  void paint(Canvas canvas, Size size) {
    final pintura = Paint()..color = color;
    final total = IconoCodigoBarras._barras.fold<double>(0, (a, b) => a + b);
    final ancho = size.width * 0.84;
    final unidad = ancho / total;
    final alto = size.height * 0.64;
    var x = size.width * 0.08;
    final y = (size.height - alto) / 2;
    for (var i = 0; i < IconoCodigoBarras._barras.length; i++) {
      final w = IconoCodigoBarras._barras[i] * unidad;
      // Las posiciones pares son barras; las impares, huecos.
      if (i.isEven) canvas.drawRect(Rect.fromLTWH(x, y, w, alto), pintura);
      x += w;
    }
  }

  @override
  bool shouldRepaint(_PintorBarras anterior) => anterior.color != color;
}
