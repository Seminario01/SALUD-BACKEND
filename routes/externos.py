import time
from datetime import datetime, timedelta

from flask import Blueprint, request, jsonify
from extensions import db
from models import (
    Paciente, CitaMedica, RecursoHospitalario, Turno, PresupuestoHospitalario,
    Vacunacion, Establecimiento, Practicante, HorasPractica, Receta, Medicamento,
)
from auth import validar_api_key, validar_api_key_o_token, ROLES_AUDITORIA
from bitacora import registrar, resumir
from services_externos import coordinar_jornada
from routes.hospitalizacion import resumen_hospitalizacion
from routes.caja import resumen_cuentas

externos_bp = Blueprint("externos", __name__)

OPERACIONES = {
    "externos.coordinar_jornada_vacunacion": "Coordinar jornada de vacunación (WS-SALUD-01)",
    "externos.establecimientos_disponibilidad": "Disponibilidad de establecimientos (WS-SALUD-02)",
    "externos.horas_practicante": "Horas de práctica (WS-SALUD-06)",
    "externos.costo_cita": "Costo y pago de una cita",
    "externos.indicadores": "Indicadores agregados",
    "externos.notificacion_pago": "Aviso de pago de una obligación",
}
MODULOS = {"seguridad": "Seguridad", "educacion": "Educación", "educación": "Educación",
           "tributario": "Tributario", "auditoria": "Auditoría", "auditoría": "Auditoría"}


@externos_bp.before_request
def _inicio():
    request._inicio_bitacora = time.perf_counter()


@externos_bp.after_request
def _registrar_entrante(respuesta):
    """Bitácora: otro módulo consumió un servicio de Salud con su API key."""
    if request.headers.get("X-API-Key"):
        origen = (request.headers.get("X-Modulo-Origen") or "").strip().lower()
        try:
            cuerpo = respuesta.get_json(silent=True) or {}
        except Exception:  # noqa: BLE001
            cuerpo = {}
        datos = cuerpo.get("data") if isinstance(cuerpo, dict) else None
        registrar(
            "entrante", MODULOS.get(origen, "Otro"), OPERACIONES.get(request.endpoint, request.path),
            request.method, request.full_path.rstrip("?"), respuesta.status_code,
            "ok" if respuesta.status_code < 400 else (cuerpo.get("error") or f"error_{respuesta.status_code}"),
            round((time.perf_counter() - getattr(request, "_inicio_bitacora", time.perf_counter())) * 1000),
            request.headers.get("X-Simulado", "").lower() == "true",
            resumir(datos if datos is not None else cuerpo) or cuerpo.get("message"),
        )
    return respuesta


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


def calcular_indicadores():
    """Indicadores agregados del módulo (sin datos personales). Los usan:
    - GET /indicadores (otros módulos, con API key)
    - GET /panel (frontend de Salud, con el token del usuario)"""
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
        "tipo": r.tipo, "descripcion": r.descripcion, "disponible": r.disponible, "total": r.total
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

    return {
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
        "hospitalizacion": resumen_hospitalizacion(),
        "farmacia": resumen_farmacia(),
        "cuentas": resumen_cuentas(),
        "presupuesto_servicio_social": presupuesto_resumen,
    }


def resumen_farmacia():
    """Recetas e inventario, agregados (sin datos personales)."""
    hace30 = datetime.now() - timedelta(days=30)
    return {
        "recetas_pendientes": Receta.query.filter_by(estado="PENDIENTE").count(),
        "recetas_despachadas_30_dias": Receta.query.filter(Receta.estado == "DESPACHADA",
                                                           Receta.fecha_despacho >= hace30).count(),
        "medicamentos_bajo_minimo": Medicamento.query.filter(Medicamento.existencia <= Medicamento.stock_minimo).count(),
    }


@externos_bp.route("/api/v1/salud/indicadores", methods=["GET"])
@validar_api_key_o_token(*ROLES_AUDITORIA)
def indicadores():
    """
    Indicadores generales del módulo de salud
    ---
    tags:
      - Integración externa
    description: >
      Para otros módulos con X-API-Key, o para Auditoría Social con el token
      del usuario (rol auditoria:analista / auditoria:admin).
    security:
      - ApiKeyAuth: []
      - BearerAuth: []
    responses:
      200:
        description: Indicadores del módulo de salud
    """
    return jsonify(success=True, data=calcular_indicadores()), 200


@externos_bp.route("/api/v1/salud/pagos/notificacion", methods=["POST"])
@validar_api_key
def notificacion_pago():
    """
    Aviso de Tributario: una obligación de pago de Salud fue pagada o anulada
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
          required: [numero_referencia, estado]
          properties:
            numero_referencia: {type: string, example: "SAL-2026-000120"}
            estado: {type: string, enum: [PAGADO, ANULADO], example: PAGADO}
            numero_autorizacion: {type: string, example: "AUT-7781234"}
            fecha_pago: {type: string, example: "2026-10-08T10:15:00"}
            monto_pagado: {type: number, example: 150.00}
    responses:
      200:
        description: Salud registró el aviso; la cita queda pagada (o con el cobro anulado)
      400:
        description: Faltan datos o el estado no es válido
      404:
        description: Salud no tiene una obligación con ese número de referencia
    """
    from datetime import datetime
    from routes.integraciones import marcar_pagada
    from routes.caja import aviso_de_pago

    data = request.get_json(silent=True) or {}
    referencia = (data.get("numero_referencia") or "").strip()
    estado = str(data.get("estado") or "").strip().upper()
    if not referencia or estado not in ("PAGADO", "ANULADO"):
        return jsonify(success=False, error="datos_incompletos",
                       message="numero_referencia y estado (PAGADO o ANULADO) son requeridos"), 400
    try:
        fecha = datetime.fromisoformat(str(data.get("fecha_pago")).replace("Z", "")) if data.get("fecha_pago") else None
    except ValueError:
        fecha = None
    cita = CitaMedica.query.filter_by(numero_referencia=referencia).first()
    if not cita:
        # ¿Es la referencia de una cuenta del paciente (hospitalización o ambulatoria)?
        cuenta = aviso_de_pago(referencia, estado, data.get("numero_autorizacion"), fecha)
        if cuenta is None:
            return jsonify(success=False, error="no_encontrado", message="Salud no tiene esa referencia"), 404
        return jsonify(success=True, data={"numero_referencia": referencia, "estado": cuenta.estado_cobro or "ANULADO",
                                           "cuenta_id": cuenta.id}, message="Aviso registrado"), 200
    if estado == "PAGADO":
        marcar_pagada(cita, data.get("numero_autorizacion"), fecha)
    else:
        cita.estado_cobro = "ANULADO"
        cita.pago_confirmado = False
    db.session.commit()
    return jsonify(success=True, data={"numero_referencia": referencia, "estado": cita.estado_cobro,
                                       "cita_id": cita.id}, message="Aviso registrado"), 200
