"""
Integración con los otros módulos (Salud CONSUME sus servicios).

El frontend nunca llama directo a otro módulo: pide aquí, con el token del
usuario, y el backend de Salud llama al módulo destino (servidor a servidor).
Si el otro módulo no está configurado o no responde, se devuelve un error
claro (503) y la operación propia de Salud no se ve afectada.
"""
from datetime import date, datetime, timedelta

from flask import Blueprint, jsonify, request

from auth import validar_token, requiere_permiso
from config import Config
from extensions import db
from models import BitacoraIntegracion, CitaMedica, Paciente
from services_externos import (
    consultar_antecedentes_seguridad,
    disparar_caso_simulado,
    obtener_estudiante,
    obtener_indicadores_educacion,
    obtener_indicadores_seguridad,
    obtener_indicadores_tributario,
    consultar_obligacion,
    registrar_obligacion,
)

integraciones_bp = Blueprint("integraciones", __name__)

MENSAJES = {
    "no_configurado": "El módulo {m} no está configurado (falta su URL en el .env del backend).",
    "modulo_no_disponible": "El módulo {m} no está disponible en este momento. Intente más tarde.",
    "respuesta_invalida": "El módulo {m} respondió con un formato inesperado.",
}


def _error_modulo(resultado, modulo):
    codigo = resultado.get("error", "modulo_no_disponible")
    status = 502 if codigo == "respuesta_invalida" else 503
    mensaje = MENSAJES.get(codigo, MENSAJES["modulo_no_disponible"]).format(m=modulo)
    if resultado.get("detalle"):
        mensaje = f"{modulo} rechazó la solicitud: {resultado['detalle']}"
    return jsonify(success=False, error=codigo, modulo=modulo, message=mensaje), status


@integraciones_bp.route("/api/v1/salud/integraciones/estado", methods=["GET"])
@validar_token
@requiere_permiso("integraciones.ver")
def estado_integraciones():
    """
    Estado de conexión con los otros módulos
    ---
    tags:
      - Integraciones
    security:
      - BearerAuth: []
    responses:
      200:
        description: "Por módulo: conectado, no_disponible o no_configurado (y si es un simulador)"
    """
    modulos = {
        "educacion": (Config.URL_EDUCACION, obtener_indicadores_educacion),
        "seguridad": (Config.URL_SEGURIDAD, obtener_indicadores_seguridad),
        "tributario": (Config.URL_TRIBUTARIO, obtener_indicadores_tributario),
    }
    estado = {}
    for nombre, (url, ping) in modulos.items():
        r = ping(registrar=False)
        # Cualquier respuesta HTTP (aunque sea 404 o un formato distinto) significa que el módulo responde
        if r["success"] or r.get("error") in ("no_encontrado", "respuesta_invalida"):
            datos = r.get("data") if isinstance(r.get("data"), dict) else {}
            indicadores = {k: v for k, v in datos.items() if k not in ("simulado", "modulo")}
            estado[nombre] = {"estado": "conectado", "simulado": bool(r.get("simulado") or datos.get("simulado")),
                              "indicadores": indicadores}
        elif r.get("error") == "no_configurado":
            estado[nombre] = {"estado": "no_configurado", "simulado": False}
        else:
            estado[nombre] = {"estado": "no_disponible", "simulado": False}
    return jsonify(success=True, data=estado), 200


@integraciones_bp.route("/api/v1/salud/pacientes/<int:id>/antecedentes", methods=["GET"])
@validar_token
@requiere_permiso("pacientes.antecedentes")
def antecedentes_paciente(id):
    """
    WS-SALUD-08 - Consultar antecedentes del paciente en Seguridad
    ---
    tags:
      - Integraciones
    security:
      - BearerAuth: []
    description: >
      El paciente se atiende siempre; el resultado solo indica si se requieren
      cuidados o custodia adicionales.
    parameters:
      - name: id
        in: path
        type: integer
        required: true
    responses:
      200:
        description: Resultado de Seguridad (tieneAntecedentes, tipoAntecedente, nivelRiesgo, requiereCustodia)
      400:
        description: El paciente no tiene CUI registrado
      503:
        description: Seguridad no configurado o no disponible
    """
    paciente = Paciente.query.get(id)
    if not paciente:
        return jsonify(success=False, error="no_encontrado", message="Paciente no existe"), 404
    if not paciente.cui:
        return jsonify(success=False, error="datos_incompletos",
                       message="El paciente no tiene CUI registrado; no se puede consultar a Seguridad"), 400

    r = consultar_antecedentes_seguridad(paciente.cui, paciente.nombre_completo)
    if r.get("error") == "no_encontrado":
        # Seguridad no tiene registro de la persona: sin antecedentes conocidos
        return jsonify(success=True, data={"encontrado": False, "tieneAntecedentes": False}), 200
    if not r["success"]:
        return _error_modulo(r, "Seguridad")
    datos = r["data"] if isinstance(r["data"], dict) else {}
    return jsonify(success=True, data={"encontrado": True, **datos}), 200


