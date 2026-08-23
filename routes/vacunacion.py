from flask import Blueprint, request, jsonify
from extensions import db
from models import Vacunacion
from auth import validar_token, requiere_rol

vacunacion_bp = Blueprint("vacunacion", __name__)


def _serializar(registro):
    return {
        "id": registro.id,
        "paciente_id": registro.paciente_id,
        "es_estudiante": registro.es_estudiante,
        "esquema_completo": registro.esquema_completo,
        "vacunas_pendientes": registro.vacunas_pendientes,
        "fecha_actualizacion": registro.fecha_actualizacion.isoformat() if registro.fecha_actualizacion else None,
    }


@vacunacion_bp.route("/api/v1/salud/vacunacion", methods=["POST"])
@validar_token
@requiere_rol("admin", "medico")
def registrar_vacunacion():
    """
    Registrar un nuevo registro de vacunación
    ---
    tags:
      - Vacunación
    security:
      - BearerAuth: []
    parameters:
      - in: body
        name: body
        required: true
        schema:
          type: object
          required:
            - paciente_id
          properties:
            paciente_id:
              type: integer
            es_estudiante:
              type: boolean
            esquema_completo:
              type: boolean
            vacunas_pendientes:
              type: string
    responses:
      201:
        description: Registro de vacunación creado
    """
    data = request.get_json()
    registro = Vacunacion(
        paciente_id=data["paciente_id"],
        es_estudiante=data.get("es_estudiante", False),
        esquema_completo=data.get("esquema_completo", False),
        vacunas_pendientes=data.get("vacunas_pendientes"),
    )
    db.session.add(registro)
    db.session.commit()
    return jsonify(success=True, data={"id": registro.id}, message="Registro de vacunación creado"), 201


@vacunacion_bp.route("/api/v1/salud/vacunacion", methods=["GET"])
@validar_token
@requiere_rol("admin", "medico")
def listar_vacunacion():
    """
    Listar todos los registros de vacunación
    ---
    tags:
      - Vacunación
    security:
      - BearerAuth: []
    responses:
      200:
        description: Lista de registros de vacunación
    """
    registros = Vacunacion.query.all()
    return jsonify(success=True, data=[_serializar(r) for r in registros]), 200


@vacunacion_bp.route("/api/v1/salud/vacunacion/<int:paciente_id>", methods=["GET"])
@validar_token
def obtener_vacunacion(paciente_id):
    """
    Obtener el registro de vacunación de un paciente
    ---
    tags:
      - Vacunación
    security:
      - BearerAuth: []
    parameters:
      - in: path
        name: paciente_id
        type: integer
        required: true
    responses:
      200:
        description: Registro de vacunación encontrado
      404:
        description: Sin registro de vacunación
    """
    registro = Vacunacion.query.filter_by(paciente_id=paciente_id).first()
    if not registro:
        return jsonify(success=False, error="no_encontrado", message="Sin registro de vacunación"), 404

    return jsonify(success=True, data=_serializar(registro)), 200


@vacunacion_bp.route("/api/v1/salud/vacunacion/<int:paciente_id>", methods=["PUT"])
@validar_token
@requiere_rol("admin", "medico")
def actualizar_vacunacion(paciente_id):
    """
    Actualizar el registro de vacunación de un paciente
    ---
    tags:
      - Vacunación
    security:
      - BearerAuth: []
    parameters:
      - in: path
        name: paciente_id
        type: integer
        required: true
      - in: body
        name: body
        schema:
          type: object
          properties:
            es_estudiante:
              type: boolean
            esquema_completo:
              type: boolean
            vacunas_pendientes:
              type: string
    responses:
      200:
        description: Registro actualizado
      404:
        description: Sin registro de vacunación
    """
    registro = Vacunacion.query.filter_by(paciente_id=paciente_id).first()
    if not registro:
        return jsonify(success=False, error="no_encontrado", message="Sin registro de vacunación"), 404

    data = request.get_json()
    if "es_estudiante" in data:
        registro.es_estudiante = data["es_estudiante"]
    if "esquema_completo" in data:
        registro.esquema_completo = data["esquema_completo"]
    if "vacunas_pendientes" in data:
        registro.vacunas_pendientes = data["vacunas_pendientes"]

    db.session.commit()
    return jsonify(success=True, data={"id": registro.id}, message="Actualizado"), 200


@vacunacion_bp.route("/api/v1/salud/vacunacion/<int:paciente_id>", methods=["DELETE"])
@validar_token
@requiere_rol("admin")
def eliminar_vacunacion(paciente_id):
    """
    Eliminar el registro de vacunación de un paciente
    ---
    tags:
      - Vacunación
    security:
      - BearerAuth: []
    parameters:
      - in: path
        name: paciente_id
        type: integer
        required: true
    responses:
      200:
        description: Registro eliminado
      404:
        description: Sin registro de vacunación
    """
    registro = Vacunacion.query.filter_by(paciente_id=paciente_id).first()
    if not registro:
        return jsonify(success=False, error="no_encontrado", message="Sin registro de vacunación"), 404

    db.session.delete(registro)
    db.session.commit()
    return jsonify(success=True, data={"id": paciente_id}, message="Registro de vacunación eliminado"), 200
