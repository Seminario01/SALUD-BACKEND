from flask import Blueprint, request, jsonify
from datetime import date, datetime
from extensions import db
from models import Turno, Paciente
from auth import validar_token, requiere_permiso, puede
from validacion import entero

turnos_bp = Blueprint("turnos", __name__)

TIPOS_ATENCION = ("consulta_general", "emergencia", "especialidad")
PRIORIDADES = ("normal", "urgente")

@turnos_bp.route("/api/v1/salud/turnos", methods=["POST"])
@validar_token
@requiere_permiso("turnos.generar")
def generar_turno():
    data = request.get_json(silent=True) or {}
    if not data.get("paciente_id") or not data.get("tipo_atencion"):
        return jsonify(success=False, error="datos_invalidos",
                       message="paciente_id y tipo_atencion son obligatorios"), 400
    if data["tipo_atencion"] not in TIPOS_ATENCION:
        return jsonify(success=False, error="datos_invalidos",
                       message="tipo_atencion debe ser: " + ", ".join(TIPOS_ATENCION)), 400
    if data.get("prioridad", "normal") not in PRIORIDADES:
        return jsonify(success=False, error="datos_invalidos",
                       message="prioridad debe ser: " + ", ".join(PRIORIDADES)), 400
    paciente_id = entero(data, "paciente_id", 1, 2_147_483_647, obligatorio=True)
    if not Paciente.query.get(paciente_id):
        return jsonify(success=False, error="no_encontrado", message="El paciente no existe"), 404
    # Un paciente no puede estar dos veces en la fila de hoy
    hoy = datetime.combine(date.today(), datetime.min.time())
    if Turno.query.filter(Turno.paciente_id == paciente_id, Turno.fecha_hora_ingreso >= hoy,
                          Turno.estado.in_(["en_espera", "llamado", "en_atencion"])).first():
        return jsonify(success=False, error="ya_existe",
                       message="El paciente ya tiene un turno activo hoy"), 409

    # Los turnos usan la hora LOCAL del servidor (TZ=America/Guatemala en Docker).
    # Antes se guardaba en UTC pero se comparaba con la fecha local: después de
    # las 18:00 en Guatemala ya era "mañana" en UTC y la numeración volvía a 1.
    ahora = datetime.now()
    inicio_del_dia = datetime.combine(ahora.date(), datetime.min.time())
    ultimo = Turno.query.filter(Turno.fecha_hora_ingreso >= inicio_del_dia) \
        .order_by(Turno.numero_turno.desc()).first()
    siguiente_numero = (ultimo.numero_turno + 1) if ultimo else 1

    turno = Turno(
        paciente_id=paciente_id,
        tipo_atencion=data["tipo_atencion"],
        prioridad=data.get("prioridad", "normal"),
        numero_turno=siguiente_numero,
        fecha_hora_ingreso=ahora,
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
    # Solo los de HOY: la numeración se reinicia cada día, así que un turno
    # olvidado de ayer mezclaría números repetidos en la sala de espera.
    turnos = Turno.query.filter(Turno.estado.in_(["en_espera", "llamado", "en_atencion"]),
                                Turno.fecha_hora_ingreso >= datetime.combine(date.today(), datetime.min.time())) \
        .order_by(Turno.prioridad.desc(), Turno.fecha_hora_ingreso.asc()).all()

    # El nombre del paciente es un dato personal: solo para el personal de Salud.
    personal = puede("turnos.ver_cola")
    nombres = {}
    if personal and turnos:
        ids = {t.paciente_id for t in turnos}
        nombres = {p.id: p.nombre_completo for p in Paciente.query.filter(Paciente.id.in_(ids)).all()}

    def serializar(t):
        dato = {"id": t.id, "numero_turno": t.numero_turno, "estado": t.estado,
                "prioridad": t.prioridad, "tipo_atencion": t.tipo_atencion,
                "modulo_asignado": t.modulo_asignado,
                # La pantalla de la sala anuncia por voz cada llamado nuevo (o cuando se vuelve a llamar)
                "llamado_en": t.fecha_hora_llamado.isoformat(timespec="seconds") if t.fecha_hora_llamado else None}
        if personal:
            dato.update(paciente_id=t.paciente_id, paciente=nombres.get(t.paciente_id))
        return dato

    return jsonify(success=True, data=[serializar(t) for t in turnos]), 200


@turnos_bp.route("/api/v1/salud/turnos/<int:id>/llamar", methods=["PUT"])
@validar_token
@requiere_permiso("turnos.atender")
def llamar_turno(id):
    turno = Turno.query.get(id)
    if not turno:
        return jsonify(success=False, error="no_encontrado", message="Turno no existe"), 404

    turno.estado = "llamado"
    turno.fecha_hora_llamado = datetime.now()
    # Opcional: a qué consultorio/ventanilla debe pasar (se muestra en la sala de espera)
    modulo = ((request.get_json(silent=True) or {}).get("modulo_asignado") or "").strip()
    if modulo:
        turno.modulo_asignado = modulo[:50]
    db.session.commit()
    return jsonify(success=True, data={"id": turno.id}, message="Turno llamado"), 200


@turnos_bp.route("/api/v1/salud/turnos/<int:id>/atender", methods=["PUT"])
@validar_token
@requiere_permiso("turnos.atender")
def atender_turno(id):
    turno = Turno.query.get(id)
    if not turno:
        return jsonify(success=False, error="no_encontrado", message="Turno no existe"), 404

    turno.estado = "en_atencion"
    turno.fecha_hora_atencion = datetime.now()
    db.session.commit()
    return jsonify(success=True, data={"id": turno.id}, message="Turno en atención"), 200


@turnos_bp.route("/api/v1/salud/turnos/<int:id>/finalizar", methods=["PUT"])
@validar_token
@requiere_permiso("turnos.atender")
def finalizar_turno(id):
    turno = Turno.query.get(id)
    if not turno:
        return jsonify(success=False, error="no_encontrado", message="Turno no existe"), 404

    turno.estado = "atendido"
    db.session.commit()
    return jsonify(success=True, data={"id": turno.id}, message="Turno finalizado"), 200