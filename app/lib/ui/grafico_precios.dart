import 'package:material_ui/material_ui.dart';

import '../data/price_repository.dart';
import '../domain/historial.dart';
import '../domain/precio.dart';

/// Una marca vertical con un texto sobre una fecha (los «hitos» del corte 23). Por ahora
/// el gráfico las acepta pero nadie las pasa.
class MarcaGrafico {
  const MarcaGrafico({required this.fecha, required this.texto});

  final DateTime fecha;
  final String texto;
}

/// Evolución del precio de un producto en un local: una línea, con el eje vertical
/// **lineal** (sin escalas que exageren un cambio). Con un solo precio dibuja un punto.
class GraficoPrecios extends StatefulWidget {
  const GraficoPrecios({
    super.key,
    required this.precios,
    this.marcas = const [],
  });

  final List<PrecioHistorial> precios;
  final List<MarcaGrafico> marcas;

  @override
  State<GraficoPrecios> createState() => _GraficoPreciosState();
}

class _GraficoPreciosState extends State<GraficoPrecios> {
  /// Índice (en orden cronológico) del punto tocado; nulo si no hay ninguno.
  int? _tocado;

  /// Hasta dónde (en píxeles) un toque «agarra» el punto más cercano.
  static const _alcance = 32.0;

  static const _izquierda = 64.0;
  static const _derecha = 16.0;
  static const _arriba = 12.0;
  static const _abajo = 24.0;
  static const _anchoGlobo = 132.0;

  String _dia(DateTime f) {
    final l = f.toLocal();
    String dos(int n) => n.toString().padLeft(2, '0');
    return '${dos(l.day)}/${dos(l.month)}';
  }

  @override
  Widget build(BuildContext context) {
    final precios = widget.precios;
    final marcas = widget.marcas;
    if (precios.isEmpty) return const SizedBox.shrink();
    final cronologicos = [...precios]
      ..sort((a, b) => a.fecha.compareTo(b.fecha));
    final valores = [for (final p in cronologicos) double.parse(p.precio)];
    final rango = rangoEje(valores);
    final minimo = valores.reduce((a, b) => a < b ? a : b);
    final maximo = valores.reduce((a, b) => a > b ? a : b);
    final desde = cronologicos.first.fecha;
    final hasta = cronologicos.last.fecha;
    final texto = Theme.of(context).textTheme.bodySmall;
    final color = Theme.of(context).colorScheme.primary;

    return Semantics(
      label:
          'Precio en el tiempo: de ${formatearPrecio(cronologicos.first.precio)} '
          'a ${formatearPrecio(cronologicos.last.precio)}',
      child: LayoutBuilder(
        builder: (context, c) {
          final alto = c.maxHeight - _arriba - _abajo;
          final ancho = c.maxWidth - _izquierda - _derecha;
          double y(double v) =>
              _arriba + (rango.max - v) / (rango.max - rango.min) * alto;
          double x(DateTime f) {
            final total = hasta.difference(desde).inMilliseconds;
            final t = total == 0
                ? 0.5
                : f.difference(desde).inMilliseconds / total;
            return _izquierda + t * ancho;
          }

          final puntos = [
            for (var i = 0; i < cronologicos.length; i++)
              Offset(x(cronologicos[i].fecha), y(valores[i])),
          ];
          Widget rotulo(double v) => Positioned(
            left: 0,
            width: _izquierda - 6,
            top: y(v) - 8,
            child: Text(
              formatearPrecioCorto(
                valores.firstWhere((e) => e == v).toStringAsFixed(2),
              ),
              textAlign: TextAlign.right,
              style: texto,
            ),
          );

          int? masCercano(Offset toque) {
            int? mejor;
            var distancia = _alcance;
            for (var i = 0; i < puntos.length; i++) {
              final d = (puntos[i] - toque).distance;
              if (d <= distancia) {
                distancia = d;
                mejor = i;
              }
            }
            return mejor;
          }

          void tocar(Offset toque) {
            final i = masCercano(toque);
            if (i != _tocado) setState(() => _tocado = i);
          }

          // Un índice viejo (la lista cambió de local) no debe salirse del rango.
          final tocado = _tocado != null && _tocado! < puntos.length
              ? _tocado
              : null;

          return GestureDetector(
            behavior: HitTestBehavior.opaque,
            onTapDown: (d) => tocar(d.localPosition),
            onHorizontalDragUpdate: (d) => tocar(d.localPosition),
            child: Stack(
              children: [
                Positioned.fill(
                  child: CustomPaint(
                    painter: _PintorLinea(
                      puntos: puntos,
                      color: color,
                      ejes: Theme.of(context).dividerColor,
                      izquierda: _izquierda,
                      derecha: c.maxWidth - _derecha,
                      abajo: _arriba + alto,
                      tocado: tocado == null ? null : puntos[tocado],
                      marcas: [
                        for (final m in marcas)
                          if (!m.fecha.isBefore(desde) &&
                              !m.fecha.isAfter(hasta))
                            x(m.fecha),
                      ],
                    ),
                  ),
                ),
                rotulo(maximo),
                if (minimo != maximo) rotulo(minimo),
                Positioned(
                  left: _izquierda - 16,
                  bottom: 0,
                  child: Text(_dia(desde), style: texto),
                ),
                if (hasta != desde)
                  Positioned(
                    right: _derecha - 16,
                    bottom: 0,
                    child: Text(_dia(hasta), style: texto),
                  ),
                if (tocado != null)
                  Positioned(
                    left: (puntos[tocado].dx - _anchoGlobo / 2).clamp(
                      0.0,
                      c.maxWidth - _anchoGlobo,
                    ),
                    top: (puntos[tocado].dy - 40).clamp(0.0, c.maxHeight),
                    width: _anchoGlobo,
                    child: _Globo(
                      key: const ValueKey('punto-tocado'),
                      texto:
                          '${formatearPrecio(cronologicos[tocado].precio)} · '
                          '${_dia(cronologicos[tocado].fecha)}',
                    ),
                  ),
              ],
            ),
          );
        },
      ),
    );
  }
}