@integraciones_bp.route("/api/v1/salud/educacion/estudiantes/<string:cui>", methods=["GET"])
@validar_token
@requiere_permiso("vacunacion.registrar")
def estudiante_educacion(cui):
    """
    Consultar en Educación si un CUI corresponde a un estudiante
    ---
    tags:
      - Integraciones
    security:
      - BearerAuth: []
    parameters:
      - name: cui
        in: path
        type: string
        required: true
    responses:
      200:
        description: "esEstudiante true/false y, si aplica, establecimiento, grado, sección y jornada"
      503:
        description: Educación no configurado o no disponible
    """
    r = obtener_estudiante(cui)
    if r.get("error") == "no_encontrado":
        return jsonify(success=True, data={"esEstudiante": False}), 200
    if not r["success"]:
        return _error_modulo(r, "Educación")
    datos = r["data"] if isinstance(r["data"], dict) else {}
    return jsonify(success=True, data={"esEstudiante": True, **datos}), 200


# ---------------------------------------------------------------------------
# Tributario: obligaciones de pago de las citas
# ---------------------------------------------------------------------------
ESTADOS_PAGADO = ("PAGADO", "PAGADA", "CONFIRMADO", "APROBADO", "CANCELADO_PAGO")
TIPO_OBLIGACION = {"emergencia": "EMERGENCIA", "especialidad": "ESPECIALIDAD"}


def _siguiente_referencia():
    """SAL-AAAA-NNNNNN, correlativo por año."""
    prefijo = f"SAL-{date.today().year}-"
    ultima = db.session.query(db.func.max(CitaMedica.numero_referencia)) \
        .filter(CitaMedica.numero_referencia.like(prefijo + "%")).scalar()
    numero = int(ultima.rsplit("-", 1)[1]) + 1 if ultima else 1
    return f"{prefijo}{numero:06d}"


def _estado_cobro(cita):
    return {
        "citaId": cita.id,
        "numeroReferencia": cita.numero_referencia,
        "estadoCobro": "PAGADO" if cita.pago_confirmado else cita.estado_cobro,
        "pagoConfirmado": bool(cita.pago_confirmado),
        "monto": float(cita.costo) if cita.costo is not None else None,
        "fechaVencimiento": cita.fecha_vencimiento.isoformat() if cita.fecha_vencimiento else None,
        "numeroAutorizacion": cita.numero_autorizacion,
        "fechaPago": cita.fecha_pago.isoformat(timespec="minutes") if cita.fecha_pago else None,
    }


def marcar_pagada(cita, autorizacion=None, fecha_pago=None):
    cita.pago_confirmado = True
    cita.estado_cobro = "PAGADO"
    cita.numero_autorizacion = autorizacion or cita.numero_autorizacion
    cita.fecha_pago = fecha_pago or cita.fecha_pago or datetime.now()


def _fecha_hora(valor):
    try:
        return datetime.fromisoformat(str(valor).replace("Z", "")) if valor else None
    except ValueError:
        return None


def _registrar_cobro(cita, paciente):
    """Envía la obligación a Tributario. Devuelve (ok, respuesta_error)."""
    if not cita.numero_referencia:
        cita.numero_referencia = _siguiente_referencia()
        db.session.commit()
    if not cita.costo:
        cita.costo = Config.COSTO_CONSULTA
    hoy = date.today()
    vence = hoy + timedelta(days=Config.DIAS_VENCIMIENTO_COBRO)
    r = registrar_obligacion(cita.numero_referencia, paciente.cui, "CONSULTA_MEDICA",
                             (cita.motivo or "Consulta médica general")[:200], cita.costo,
                             hoy.isoformat(), vence.isoformat())
    duplicada = not r["success"] and r.get("estado_http") == 409
    if not r["success"] and not duplicada:
        return False, _error_modulo(r, "Tributario")
    datos = r.get("data") if isinstance(r.get("data"), dict) else {}
    estado = str(datos.get("estado") or "PENDIENTE").upper()
    cita.estado_cobro = estado if not duplicada else (cita.estado_cobro or "PENDIENTE")
    cita.fecha_vencimiento = cita.fecha_vencimiento or vence
    if estado in ESTADOS_PAGADO:
        marcar_pagada(cita, datos.get("numero_autorizacion") or datos.get("numeroAutorizacion"))
    db.session.commit()
    return True, None


