from flask import Blueprint, g, request, jsonify
from datetime import date, datetime
from extensions import db
from models import Turno, Paciente
from auth import validar_token, requiere_permiso, puede
from validacion import entero, opcion, texto
from sedes import de_la_sede, filtrar, sede_para_crear

turnos_bp = Blueprint("turnos", __name__)

TIPOS_ATENCION = ("consulta_general", "emergencia", "especialidad")
PRIORIDADES = ("normal", "urgente")

# Triage de 5 niveles (como el sistema Manchester): color, nombre y tiempo máximo de espera
# recomendado. La cola se ordena por nivel y, dentro del nivel, por orden de llegada.
TRIAGE = {
    "ROJO": {"orden": 0, "nombre": "Inmediato", "minutos": 0},
    "NARANJA": {"orden": 1, "nombre": "Muy urgente", "minutos": 10},
    "AMARILLO": {"orden": 2, "nombre": "Urgente", "minutos": 60},
    "VERDE": {"orden": 3, "nombre": "Poco urgente", "minutos": 120},
    "AZUL": {"orden": 4, "nombre": "No urgente", "minutos": 240},
}


def _orden_cola(t):
    """Sin clasificar: urgente entre naranja y amarillo; normal como verde."""
    nivel = TRIAGE[t.triage]["orden"] if t.triage in TRIAGE else (1.5 if t.prioridad == "urgente" else 3)
    return (nivel, t.fecha_hora_ingreso or datetime.min)


def _clasificar(turno, data):
    """Aplica el triage del cuerpo (nivel y motivo) al turno; la prioridad sigue al nivel."""
    nivel = opcion(data, "triage", tuple(TRIAGE), obligatorio=True, etiqueta="El nivel de triage")
    turno.triage = nivel
    turno.motivo_triage = texto(data, "motivo_triage", 255, etiqueta="El motivo")
    turno.triage_por = (g.usuario.get("nombre") or g.usuario.get("usuario") or "")[:150] or None
    turno.fecha_triage = datetime.now()
    turno.prioridad = "urgente" if TRIAGE[nivel]["orden"] <= 1 else "normal"

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
    # La numeración es de cada sede (cada una tiene su sala de espera).
    ahora = datetime.now()
    inicio_del_dia = datetime.combine(ahora.date(), datetime.min.time())
    sede = sede_para_crear()
    ultimo = Turno.query.filter(Turno.fecha_hora_ingreso >= inicio_del_dia, de_la_sede(Turno.sede_id, sede)) \
        .order_by(Turno.numero_turno.desc()).first()
    siguiente_numero = (ultimo.numero_turno + 1) if ultimo else 1

    turno = Turno(
        paciente_id=paciente_id,
        tipo_atencion=data["tipo_atencion"],
        prioridad=data.get("prioridad", "normal"),
        numero_turno=siguiente_numero,
        fecha_hora_ingreso=ahora,
        sede_id=sede,
    )
    # El triage al generar el turno solo lo pone quien puede clasificar (Enfermería o Médico)
    if data.get("triage") is not None:
        if not puede("turnos.clasificar"):
            return jsonify(success=False, error="permiso_denegado",
                           message="Solo Enfermería o un médico pueden clasificar la urgencia (triage)"), 403
        _clasificar(turno, data)
    db.session.add(turno)
    db.session.commit()

    en_espera = Turno.query.filter(Turno.estado == "en_espera", de_la_sede(Turno.sede_id, sede),
                                   Turno.fecha_hora_ingreso >= inicio_del_dia).count()

    return jsonify(success=True, data={
        "numero_turno": turno.numero_turno,
        "posicion_en_fila": en_espera,
    }, message="Turno generado"), 201


@turnos_bp.route("/api/v1/salud/turnos/activos", methods=["GET"])
@validar_token
def turnos_activos():
    # Solo los de HOY: la numeración se reinicia cada día, así que un turno
    # olvidado de ayer mezclaría números repetidos en la sala de espera.
    turnos = filtrar(Turno.query, Turno).filter(Turno.estado.in_(["en_espera", "llamado", "en_atencion"]),
                                                Turno.fecha_hora_ingreso >= datetime.combine(date.today(), datetime.min.time())).all()
    turnos.sort(key=_orden_cola)
    ahora = datetime.now()

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
                "llamado_en": t.fecha_hora_llamado.isoformat(timespec="seconds") if t.fecha_hora_llamado else None,
                "triage": t.triage, "triage_nombre": TRIAGE[t.triage]["nombre"] if t.triage in TRIAGE else None,
                "sede_id": t.sede_id}
        if personal:
            espera = max(0, int((ahora - t.fecha_hora_ingreso).total_seconds() // 60)) if t.fecha_hora_ingreso else None
            objetivo = TRIAGE[t.triage]["minutos"] if t.triage in TRIAGE else None
            dato.update(paciente_id=t.paciente_id, paciente=nombres.get(t.paciente_id),
                        motivo_triage=t.motivo_triage, triage_por=t.triage_por,
                        ingreso=t.fecha_hora_ingreso.isoformat(timespec="seconds") if t.fecha_hora_ingreso else None,
                        espera_min=espera, objetivo_min=objetivo,
                        # Esperando más de lo recomendado para su nivel (solo los que todavía no pasan)
                        excede=bool(objetivo is not None and espera is not None and t.estado == "en_espera" and espera > objetivo))
        return dato

    return jsonify(success=True, data=[serializar(t) for t in turnos]), 200


@turnos_bp.route("/api/v1/salud/turnos/triage", methods=["GET"])
@validar_token
def niveles_triage():
    """Niveles de triage (color, nombre y minutos máximos de espera recomendados)."""
    return jsonify(success=True, data=[{"nivel": k, **v} for k, v in TRIAGE.items()]), 200


@turnos_bp.route("/api/v1/salud/turnos/<int:id>/triage", methods=["PUT"])
@validar_token
@requiere_permiso("turnos.clasificar")
def clasificar_turno(id):
    """
    Clasificar la urgencia de un turno (triage de 5 niveles)
    ---
    tags:
      - Turnos
    security:
      - BearerAuth: []
    description: >
      Enfermería o un médico. La cola se ordena por nivel (ROJO inmediato, NARANJA 10 min,
      AMARILLO 60, VERDE 120, AZUL 240) y dentro del nivel por llegada. ROJO y NARANJA quedan urgentes.
    parameters:
      - {name: id, in: path, type: integer, required: true}
      - in: body
        name: body
        required: true
        schema:
          type: object
          required: [triage]
          properties:
            triage: {type: string, enum: [ROJO, NARANJA, AMARILLO, VERDE, AZUL]}
            motivo_triage: {type: string, example: "Dolor torácico de 30 minutos"}
    responses:
      200:
        description: Clasificado
      404:
        description: El turno no existe
      409:
        description: El turno ya fue atendido o no se presentó
    """
    turno = Turno.query.get(id)
    if not turno:
        return jsonify(success=False, error="no_encontrado", message="Turno no existe"), 404
    if turno.estado not in ("en_espera", "llamado", "en_atencion"):
        return jsonify(success=False, error="estado_invalido", message="El turno ya terminó: no se puede clasificar"), 409
    _clasificar(turno, request.get_json(silent=True) or {})
    db.session.commit()
    return jsonify(success=True, data={"id": turno.id, "triage": turno.triage, "prioridad": turno.prioridad},
                   message=f"Turno {turno.numero_turno} clasificado: {TRIAGE[turno.triage]['nombre'].lower()}"), 200


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