class _PintorLinea extends CustomPainter {
  const _PintorLinea({
    required this.puntos,
    required this.color,
    required this.ejes,
    required this.izquierda,
    required this.derecha,
    required this.abajo,
    required this.marcas,
    required this.tocado,
  });

  final List<Offset> puntos;
  final Color color;
  final Color ejes;
  final double izquierda;
  final double derecha;
  final double abajo;
  final List<double> marcas;
  final Offset? tocado;

  @override
  void paint(Canvas canvas, Size size) {
    final eje = Paint()
      ..color = ejes
      ..strokeWidth = 1;
    canvas.drawLine(Offset(izquierda, abajo), Offset(derecha, abajo), eje);
    canvas.drawLine(Offset(izquierda, 0), Offset(izquierda, abajo), eje);
    final marca = Paint()
      ..color = color.withValues(alpha: 0.4)
      ..strokeWidth = 1.5;
    for (final mx in marcas) {
      canvas.drawLine(Offset(mx, 0), Offset(mx, abajo), marca);
    }
    final linea = Paint()
      ..color = color
      ..strokeWidth = 2.5
      ..style = PaintingStyle.stroke
      ..strokeJoin = StrokeJoin.round;
    if (puntos.length > 1) {
      final path = Path()..moveTo(puntos.first.dx, puntos.first.dy);
      for (final p in puntos.skip(1)) {
        path.lineTo(p.dx, p.dy);
      }
      canvas.drawPath(path, linea);
    }
    final relleno = Paint()..color = color;
    for (final p in puntos) {
      canvas.drawCircle(p, 4, relleno);
    }
    if (tocado != null) {
      canvas.drawCircle(
        tocado!,
        9,
        Paint()..color = color.withValues(alpha: 0.35),
      );
      canvas.drawCircle(tocado!, 5, Paint()..color = color);
    }
    // El último precio, resaltado.
    canvas.drawCircle(
      puntos.last,
      7,
      Paint()..color = color.withValues(alpha: 0.25),
    );
  }

  @override
  bool shouldRepaint(_PintorLinea anterior) =>
      anterior.puntos != puntos ||
      anterior.color != color ||
      anterior.marcas != marcas ||
      anterior.tocado != tocado;
}

/// El cartelito con el precio y el día del punto tocado.
class _Globo extends StatelessWidget {
  const _Globo({super.key, required this.texto});

  final String texto;

  @override
  Widget build(BuildContext context) {
    final colores = Theme.of(context).colorScheme;
    return Container(
      alignment: Alignment.center,
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
      decoration: BoxDecoration(
        color: colores.inverseSurface,
        borderRadius: BorderRadius.circular(14),
      ),
      child: Text(
        texto,
        maxLines: 1,
        style: TextStyle(
          color: colores.onInverseSurface,
          fontWeight: FontWeight.bold,
          fontSize: 12,
        ),
      ),
    );
  }
}