def _cita_y_paciente(id):
    cita = CitaMedica.query.get(id)
    if not cita:
        return None, None, (jsonify(success=False, error="no_encontrado", message="Cita no existe"), 404)
    paciente = Paciente.query.get(cita.paciente_id)
    if not paciente or not paciente.cui:
        return cita, None, (jsonify(success=False, error="datos_incompletos",
                                    message="El paciente no tiene CUI registrado; Tributario lo necesita"), 400)
    if cita.estado == "cancelada":
        return cita, None, (jsonify(success=False, error="cita_cancelada",
                                    message="La cita está cancelada"), 409)
    return cita, paciente, None


@integraciones_bp.route("/api/v1/salud/citas/<int:id>/cobro", methods=["POST"])
@validar_token
@requiere_permiso("pagos.verificar")
def enviar_cobro(id):
    """
    Enviar a Tributario el cobro de una cita (obligación de pago)
    ---
    tags:
      - Integraciones
    security:
      - BearerAuth: []
    description: >
      Genera el número de referencia SAL-AAAA-NNNNNN (si la cita no tiene) y
      registra la obligación en Tributario: dpi_persona, tipo_obligacion,
      concepto, monto, moneda GTQ, fecha_emision y fecha_vencimiento. Si ya
      estaba registrada, no la duplica.
    parameters:
      - name: id
        in: path
        type: integer
        required: true
    responses:
      200:
        description: "numeroReferencia, estadoCobro, monto, fechaVencimiento"
      409:
        description: La cita está cancelada
      503:
        description: Tributario no configurado o no disponible
    """
    cita, paciente, error = _cita_y_paciente(id)
    if error:
        return error
    # Ya pagada, o ya registrada en Tributario (y no anulada): no se reenvía
    if cita.pago_confirmado or (cita.estado_cobro and cita.estado_cobro != "ANULADO"):
        return jsonify(success=True, data=_estado_cobro(cita)), 200
    if cita.estado_cobro == "ANULADO":
        cita.numero_referencia = None   # una obligación anulada no se reutiliza: referencia nueva
    ok, error = _registrar_cobro(cita, paciente)
    if not ok:
        return error
    return jsonify(success=True, data=_estado_cobro(cita)), 200


@integraciones_bp.route("/api/v1/salud/citas/<int:id>/verificar-pago", methods=["POST"])
@validar_token
@requiere_permiso("pagos.verificar")
def verificar_pago_cita(id):
    """
    Consultar en Tributario si el cobro de una cita ya se pagó
    ---
    tags:
      - Integraciones
    security:
      - BearerAuth: []
    description: >
      Consulta el estado de la obligación por su número de referencia. Si la
      cita aún no tenía cobro, primero lo registra. Si Tributario la reporta
      pagada, la cita queda con pago confirmado y número de autorización.
    parameters:
      - name: id
        in: path
        type: integer
        required: true
    responses:
      200:
        description: "pagoConfirmado true/false, numeroReferencia, estadoCobro, numeroAutorizacion"
      503:
        description: Tributario no configurado o no disponible
    """
    cita, paciente, error = _cita_y_paciente(id)
    if error:
        return error
    if not cita.pago_confirmado:
        if not cita.estado_cobro:
            ok, error = _registrar_cobro(cita, paciente)
            if not ok:
                return error
        if not cita.pago_confirmado:
            r = consultar_obligacion(cita.numero_referencia)
            if not r["success"]:
                return _error_modulo(r, "Tributario")
            datos = r["data"] if isinstance(r["data"], dict) else {}
            estado = str(datos.get("estado") or datos.get("estado_pago") or "PENDIENTE").upper()
            if estado in ESTADOS_PAGADO or datos.get("pagoConfirmado") is True:
                marcar_pagada(cita, datos.get("numero_autorizacion") or datos.get("numeroAutorizacion"),
                              _fecha_hora(datos.get("fecha_pago") or datos.get("fechaPago")))
            else:
                cita.estado_cobro = estado
            db.session.commit()
    return jsonify(success=True, data=_estado_cobro(cita)), 200


# ---------------------------------------------------------------------------
# Bitácora y demostración de la integración
# ---------------------------------------------------------------------------
MODULOS_BITACORA = ("Educación", "Seguridad", "Tributario", "Auditoría", "Otro")


