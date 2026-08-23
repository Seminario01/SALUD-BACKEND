from flask import Blueprint, request, jsonify, g
from extensions import db
from models import Paciente
from auth import validar_token, requiere_rol

pacientes_bp = Blueprint("pacientes", __name__)

@pacientes_bp.route("/api/v1/salud/pacientes", methods=["POST"])
@validar_token
@requiere_rol("admin", "recepcion")
def crear_paciente():
    data = request.get_json()
    paciente = Paciente(
        cui=data.get("cui"),
        nombre_completo=data["nombre_completo"],
        fecha_nacimiento=data.get("fecha_nacimiento"),
        genero=data.get("genero"),
        telefono=data.get("telefono"),
        tipo_seguro=data.get("tipo_seguro"),
        cuidador=data.get("cuidador"),
    )
    db.session.add(paciente)
    db.session.commit()
    return jsonify(success=True, data={"id": paciente.id}, message="Paciente registrado"), 201


@pacientes_bp.route("/api/v1/salud/pacientes/<int:id>", methods=["GET"])
@validar_token
def obtener_paciente(id):
    if g.usuario.rol == "paciente" and g.usuario.id != id:
        return jsonify(success=False, error="permiso_denegado", message="Solo puede ver su propio registro"), 403

    paciente = Paciente.query.get(id)
    if not paciente:
        return jsonify(success=False, error="no_encontrado", message="Paciente no existe"), 404

    return jsonify(success=True, data={
        "id": paciente.id,
        "cui": paciente.cui,
        "nombre_completo": paciente.nombre_completo,
        "fecha_nacimiento": str(paciente.fecha_nacimiento),
        "tipo_seguro": paciente.tipo_seguro,
    }), 200


@pacientes_bp.route("/api/v1/salud/pacientes/<int:id>", methods=["PUT"])
@validar_token
@requiere_rol("admin", "recepcion", "paciente")
def actualizar_paciente(id):
    paciente = Paciente.query.get(id)
    if not paciente:
        return jsonify(success=False, error="no_encontrado", message="Paciente no existe"), 404

    data = request.get_json()
    for campo in ["telefono", "tipo_seguro", "cuidador"]:
        if campo in data:
            setattr(paciente, campo, data[campo])

    db.session.commit()
    return jsonify(success=True, data={"id": paciente.id}, message="Actualizado"), 200