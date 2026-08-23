from flask import Blueprint, request, jsonify, g
from extensions import db
from models import ExpedienteClinico, Paciente
from auth import validar_token, requiere_rol

expedientes_bp = Blueprint("expedientes", __name__)

@expedientes_bp.route("/api/v1/salud/expedientes/<int:paciente_id>", methods=["GET"])
@validar_token
def obtener_expediente(paciente_id):
    if g.usuario.rol == "paciente" and g.usuario.id != paciente_id:
        return jsonify(success=False, error="permiso_denegado", message="Solo puede ver su propio expediente"), 403

    if g.usuario.rol == "recepcion":
        return jsonify(success=False, error="permiso_denegado", message="No tiene permiso para ver expedientes"), 403

    paciente = Paciente.query.get(paciente_id)
    if not paciente:
        return jsonify(success=False, error="no_encontrado", message="Paciente no existe"), 404

    registros = ExpedienteClinico.query.filter_by(paciente_id=paciente_id) \
        .order_by(ExpedienteClinico.fecha_atencion.desc()).all()

    return jsonify(success=True, data=[{
        "id": r.id,
        "cita_id": r.cita_id,
        "diagnostico": r.diagnostico,
        "tratamiento": r.tratamiento,
        "notas": r.notas,
        "fecha_atencion": str(r.fecha_atencion),
    } for r in registros]), 200


@expedientes_bp.route("/api/v1/salud/expedientes/<int:paciente_id>/atenciones", methods=["POST"])
@validar_token
@requiere_rol("medico")
def registrar_atencion(paciente_id):
    paciente = Paciente.query.get(paciente_id)
    if not paciente:
        return jsonify(success=False, error="no_encontrado", message="Paciente no existe"), 404

    data = request.get_json()
    registro = ExpedienteClinico(
        paciente_id=paciente_id,
        cita_id=data.get("cita_id"),
        medico_id=g.usuario.id,
        diagnostico=data.get("diagnostico"),
        tratamiento=data.get("tratamiento"),
        notas=data.get("notas"),
    )
    db.session.add(registro)
    db.session.commit()

    return jsonify(success=True, data={"id": registro.id}, message="Atención registrada"), 201