@integraciones_bp.route("/api/v1/salud/integraciones/bitacora", methods=["GET"])
@validar_token
@requiere_permiso("integraciones.ver")
def bitacora_integraciones():
    """
    Bitácora de llamadas entre Salud y los otros módulos
    ---
    tags:
      - Integraciones
    security:
      - BearerAuth: []
    description: >
      Cada consulta que Salud hace a otro módulo (saliente) y cada servicio de
      Salud que otro módulo consume con API key (entrante). Los CUI se muestran
      enmascarados.
    parameters:
      - name: modulo
        in: query
        type: string
        enum: [Educación, Seguridad, Tributario, Auditoría, Otro]
      - name: direccion
        in: query
        type: string
        enum: [saliente, entrante]
      - name: limite
        in: query
        type: integer
        default: 50
    responses:
      200:
        description: Registros, del más reciente al más antiguo, y totales por módulo
    """
    query = BitacoraIntegracion.query
    modulo = request.args.get("modulo")
    direccion = request.args.get("direccion")
    if modulo:
        query = query.filter(BitacoraIntegracion.modulo == modulo)
    if direccion in ("saliente", "entrante"):
        query = query.filter(BitacoraIntegracion.direccion == direccion)
    try:
        limite = max(1, min(int(request.args.get("limite", 50)), 200))
    except ValueError:
        limite = 50
    registros = query.order_by(BitacoraIntegracion.id.desc()).limit(limite).all()

    totales = dict(db.session.query(BitacoraIntegracion.modulo, db.func.count())
                   .group_by(BitacoraIntegracion.modulo).all())
    return jsonify(success=True, data=[{
        "id": r.id, "fecha": r.fecha.isoformat(timespec="seconds"), "direccion": r.direccion,
        "modulo": r.modulo, "operacion": r.operacion, "metodo": r.metodo, "ruta": r.ruta,
        "estadoHttp": r.estado_http, "resultado": r.resultado, "duracionMs": r.duracion_ms,
        "simulado": r.simulado, "usuario": r.usuario, "detalle": r.detalle,
    } for r in registros], totales=totales), 200


CASOS_SIMULADOS = {
    # caso: (módulo simulado que hace la consulta, URL de ese módulo)
    "seguridad-establecimientos": "URL_SEGURIDAD",
    "educacion-jornada": "URL_EDUCACION",
    "educacion-practicante": "URL_EDUCACION",
    "tributario-costo": "URL_TRIBUTARIO",
    "tributario-pago": "URL_TRIBUTARIO",
    "auditoria-indicadores": "URL_SEGURIDAD",   # Auditoría la maneja la ingeniera; se simula desde el mismo servidor
}


@integraciones_bp.route("/api/v1/salud/integraciones/simular/<string:caso>", methods=["POST"])
@validar_token
@requiere_permiso("integraciones.demo")
def simular_consulta_entrante(caso):
    """
    Demostración - un módulo SIMULADO consume un servicio de Salud
    ---
    tags:
      - Integraciones
    security:
      - BearerAuth: []
    description: >
      Le pide al simulador que haga de Seguridad, Educación, Tributario o
      Auditoría y llame a un servicio de Salud con su API key. Solo funciona
      mientras ese módulo esté configurado con los simuladores.
    parameters:
      - name: caso
        in: path
        type: string
        required: true
        enum: [seguridad-establecimientos, educacion-jornada, educacion-practicante, tributario-costo, tributario-pago, auditoria-indicadores]
    responses:
      200:
        description: Petición que hizo el módulo simulado y respuesta de Salud
      404:
        description: Caso desconocido
      503:
        description: El módulo no está configurado con los simuladores
    """
    if caso not in CASOS_SIMULADOS:
        return jsonify(success=False, error="no_encontrado", message="Caso desconocido"), 404
    url = getattr(Config, CASOS_SIMULADOS[caso])
    cuerpo = {}
    if caso == "tributario-costo":
        cita = CitaMedica.query.filter(CitaMedica.costo.isnot(None)).order_by(CitaMedica.id.desc()).first()
        cuerpo["cita_id"] = cita.id if cita else 1
    if caso == "tributario-pago":
        cita = CitaMedica.query.filter(CitaMedica.estado_cobro == "PENDIENTE", CitaMedica.pago_confirmado.is_(False)) \
            .order_by(CitaMedica.id.desc()).first()
        if not cita:
            return jsonify(success=False, error="sin_cobros_pendientes",
                           message="No hay cobros pendientes: primero envíe un cobro desde Citas"), 409
        cuerpo.update(numero_referencia=cita.numero_referencia, monto=float(cita.costo or 0))
    r = disparar_caso_simulado(url, caso, cuerpo)
    if not r["success"]:
        if r.get("error") in ("no_encontrado", "respuesta_invalida"):
            return jsonify(success=False, error="no_simulado",
                           message="Ese módulo no está usando los simuladores: la demostración solo funciona con ellos."), 503
        return _error_modulo(r, "simulado")
    return jsonify(success=True, data=r["data"]), 200
