from flask import Blueprint, request, jsonify
from extensions import db
from models import Paciente, CitaMedica, RecursoHospitalario, Turno, PresupuestoHospitalario, Vacunacion
from auth import validar_api_key

externos_bp = Blueprint("externos", __name__)


@externos_bp.route("/api/v1/salud/estudiantes/vacunacion", methods=["GET"])
@validar_api_key
def estudiantes_vacunacion():
    """
    Estado de vacunación de pacientes que son estudiantes
    ---
    tags:
      - Integración externa
    security:
      - ApiKeyAuth: []
    responses:
      200:
        description: Lista de estudiantes con su estado de vacunación
    """
    registros = (
        db.session.query(Vacunacion, Paciente)
        .join(Paciente, Vacunacion.paciente_id == Paciente.id)
        .filter(Vacunacion.es_estudiante.is_(True))
        .all()
    )

    return jsonify(success=True, data=[{
        "paciente_id": vacunacion.paciente_id,
        "nombre_completo": paciente.nombre_completo,
        "cui": paciente.cui,
        "esquema_completo": vacunacion.esquema_completo,
        "vacunas_pendientes": vacunacion.vacunas_pendientes,
    } for vacunacion, paciente in registros]), 200


@externos_bp.route("/api/v1/salud/recursos/disponibilidad", methods=["GET"])
@validar_api_key
def recursos_disponibilidad():
    """
    Disponibilidad de recursos hospitalarios
    ---
    tags:
      - Integración externa
    security:
      - ApiKeyAuth: []
    responses:
      200:
        description: Disponibilidad de recursos
    """
    recursos = RecursoHospitalario.query.all()
    return jsonify(success=True, data=[{
        "tipo": r.tipo, "disponible": r.disponible, "total": r.total
    } for r in recursos]), 200


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
