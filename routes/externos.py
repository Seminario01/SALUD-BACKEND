from flask import Blueprint, request, jsonify
from extensions import db
from models import (
    Paciente, CitaMedica, RecursoHospitalario, Turno, PresupuestoHospitalario,
    Vacunacion, Establecimiento, Practicante, HorasPractica,
)
from auth import validar_api_key
from services_externos import coordinar_jornada

externos_bp = Blueprint("externos", __name__)


@externos_bp.route("/api/v1/salud/jornadas/coordinar", methods=["POST"])
@validar_api_key
def coordinar_jornada_vacunacion():
    """
    WS-SALUD-01: Coordinación de jornadas de vacunación con Educación
    ---
    tags:
      - Integración externa
    security:
      - ApiKeyAuth: []
    parameters:
      - in: body
        name: body
        required: true
        schema:
          type: object
          required: [tipo_jornada, lugar, fecha, hora]
          properties:
            tipo_jornada:
              type: string
            lugar:
              type: string
            fecha:
              type: string
            hora:
              type: string
    responses:
      200:
        description: Estudiantes convocados a la jornada
      404:
        description: No se encontraron estudiantes para los criterios enviados
      500:
        description: Error al coordinar con Educación
    """
    data = request.get_json(silent=True) or {}
    tipo_jornada = data.get("tipo_jornada")
    lugar = data.get("lugar")
    fecha = data.get("fecha")
    hora = data.get("hora")

    if not all([tipo_jornada, lugar, fecha, hora]):
        return jsonify(
            success=False, error="datos_incompletos",
            message="tipo_jornada, lugar, fecha y hora son requeridos",
        ), 400

    resultado = coordinar_jornada(tipo_jornada, lugar, fecha, hora)
    if not resultado["success"]:
        return jsonify(
            success=False, error=resultado.get("error", "error_conexion"),
            message=resultado.get("message", "Error al coordinar la jornada con Educación"),
        ), 500

    estudiantes = resultado["data"]
    if not estudiantes:
        return jsonify(success=False, error="no_encontrado", message="No se encontraron estudiantes para la jornada"), 404

    return jsonify(success=True, data=estudiantes), 200


@externos_bp.route("/api/v1/salud/establecimientos/disponibilidad", methods=["GET"])
@validar_api_key
def establecimientos_disponibilidad():
    """
    WS-SALUD-02: Disponibilidad de establecimientos de salud
    ---
    tags:
      - Integración externa
    security:
      - ApiKeyAuth: []
    parameters:
      - in: query
        name: departamento
        type: string
        required: false
      - in: query
        name: municipio
        type: string
        required: false
      - in: query
        name: tipoAtencion
        type: string
        required: false
      - in: query
        name: nivelUrgencia
        type: string
        required: false
    responses:
      200:
        description: Disponibilidad de establecimientos
    """
    departamento = request.args.get("departamento")
    municipio = request.args.get("municipio")
    tipo_atencion = request.args.get("tipoAtencion")
    # nivelUrgencia se recibe por contrato con Seguridad; hoy no filtra en BD
    # porque el catálogo de establecimientos aún no clasifica por urgencia.
    request.args.get("nivelUrgencia")

    query = Establecimiento.query
    if departamento:
        query = query.filter(Establecimiento.departamento == departamento)
    if municipio:
        query = query.filter(Establecimiento.municipio == municipio)
    if tipo_atencion:
        query = query.filter(Establecimiento.tipo_atencion_disponible.ilike(f"%{tipo_atencion}%"))

    establecimientos = query.all()
    data = [{
        "nombreEstablecimiento": e.nombre,
        "tipoEstablecimiento": e.tipo,
        "direccion": e.direccion,
        "departamento": e.departamento,
        "municipio": e.municipio,
        "estadoServicio": e.estado_servicio,
        "tipoAtencionDisponible": e.tipo_atencion_disponible,
        "telefono": e.telefono,
    } for e in establecimientos]

    disponible = len(data) > 0
    mensaje = (
        "Se encontraron establecimientos disponibles"
        if disponible else
        "No se encontraron establecimientos para los criterios enviados"
    )

    return jsonify(success=True, disponible=disponible, establecimientos=data, mensaje=mensaje), 200


