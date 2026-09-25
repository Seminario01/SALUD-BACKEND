from flask import Blueprint, request, jsonify, g
from extensions import db
from models import ExpedienteClinico, Paciente
from auth import validar_token, requiere_rol, tiene_rol, ROL_MEDICO, ROL_ADMIN

expedientes_bp = Blueprint("expedientes", __name__)

@expedientes_bp.route("/api/v1/salud/expedientes/<int:paciente_id>", methods=["GET"])
@validar_token
def obtener_expediente(paciente_id):
    paciente = Paciente.query.get(paciente_id)

    # OWASP API1 (BOLA): datos clínicos. Solo médico/admin de Salud, o el propio
    # ciudadano dueño del registro. Recepción NO ve expedientes.
    es_dueno = paciente is not None and paciente.usuario_sub == g.usuario["sub"]
    if not (tiene_rol(ROL_MEDICO, ROL_ADMIN) or es_dueno):
        return jsonify(success=False, error="permiso_denegado", message="Solo puede ver su propio expediente"), 403

    if not paciente:
        return jsonify(success=False, error="no_encontrado", message="Paciente no existe"), 404

    registros = ExpedienteClinico.query.filter_by(paciente_id=paciente_id) \
        .order_by(ExpedienteClinico.fecha_atencion.desc()).all()

    return jsonify(success=True, data=[{
        "id": r.id,
        "cita_id": r.cita_id,
        "medico_sub": r.medico_sub,
        "diagnostico": r.diagnostico,
        "tratamiento": r.tratamiento,
        "notas": r.notas,
        "fecha_atencion": str(r.fecha_atencion),
    } for r in registros]), 200


@expedientes_bp.route("/api/v1/salud/expedientes/<int:paciente_id>/atenciones", methods=["POST"])
@validar_token
@requiere_rol(ROL_MEDICO)
def registrar_atencion(paciente_id):
    paciente = Paciente.query.get(paciente_id)
    if not paciente:
        return jsonify(success=False, error="no_encontrado", message="Paciente no existe"), 404

    data = request.get_json()
    registro = ExpedienteClinico(
        paciente_id=paciente_id,
        cita_id=data.get("cita_id"),
        medico_sub=g.usuario["sub"],
        diagnostico=data.get("diagnostico"),
        tratamiento=data.get("tratamiento"),
        notas=data.get("notas"),
    )
    db.session.add(registro)
    db.session.commit()

    return jsonify(success=True, data={"id": registro.id}, message="Atención registrada"), 201