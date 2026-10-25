import logging
import time
from datetime import datetime, timedelta

from flask import Blueprint, g, request, jsonify
from extensions import db
from models import (
    Paciente, CitaMedica, RecursoHospitalario, Turno, PresupuestoHospitalario,
    Vacunacion, Establecimiento, Practicante, HorasPractica, Receta, Medicamento, EstudianteJornada,
)
from auth import validar_api_key, validar_api_key_o_token, ROLES_AUDITORIA
from bitacora import registrar, resumir, solicitud_entrante
from services_externos import coordinar_jornada
from routes.hospitalizacion import resumen_hospitalizacion
from routes.caja import resumen_cuentas
from routes.integraciones import _error_modulo
from routes.jornadas import guardar_jornada
from validacion import ESCAPE_LIKE, contiene, empieza

externos_bp = Blueprint("externos", __name__)
log = logging.getLogger(__name__)

OPERACIONES = {
    "externos.coordinar_jornada_vacunacion": "Coordinar jornada de vacunación (WS-SALUD-01)",
    "externos.establecimientos_disponibilidad": "Disponibilidad de establecimientos (WS-SALUD-02)",
    "externos.horas_practicante": "Horas de práctica (WS-SALUD-06)",
    "externos.costo_cita": "Costo y pago de una cita",
    "externos.indicadores": "Indicadores agregados",
    "externos.notificacion_pago": "Aviso de pago de una obligación",
    "externos.confirmacion_pago": "Confirmación de pago (Tributario)",
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
        # La clave identifica al módulo; el header X-Modulo-Origen solo se usa con la clave común
        por_clave = getattr(g, "modulo_api_key", None)
        try:
            cuerpo = respuesta.get_json(silent=True) or {}
        except Exception:  # noqa: BLE001
            cuerpo = {}
        datos = cuerpo.get("data") if isinstance(cuerpo, dict) else None
        registrar(
            "entrante", por_clave if por_clave not in (None, "Común") else MODULOS.get(origen, "Otro"), OPERACIONES.get(request.endpoint, request.path),
            request.method, request.full_path.rstrip("?"), respuesta.status_code,
            "ok" if respuesta.status_code < 400 else (cuerpo.get("error") or f"error_{respuesta.status_code}"),
            round((time.perf_counter() - getattr(request, "_inicio_bitacora", time.perf_counter())) * 1000),
            request.headers.get("X-Simulado", "").lower() == "true",
            resumir(datos if datos is not None else cuerpo) or cuerpo.get("message"),
            *solicitud_entrante(), cuerpo,
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
      422:
        description: Educación rechazó la petición (con su motivo)
      424:
        description: Educación respondió algo que Salud no puede usar, o no aceptó la clave de Salud
      503:
        description: Educación no está configurado o no responde (3 s)
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
    if resultado.get("error") == "no_encontrado":
        return jsonify(success=False, error="no_encontrado", message="No se encontraron estudiantes para la jornada"), 404
    if not resultado["success"]:
        # Falla de Educación, no de Salud: 503 / 422 / 424 como las demás integraciones (nunca 500)
        return _error_modulo(resultado, "Educación")

    estudiantes = resultado["data"]
    if not isinstance(estudiantes, list):
        return jsonify(success=False, error="respuesta_invalida", modulo="Educación",
                       message="Educación debe responder una lista de estudiantes"), 424
    if not estudiantes:
        return jsonify(success=False, error="no_encontrado", message="No se encontraron estudiantes para la jornada"), 404

    # Salud guarda la jornada para que el personal la vea en Vacunación → Jornadas (si falla, la respuesta sigue)
    try:
        guardar_jornada(tipo_jornada, lugar, fecha, hora, estudiantes, "Educación")
    except Exception as error:  # noqa: BLE001
        db.session.rollback()
        log.warning("No se pudo guardar la jornada coordinada por Educación: %s", error)

    return jsonify(success=True, data=estudiantes), 200


TIPOS_ATENCION = ("EMERGENCIA", "CONSULTA_GENERAL", "ESPECIALIDAD", "VACUNACION")


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
        name: especialidad
        type: string
        required: false
        description: "Tipo de atención (EMERGENCIA, CONSULTA_GENERAL, ESPECIALIDAD, VACUNACION) o una especialidad médica (devuelve los que atienden ESPECIALIDAD)"
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
    tipo_atencion = (request.args.get("tipoAtencion") or "").strip().upper() or None
    if tipo_atencion and tipo_atencion not in TIPOS_ATENCION:
        return jsonify(success=False, error="parametro_invalido",
                       message=f"tipoAtencion debe ser uno de: {', '.join(TIPOS_ATENCION)}"), 400
    # especialidad (acordado con Seguridad): si es un tipo de atención (EMERGENCIA...) filtra por él;
    # si es una especialidad médica (Traumatología, Pediatría...) devuelve los que atienden ESPECIALIDAD.
    especialidad = (request.args.get("especialidad") or "").strip()
    if especialidad and not tipo_atencion:
        tipo_atencion = especialidad.upper() if especialidad.upper() in TIPOS_ATENCION else "ESPECIALIDAD"
    # nivelUrgencia se recibe por contrato con Seguridad; hoy no filtra en BD
    # porque el catálogo de establecimientos aún no clasifica por urgencia.
    request.args.get("nivelUrgencia")

    query = Establecimiento.query.filter(Establecimiento.estado_servicio == "ACTIVO")   # contrato: solo los activos
    if departamento:
        query = query.filter(Establecimiento.departamento == departamento)
    if municipio:
        query = query.filter(Establecimiento.municipio == municipio)
    if tipo_atencion:
        query = query.filter(Establecimiento.tipo_atencion_disponible.ilike(contiene(tipo_atencion), escape=ESCAPE_LIKE))

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
        "nivel": e.nivel,                            # Referencia nacional, Regional, Departamental, Distrital...
        "codigoMunicipio": e.codigo_municipio,       # código INE de 4 dígitos
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
    # Estudiantes vacunados: solo los que Educación convocó a una jornada (su lista) y Enfermería marcó.
    # Salud no guarda por su cuenta quién es estudiante: eso lo confirma Educación.
    estudiantes_vacunados = (db.session.query(db.func.count(db.distinct(EstudianteJornada.cui)))
                             .filter(EstudianteJornada.vacunado.is_(True), EstudianteJornada.cui.isnot(None)).scalar() or 0)

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


@externos_bp.route("/api/v1/salud/pagos/confirmacion", methods=["POST"])
@validar_api_key
def confirmacion_pago():
    """
    Confirmación de pago de Tributario (pago aprobado, rechazado, parcial o anulado)
    ---
    tags:
      - Integración externa
    security:
      - ApiKeyAuth: []
    description: >
      Formato acordado con Tributario. El header Idempotency-Key debe ser igual a
      evento_id: si el mismo evento llega dos veces, Salud responde 200 sin volver a
      procesarlo. La referencia puede ser de una cita o de una cuenta del paciente.
    parameters:
      - in: header
        name: Idempotency-Key
        type: string
        required: false
      - in: body
        name: body
        required: true
        schema:
          type: object
          properties:
            evento_id: {type: string, example: "pago-aprobado-123"}
            data:
              type: object
              properties:
                numero_referencia: {type: string, example: "SAL-2026-000120"}
                referencia_tributario: {type: string, example: "REF-TRIB-000123"}
                estado: {type: string, example: "APROBADO"}
                estado_pago: {type: string, example: "PAGADO"}
                numero_autorizacion: {type: string, example: "123456"}
                monto_pagado: {type: number, example: 150.00}
                fecha_pago: {type: string, example: "2026-10-10T11:30:00"}
    responses:
      200:
        description: Procesado (también si el evento ya se había procesado)
      400:
        description: Datos incompletos
      401:
        description: Sin API key
      403:
        description: API key inválida o de otro módulo
      404:
        description: numero_referencia inexistente en Salud
      409:
        description: El monto pagado no coincide con lo cobrado
    """
    return _procesar_pago()


@externos_bp.route("/api/v1/salud/pagos/notificacion", methods=["POST"])
@validar_api_key
def notificacion_pago():
    """
    Aviso de pago (formato anterior, se mantiene por compatibilidad)
    ---
    tags:
      - Integración externa
    security:
      - ApiKeyAuth: []
    description: >
      Igual que POST /pagos/confirmacion. Acepta también el cuerpo plano:
      numero_referencia, estado (PAGADO o ANULADO), numero_autorizacion, fecha_pago, monto_pagado.
    responses:
      200:
        description: Procesado
      400:
        description: Datos incompletos
      404:
        description: Referencia desconocida
    """
    return _procesar_pago()


def _procesar_pago():
    import pagos
    # Si Tributario ya tiene su propia clave, solo esa (o la común) puede confirmar pagos
    if getattr(g, "modulo_api_key", None) not in ("Tributario", "Común"):
        return jsonify(success=False, error="api_key_invalida",
                       message="Esta clave no corresponde al módulo Tributario"), 403
    status, cuerpo = pagos.procesar(request.get_json(silent=True), request.headers.get("Idempotency-Key"))
    return jsonify(cuerpo), status
