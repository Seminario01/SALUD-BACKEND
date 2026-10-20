from flask import Blueprint, request, jsonify, g
import cie10
from extensions import db
from models import ExpedienteClinico, Paciente, CitaMedica
from auth import validar_token, requiere_permiso, puede
from validacion import DatoInvalido, entero, texto

expedientes_bp = Blueprint("expedientes", __name__)

@expedientes_bp.route("/api/v1/salud/expedientes/<int:paciente_id>", methods=["GET"])
@validar_token
def obtener_expediente(paciente_id):
    paciente = Paciente.query.get(paciente_id)

    # OWASP API1 (BOLA): datos clínicos. Solo los puestos con "expediente.ver"
    # (médico, enfermería, jefatura, administración en solo lectura) o el propio
    # ciudadano dueño del registro. Recepción, Caja y Farmacia NO ven expedientes.
    es_dueno = paciente is not None and paciente.usuario_sub == g.usuario["sub"]
    if not (puede("expediente.ver") or es_dueno):
        return jsonify(success=False, error="permiso_denegado", message="Solo puede ver su propio expediente"), 403

    if not paciente:
        return jsonify(success=False, error="no_encontrado", message="Paciente no existe"), 404

    registros = ExpedienteClinico.query.filter_by(paciente_id=paciente_id) \
        .order_by(ExpedienteClinico.fecha_atencion.desc(), ExpedienteClinico.id.desc()).all()

    return jsonify(success=True, data=[{
        "id": r.id,
        "cita_id": r.cita_id,
        "medico_sub": r.medico_sub,
        "diagnostico": r.diagnostico,
        "codigo_cie10": r.codigo_cie10,
        "cie10": cie10.descripcion(r.codigo_cie10) if r.codigo_cie10 else None,
        "tratamiento": r.tratamiento,
        "notas": r.notas,
        "fecha_atencion": str(r.fecha_atencion),
    } for r in registros]), 200


@expedientes_bp.route("/api/v1/salud/expedientes/<int:paciente_id>/atenciones", methods=["POST"])
@validar_token
@requiere_permiso("expediente.registrar")
def registrar_atencion(paciente_id):
    paciente = Paciente.query.get(paciente_id)
    if not paciente:
        return jsonify(success=False, error="no_encontrado", message="Paciente no existe"), 404

    data = request.get_json(silent=True) or {}
    # Código CIE-10 opcional (del catálogo); si viene sin diagnóstico escrito, el diagnóstico es su nombre
    codigo = texto(data, "codigo_cie10", 8, etiqueta="El código CIE-10")
    if codigo is not None:
        codigo = cie10.normalizar_codigo(codigo)
        if not cie10.descripcion(codigo):
            raise DatoInvalido(f"El código CIE-10 {codigo} no está en el catálogo (búsquelo en /cie10?q=)")
    diagnostico = texto(data, "diagnostico", 4000, etiqueta="El diagnóstico") or (cie10.descripcion(codigo) if codigo else None)
    if not diagnostico:
        return jsonify(success=False, error="datos_invalidos", message="El diagnóstico es obligatorio"), 400

    # Si se asocia una cita, debe ser de ESTE paciente (evita mezclar expedientes).
    cita_id = entero(data, "cita_id", 1, 2_147_483_647, etiqueta="cita_id")
    if cita_id is not None:
        cita = CitaMedica.query.get(cita_id)
        if cita is None or cita.paciente_id != paciente_id:
            return jsonify(success=False, error="datos_invalidos",
                           message="La cita no existe o no pertenece a este paciente"), 400

    registro = ExpedienteClinico(
        paciente_id=paciente_id,
        cita_id=cita_id,
        medico_sub=g.usuario["sub"],
        diagnostico=diagnostico,
        codigo_cie10=codigo,
        tratamiento=texto(data, "tratamiento", 4000, etiqueta="El tratamiento"),
        notas=texto(data, "notas", 4000, etiqueta="Las notas"),
    )
    db.session.add(registro)
    # La cita atendida queda a nombre del médico que registró la atención (si no tenía médico)
    if cita_id is not None and not cita.medico_sub:
        cita.medico_sub = g.usuario["sub"]
        cita.medico_nombre = (g.usuario.get("nombre") or g.usuario.get("usuario") or "")[:150] or None
    db.session.commit()

    return jsonify(success=True, data={"id": registro.id}, message="Atención registrada"), 201


@expedientes_bp.route("/api/v1/salud/cie10", methods=["GET"])
@validar_token
@requiere_permiso("expediente.registrar", "expediente.ver", "reportes.ver")
def buscar_cie10():
    """
    Buscar diagnósticos en el catálogo CIE-10
    ---
    tags:
      - Expediente
    security:
      - BearerAuth: []
    description: >
      Por código ("J0", "I10") o por palabras en cualquier orden, sin tildes ("hiper arter",
      "gripe", "ivu"). Son los diagnósticos más frecuentes (no los más de 12 000 de la CIE-10 completa).
    parameters:
      - {name: q, in: query, type: string, required: true}
      - {name: limite, in: query, type: integer, default: 15, description: "1 a 50"}
    responses:
      200:
        description: "[{codigo, descripcion, capitulo}]"
      400:
        description: Falta q o el límite no sirve
    """
    q = (request.args.get("q") or "").strip()[:60]
    if not q:
        return jsonify(success=False, error="datos_invalidos", message="Escriba un código o parte del diagnóstico (q)"), 400
    limite = request.args.get("limite", "15")
    if not limite.isdigit() or not 1 <= int(limite) <= 50:
        return jsonify(success=False, error="datos_invalidos", message="limite debe ser un número de 1 a 50"), 400
    return jsonify(success=True, data=cie10.buscar(q, int(limite)), total_catalogo=len(cie10.CATALOGO)), 200
