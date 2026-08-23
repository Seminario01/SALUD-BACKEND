from flask import Blueprint, request, jsonify, g
from extensions import db
from models import CitaMedica
from auth import validar_token, requiere_rol

citas_bp = Blueprint("citas", __name__)

@citas_bp.route("/api/v1/salud/citas", methods=["POST"])
@validar_token
def crear_cita():
    """
    Agendar una nueva cita médica
    ---
    tags:
      - Citas
    security:
      - BearerAuth: []
    parameters:
      - name: body
        in: body
        required: true
        schema:
          type: object
          properties:
            paciente_id:
              type: integer
            medico_id:
              type: integer
            fecha_hora:
              type: string
            motivo:
              type: string
    responses:
      201:
        description: Cita creada
    """
    data = request.get_json()
    cita = CitaMedica(
        paciente_id=data["paciente_id"],
        medico_id=data.get("medico_id"),
        fecha_hora=data["fecha_hora"],
        motivo=data.get("motivo"),
    )
    db.session.add(cita)
    db.session.commit()
    return jsonify(success=True, data={"id": cita.id}, message="Cita creada"), 201


@citas_bp.route("/api/v1/salud/citas/<int:id>", methods=["PUT"])
@validar_token
def reprogramar_cita(id):
    """
    Reprogramar o cambiar estado de una cita
    ---
    tags:
      - Citas
    security:
      - BearerAuth: []
    parameters:
      - name: id
        in: path
        type: integer
        required: true
      - name: body
        in: body
        required: true
        schema:
          type: object
          properties:
            fecha_hora:
              type: string
            estado:
              type: string
    responses:
      200:
        description: Cita actualizada
      404:
        description: Cita no existe
    """
    cita = CitaMedica.query.get(id)
    if not cita:
        return jsonify(success=False, error="no_encontrado", message="Cita no existe"), 404

    data = request.get_json()
    if "fecha_hora" in data:
        cita.fecha_hora = data["fecha_hora"]
    if "estado" in data:
        cita.estado = data["estado"]

    db.session.commit()
    return jsonify(success=True, data={"id": cita.id}, message="Cita actualizada"), 200


@citas_bp.route("/api/v1/salud/citas/<int:id>", methods=["DELETE"])
@validar_token
def cancelar_cita(id):
    """
    Cancelar una cita médica
    ---
    tags:
      - Citas
    security:
      - BearerAuth: []
    parameters:
      - name: id
        in: path
        type: integer
        required: true
    responses:
      200:
        description: Cita cancelada
      404:
        description: Cita no existe
    """
    cita = CitaMedica.query.get(id)
    if not cita:
        return jsonify(success=False, error="no_encontrado", message="Cita no existe"), 404

    cita.estado = "cancelada"
    db.session.commit()
    return jsonify(success=True, data=None, message="Cita cancelada"), 200


@citas_bp.route("/api/v1/salud/citas", methods=["GET"])
@validar_token
def listar_citas():
    """
    Listar citas médicas
    ---
    tags:
      - Citas
    security:
      - BearerAuth: []
    parameters:
      - name: paciente_id
        in: query
        type: integer
        required: false
        description: Filtrar por paciente
    responses:
      200:
        description: Lista de citas
    """
    paciente_id = request.args.get("paciente_id")
    query = CitaMedica.query
    if paciente_id:
        query = query.filter_by(paciente_id=paciente_id)

    citas = query.all()
    return jsonify(success=True, data=[{
        "id": c.id, "fecha_hora": str(c.fecha_hora), "estado": c.estado
    } for c in citas]), 200