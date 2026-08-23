from flask import Blueprint, request, jsonify
from datetime import datetime, date
from extensions import db
from models import Turno
from auth import validar_token, requiere_rol

turnos_bp = Blueprint("turnos", __name__)

@turnos_bp.route("/api/v1/salud/turnos", methods=["POST"])
@validar_token
@requiere_rol("admin", "recepcion")
def generar_turno():
    data = request.get_json()

    hoy = date.today()
    ultimo = Turno.query.filter(db.func.date(Turno.fecha_hora_ingreso) == hoy).order_by(Turno.numero_turno.desc()).first()
    siguiente_numero = (ultimo.numero_turno + 1) if ultimo else 1

    turno = Turno(
        paciente_id=data["paciente_id"],
        tipo_atencion=data["tipo_atencion"],
        prioridad=data.get("prioridad", "normal"),
        numero_turno=siguiente_numero,
    )
    db.session.add(turno)
    db.session.commit()

    en_espera = Turno.query.filter_by(estado="en_espera").count()

    return jsonify(success=True, data={
        "numero_turno": turno.numero_turno,
        "posicion_en_fila": en_espera,
    }, message="Turno generado"), 201


@turnos_bp.route("/api/v1/salud/turnos/activos", methods=["GET"])
@validar_token
def turnos_activos():
    turnos = Turno.query.filter(Turno.estado.in_(["en_espera", "llamado", "en_atencion"])) \
        .order_by(Turno.prioridad.desc(), Turno.fecha_hora_ingreso.asc()).all()

    return jsonify(success=True, data=[{
        "id": t.id, "numero_turno": t.numero_turno, "estado": t.estado,
        "prioridad": t.prioridad, "tipo_atencion": t.tipo_atencion
    } for t in turnos]), 200


@turnos_bp.route("/api/v1/salud/turnos/<int:id>/llamar", methods=["PUT"])
@validar_token
@requiere_rol("admin", "medico")
def llamar_turno(id):
    turno = Turno.query.get(id)
    if not turno:
        return jsonify(success=False, error="no_encontrado", message="Turno no existe"), 404

    turno.estado = "llamado"
    turno.fecha_hora_llamado = datetime.utcnow()
    db.session.commit()
    return jsonify(success=True, data={"id": turno.id}, message="Turno llamado"), 200


@turnos_bp.route("/api/v1/salud/turnos/<int:id>/atender", methods=["PUT"])
@validar_token
@requiere_rol("admin", "medico")
def atender_turno(id):
    turno = Turno.query.get(id)
    if not turno:
        return jsonify(success=False, error="no_encontrado", message="Turno no existe"), 404

    turno.estado = "en_atencion"
    turno.fecha_hora_atencion = datetime.utcnow()
    db.session.commit()
    return jsonify(success=True, data={"id": turno.id}, message="Turno en atención"), 200


@turnos_bp.route("/api/v1/salud/turnos/<int:id>/finalizar", methods=["PUT"])
@validar_token
@requiere_rol("admin", "medico")
def finalizar_turno(id):
    turno = Turno.query.get(id)
    if not turno:
        return jsonify(success=False, error="no_encontrado", message="Turno no existe"), 404

    turno.estado = "atendido"
    db.session.commit()
    return jsonify(success=True, data={"id": turno.id}, message="Turno finalizado"), 200