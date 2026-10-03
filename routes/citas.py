from datetime import datetime
from flask import Blueprint, request, jsonify, g
from extensions import db
from models import CitaMedica, Paciente
from auth import validar_token, puede

citas_bp = Blueprint("citas", __name__)


def _paciente_propio():
    """Registro de paciente vinculado al `sub` del usuario (o None)."""
    return Paciente.query.filter_by(usuario_sub=g.usuario["sub"]).first()


def _puede_gestionar(paciente_id):
    """OWASP API1 (BOLA): el personal de Salud gestiona citas de cualquier
    paciente; un ciudadano solo las de su propio registro."""
    if puede("citas.gestionar"):
        return True
    propio = _paciente_propio()
    return propio is not None and str(paciente_id) == str(propio.id)


def _fecha(valor):
    """Acepta '2026-10-01 10:00:00' o '2026-10-01T10:00'. None si es inválida."""
    try:
        return datetime.fromisoformat(str(valor))
    except ValueError:
        return None


def _sin_permiso():
    return jsonify(success=False, error="permiso_denegado", message="Solo puede gestionar sus propias citas"), 403

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
            medico_sub:
              type: string
              description: sub del médico en el Login Único
            fecha_hora:
              type: string
            motivo:
              type: string
    responses:
      201:
        description: Cita creada
      403:
        description: Un ciudadano intentó agendar para otro paciente
    """
    data = request.get_json() or {}
    if not data.get("paciente_id") or not data.get("fecha_hora"):
        return jsonify(success=False, error="datos_invalidos", message="paciente_id y fecha_hora son obligatorios"), 400
    if not _puede_gestionar(data["paciente_id"]):
        return _sin_permiso()
    fecha_hora = _fecha(data["fecha_hora"])
    if fecha_hora is None:
        return jsonify(success=False, error="datos_invalidos", message="fecha_hora inválida (formato AAAA-MM-DD HH:MM)"), 400

    cita = CitaMedica(
        paciente_id=data["paciente_id"],
        medico_sub=data.get("medico_sub"),
        fecha_hora=fecha_hora,
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
    if cita is None:
        if not puede("citas.gestionar"):
            return _sin_permiso()
        return jsonify(success=False, error="no_encontrado", message="Cita no existe"), 404
    if not _puede_gestionar(cita.paciente_id):
        return _sin_permiso()

    data = request.get_json() or {}
    if "fecha_hora" in data:
        fecha_hora = _fecha(data["fecha_hora"])
        if fecha_hora is None:
            return jsonify(success=False, error="datos_invalidos", message="fecha_hora inválida (formato AAAA-MM-DD HH:MM)"), 400
        cita.fecha_hora = fecha_hora
    if "estado" in data:
        # El estado (confirmada, atendida...) solo lo cambia el personal que gestiona citas.
        if not puede("citas.gestionar"):
            return jsonify(success=False, error="permiso_denegado", message="Solo el personal puede cambiar el estado"), 403
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
    if cita is None:
        if not puede("citas.gestionar"):
            return _sin_permiso()
        return jsonify(success=False, error="no_encontrado", message="Cita no existe"), 404
    if not _puede_gestionar(cita.paciente_id):
        return _sin_permiso()

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
        description: Filtrar por paciente (solo personal; un ciudadano siempre ve solo las suyas)
    responses:
      200:
        description: Lista de citas
    """
    query = CitaMedica.query
    if puede("citas.ver"):
        paciente_id = request.args.get("paciente_id")
        if paciente_id:
            query = query.filter_by(paciente_id=paciente_id)
    else:
        # OWASP API1 (BOLA): el ciudadano nunca ve citas de otros.
        propio = _paciente_propio()
        if propio is None:
            return jsonify(success=True, data=[]), 200
        query = query.filter_by(paciente_id=propio.id)

    citas = query.order_by(CitaMedica.fecha_hora.desc()).all()
    return jsonify(success=True, data=[{
        "id": c.id,
        "paciente_id": c.paciente_id,
        "medico_sub": c.medico_sub,
        "fecha_hora": str(c.fecha_hora),
        "estado": c.estado,
        "motivo": c.motivo,
        "costo": float(c.costo) if c.costo is not None else None,
        "pago_confirmado": bool(c.pago_confirmado),
    } for c in citas]), 200