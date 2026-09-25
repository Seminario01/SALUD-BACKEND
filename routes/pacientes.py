from datetime import date
from flask import Blueprint, request, jsonify, g
from extensions import db
from models import Paciente
from auth import (validar_token, requiere_rol, es_personal, tiene_rol,
                  ROL_ADMIN, ROL_MEDICO, ROL_RECEPCION)

pacientes_bp = Blueprint("pacientes", __name__)


def puede_ver_paciente(paciente):
    """OWASP API1 (BOLA): el personal de Salud ve a cualquier paciente; un
    ciudadano solo el registro vinculado a su propio `sub`."""
    if es_personal():
        return True
    return paciente is not None and paciente.usuario_sub == g.usuario["sub"]


def serializar_paciente(p):
    return {
        "id": p.id,
        "cui": p.cui,
        "nombre_completo": p.nombre_completo,
        "fecha_nacimiento": str(p.fecha_nacimiento) if p.fecha_nacimiento else None,
        "genero": p.genero,
        "telefono": p.telefono,
        "tipo_seguro": p.tipo_seguro,
        "cuidador": p.cuidador,
        "tiene_cuenta": p.usuario_sub is not None,
    }


@pacientes_bp.route("/api/v1/salud/pacientes", methods=["GET"])
@validar_token
@requiere_rol(ROL_ADMIN, ROL_MEDICO, ROL_RECEPCION)
def listar_pacientes():
    """
    Listar pacientes (solo personal de Salud)
    ---
    tags:
      - Pacientes
    security:
      - BearerAuth: []
    parameters:
      - name: q
        in: query
        type: string
        required: false
        description: Buscar por nombre o CUI
    responses:
      200:
        description: Lista de pacientes
      401:
        description: Sin token o token inválido
      403:
        description: El usuario no es personal de Salud
    """
    query = Paciente.query
    q = request.args.get("q", "").strip()
    if q:
        like = f"%{q}%"
        query = query.filter(db.or_(Paciente.nombre_completo.like(like), Paciente.cui.like(like)))
    pacientes = query.order_by(Paciente.nombre_completo).all()
    return jsonify(success=True, data=[serializar_paciente(p) for p in pacientes]), 200


@pacientes_bp.route("/api/v1/salud/pacientes/me", methods=["GET"])
@validar_token
def mi_registro():
    """
    Registro de paciente del usuario autenticado (ciudadano)
    ---
    tags:
      - Pacientes
    security:
      - BearerAuth: []
    responses:
      200:
        description: Registro propio
      404:
        description: El usuario no tiene registro de paciente vinculado
    """
    paciente = Paciente.query.filter_by(usuario_sub=g.usuario["sub"]).first()
    if not paciente:
        return jsonify(success=False, error="no_encontrado", message="No tiene un registro de paciente vinculado"), 404
    return jsonify(success=True, data=serializar_paciente(paciente)), 200


@pacientes_bp.route("/api/v1/salud/pacientes", methods=["POST"])
@validar_token
@requiere_rol(ROL_ADMIN, ROL_RECEPCION)
def crear_paciente():
    """
    Registrar paciente
    ---
    tags:
      - Pacientes
    security:
      - BearerAuth: []
    parameters:
      - name: body
        in: body
        required: true
        schema:
          type: object
          required: [nombre_completo]
          properties:
            cui: {type: string}
            nombre_completo: {type: string}
            fecha_nacimiento: {type: string, example: "2000-01-15"}
            genero: {type: string}
            telefono: {type: string}
            tipo_seguro: {type: string}
            cuidador: {type: string}
            usuario_sub:
              type: string
              description: sub del ciudadano en el Login Único (opcional)
    responses:
      201:
        description: Paciente registrado
    """
    data = request.get_json() or {}
    if not data.get("nombre_completo"):
        return jsonify(success=False, error="datos_invalidos", message="nombre_completo es obligatorio"), 400
    fecha_nacimiento = None
    if data.get("fecha_nacimiento"):
        try:
            fecha_nacimiento = date.fromisoformat(data["fecha_nacimiento"])
        except ValueError:
            return jsonify(success=False, error="datos_invalidos", message="fecha_nacimiento inválida (AAAA-MM-DD)"), 400

    paciente = Paciente(
        cui=data.get("cui"),
        nombre_completo=data["nombre_completo"],
        fecha_nacimiento=fecha_nacimiento,
        genero=data.get("genero"),
        telefono=data.get("telefono"),
        tipo_seguro=data.get("tipo_seguro"),
        cuidador=data.get("cuidador"),
        usuario_sub=data.get("usuario_sub"),
    )
    db.session.add(paciente)
    db.session.commit()
    return jsonify(success=True, data={"id": paciente.id}, message="Paciente registrado"), 201


@pacientes_bp.route("/api/v1/salud/pacientes/<int:id>", methods=["GET"])
@validar_token
def obtener_paciente(id):
    """
    Obtener paciente por id (personal, o el propio ciudadano)
    ---
    tags:
      - Pacientes
    security:
      - BearerAuth: []
    parameters:
      - name: id
        in: path
        type: integer
        required: true
    responses:
      200:
        description: Paciente
      403:
        description: El registro no pertenece al usuario
      404:
        description: Paciente no existe
    """
    paciente = Paciente.query.get(id)
    # Para un ciudadano, "no existe" y "no es tuyo" responden igual (403),
    # así no puede adivinar qué ids existen.
    if not puede_ver_paciente(paciente):
        return jsonify(success=False, error="permiso_denegado", message="Solo puede ver su propio registro"), 403
    if not paciente:
        return jsonify(success=False, error="no_encontrado", message="Paciente no existe"), 404

    return jsonify(success=True, data=serializar_paciente(paciente)), 200


@pacientes_bp.route("/api/v1/salud/pacientes/<int:id>", methods=["PUT"])
@validar_token
def actualizar_paciente(id):
    """
    Actualizar teléfono, seguro o cuidador (admin/recepción, o el propio ciudadano)
    ---
    tags:
      - Pacientes
    security:
      - BearerAuth: []
    parameters:
      - name: id
        in: path
        type: integer
        required: true
      - name: body
        in: body
        schema:
          type: object
          properties:
            telefono: {type: string}
            tipo_seguro: {type: string}
            cuidador: {type: string}
    responses:
      200:
        description: Actualizado
      403:
        description: Sin permiso sobre este registro
    """
    paciente = Paciente.query.get(id)
    es_dueno = paciente is not None and paciente.usuario_sub == g.usuario["sub"]
    if not (es_dueno or tiene_rol(ROL_ADMIN, ROL_RECEPCION)):
        return jsonify(success=False, error="permiso_denegado", message="No puede modificar este registro"), 403
    if not paciente:
        return jsonify(success=False, error="no_encontrado", message="Paciente no existe"), 404

    data = request.get_json() or {}
    for campo in ["telefono", "tipo_seguro", "cuidador"]:
        if campo in data:
            setattr(paciente, campo, data[campo])

    db.session.commit()
    return jsonify(success=True, data={"id": paciente.id}, message="Actualizado"), 200
