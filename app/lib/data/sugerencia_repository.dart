import 'authed_api.dart';

/// Lo que devuelve el backend al recibir una sugerencia.
class SugerenciaEnviada {
  const SugerenciaEnviada({
    required this.id,
    required this.tipo,
    required this.estado,
  });

  final String id;

  /// `alta` (producto nuevo) o `correccion`.
  final String tipo;
  final String estado;

  factory SugerenciaEnviada.fromJson(Map<String, dynamic> json) =>
      SugerenciaEnviada(
        id: json['id'] as String,
        tipo: json['tipo'] as String,
        estado: json['estado'] as String,
      );
}

/// Un estándar de carga (docs/08-estandares-de-carga.md).
class Estandar {
  const Estandar({
    required this.id,
    required this.titulo,
    required this.regla,
    required this.mal,
    required this.bien,
  });

  final String id;
  final String titulo;
  final String regla;
  final String mal;
  final String bien;

  factory Estandar.fromJson(Map<String, dynamic> json) => Estandar(
    id: json['id'] as String,
    titulo: json['titulo'] as String,
    regla: json['regla'] as String,
    mal: json['mal'] as String,
    bien: json['bien'] as String,
  );
}

class SugerenciaRepository {
  SugerenciaRepository({required this._api});

  final AuthedApi _api;

  /// Propone cambios para un EAN. `cambios` lleva solo los campos que cambian
  /// (`nombre`, `marca`, `tamano_valor`, `tamano_unidad`, `pack_cantidad`,
  /// `presentacion`); un valor `null` borra el campo. No toca el catálogo: queda en
  /// la cola hasta que un admin la aprueba.
  Future<SugerenciaEnviada> enviar({
    required String ean,
    required Map<String, Object?> cambios,
    String? motivo,
  }) async => SugerenciaEnviada.fromJson(
    await _api.post('/catalogo/sugerencias', {
      'ean': ean,
      ...cambios,
      if (motivo != null && motivo.trim().isNotEmpty) 'motivo': motivo.trim(),
    }),
  );

  Future<List<Estandar>> estandares() async => [
    for (final e in await _api.getList('/ayuda/estandares'))
      Estandar.fromJson(e as Map<String, dynamic>),
  ];
}