@externos_bp.route("/api/v1/salud/practicantes/<string:cui>/horas", methods=["GET"])
@validar_api_key
def horas_practicante(cui):
    """
    WS-SALUD-06: Seguimiento de horas de práctica de un practicante
    ---
    tags:
      - Integración externa
    security:
      - ApiKeyAuth: []
    parameters:
      - in: path
        name: cui
        type: string
        required: true
    responses:
      200:
        description: Horas acumuladas y estado del practicante
      404:
        description: Practicante no existe
    """
    practicante = Practicante.query.filter_by(dpi=cui).first()
    if not practicante:
        return jsonify(success=False, error="no_encontrado", message="Practicante no existe"), 404

    horas_acumuladas = (
        db.session.query(db.func.coalesce(db.func.sum(HorasPractica.horas), 0))
        .filter(HorasPractica.id_practicante == practicante.id_practicante)
        .scalar()
    )

    return jsonify(success=True, data={
        "horasAcumuladas": int(horas_acumuladas),
        "fechaInicio": practicante.fecha_inicio.isoformat() if practicante.fecha_inicio else None,
        "fechaFin": practicante.fecha_fin.isoformat() if practicante.fecha_fin else None,
        "supervisor": practicante.supervisor,
        "estado": practicante.estado,
    }), 200


@externos_bp.route("/api/v1/salud/citas/<int:id>/costo", methods=["GET"])
@validar_api_key
def costo_cita(id):
    """
    Costo y estado de pago de una cita médica
    ---
    tags:
      - Integración externa
    security:
      - ApiKeyAuth: []
    parameters:
      - in: path
        name: id
        type: integer
        required: true
    responses:
      200:
        description: Costo de la cita
      404:
        description: Cita no existe
    """
    cita = CitaMedica.query.get(id)
    if not cita:
        return jsonify(success=False, error="no_encontrado", message="Cita no existe"), 404

    return jsonify(success=True, data={
        "cita_id": cita.id,
        "monto": float(cita.costo) if cita.costo else 0,
        "pago_confirmado": cita.pago_confirmado,
    }), 200


@externos_bp.route("/api/v1/salud/indicadores", methods=["GET"])
@validar_api_key
def indicadores():
    """
    Indicadores generales del módulo de salud
    ---
    tags:
      - Integración externa
    security:
      - ApiKeyAuth: []
    responses:
      200:
        description: Indicadores del módulo de salud
    """
    citas_atendidas = CitaMedica.query.filter_by(estado="atendida").count()
    citas_pendientes = CitaMedica.query.filter_by(estado="pendiente").count()
    citas_canceladas = CitaMedica.query.filter_by(estado="cancelada").count()

    pacientes_totales = Paciente.query.count()

    turnos_en_espera = Turno.query.filter_by(estado="en_espera").count()
    turnos_atendidos = Turno.query.filter_by(estado="atendido").count()

    vacunacion_esquema_completo = Vacunacion.query.filter_by(esquema_completo=True).count()
    vacunacion_pendiente = Vacunacion.query.filter_by(esquema_completo=False).count()
    estudiantes_vacunados = Vacunacion.query.filter_by(es_estudiante=True, esquema_completo=True).count()

    recursos = RecursoHospitalario.query.all()
    recursos_resumen = [{
        "tipo": r.tipo, "disponible": r.disponible, "total": r.total
    } for r in recursos]

    presupuesto = PresupuestoHospitalario.query.order_by(
        PresupuestoHospitalario.fecha_actualizacion.desc()
    ).first()
    presupuesto_resumen = None
    if presupuesto:
        presupuesto_resumen = {
            "periodo": presupuesto.periodo,
            "monto_asignado": float(presupuesto.monto_asignado),
            "monto_ejecutado_servicio_social": float(presupuesto.monto_ejecutado_servicio_social or 0),
        }

    return jsonify(success=True, data={
        "pacientes_totales": pacientes_totales,
        "citas": {
            "atendidas": citas_atendidas,
            "pendientes": citas_pendientes,
            "canceladas": citas_canceladas,
        },
        "turnos": {
            "en_espera": turnos_en_espera,
            "atendidos": turnos_atendidos,
        },
        "vacunacion": {
            "esquema_completo": vacunacion_esquema_completo,
            "pendiente": vacunacion_pendiente,
            "estudiantes_vacunados": estudiantes_vacunados,
        },
        "recursos_hospitalarios": recursos_resumen,
        "presupuesto_servicio_social": presupuesto_resumen,
    }), 200
