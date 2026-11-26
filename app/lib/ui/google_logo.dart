import 'package:material_ui/material_ui.dart';

/// La «G» de Google en sus colores, para los botones que entran con Google. El material
/// icons no trae logos de marcas, así que es un asset (`assets/google_g.svg` es el original;
/// el PNG sale de ahí con `rsvg-convert -w 96 -h 96`).
class GoogleLogo extends StatelessWidget {
  const GoogleLogo({super.key, this.tamano = 20});

  final double tamano;

  @override
  Widget build(BuildContext context) => ExcludeSemantics(
    child: Image.asset(
      'assets/google_g.png',
      width: tamano,
      height: tamano,
      filterQuality: FilterQuality.medium,
    ),
  );
}
