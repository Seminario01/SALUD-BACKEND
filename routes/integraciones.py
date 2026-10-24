"""
Integración con los otros módulos (Salud CONSUME sus servicios).

El frontend nunca llama directo a otro módulo: pide aquí, con el token del
usuario, y el backend de Salud llama al módulo destino (servidor a servidor).
Si el otro módulo no está configurado o no responde, se devuelve un error
claro (503) y la operación propia de Salud no se ve afectada.
"""
import json
import re
from datetime import date, datetime, timedelta

from flask import Blueprint, jsonify, request

from auth import validar_token, requiere_permiso
from config import Config
from extensions import db
from models import BitacoraIntegracion, CitaMedica, CuentaPaciente, Paciente
from services_externos import (
    consultar_antecedentes_seguridad,
    obtener_alertas_seguridad,
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
    """Respuesta de Salud cuando falla la llamada a otro módulo.

    422 = el módulo recibió la petición y la rechazó (se muestra su motivo).
    424 = el módulo respondió algo que Salud no puede usar (formato inesperado
          o no aceptó nuestra clave).
    503 = el módulo no está configurado o no responde.
    No se usa 502: los proxies (nginx, Cloudflare) lo reemplazan por su propia
    página y el mensaje no llega al navegador."""
    codigo = resultado.get("error", "modulo_no_disponible")
    estado = resultado.get("estado_http") or 0
    mensaje = MENSAJES.get(codigo, MENSAJES["modulo_no_disponible"]).format(m=modulo)
    status = 503
    if codigo == "respuesta_invalida":
        rechazo = 400 <= estado < 500
        status = 422 if rechazo and estado not in (401, 403) else 424
        if resultado.get("detalle"):
            mensaje = f"{modulo} rechazó la solicitud: {resultado['detalle']}"
        elif rechazo:
            mensaje = f"{modulo} rechazó la solicitud (código {estado}) sin indicar el motivo."
    return jsonify(success=False, error=codigo, modulo=modulo, message=mensaje), status


RUTA_INDICADORES = {"educacion": "/api/v1/educacion/indicadores", "seguridad": "/api/v1/seguridad/indicadores",
                    "tributario": "/api/v1/tributario/indicadores"}


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
            simulado = bool(r.get("simulado") or datos.get("simulado"))
            if simulado and not Config.SIMULACIONES:
                estado[nombre] = {"estado": "no_configurado", "simulado": False}
                continue
            estado[nombre] = {"estado": "conectado", "simulado": simulado, "indicadores": indicadores,
                              "estadoHttp": r.get("estado_http"), "ruta": RUTA_INDICADORES[nombre]}
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
    if not re.fullmatch(r"\d{13}", paciente.cui.strip()):
        return jsonify(success=False, error="cui_invalido",
                       message="El CUI del paciente debe tener exactamente 13 dígitos para consultar a Seguridad"), 400

    r = consultar_antecedentes_seguridad(paciente.cui.strip(), paciente.nombre_completo)
    if r.get("error") == "no_encontrado":
        # 404 de Seguridad: sin antecedentes ACTIVOS encontrados. No distingue "no registrado" de
        # "registrado sin antecedentes", así que no es una certificación (lo aclaró Seguridad).
        return jsonify(success=True, data={"encontrado": False, "tieneAntecedentes": False}), 200
    if not r["success"]:
        return _error_modulo(r, "Seguridad")
    datos = _normalizar_antecedentes(r["data"] if isinstance(r["data"], dict) else {})
    return jsonify(success=True, data={"encontrado": True, **datos}), 200


def _normalizar_antecedentes(datos):
    """Acepta los nombres de campo del contrato (camelCase) y variantes snake_case de Seguridad."""
    equivalentes = {
        "tieneAntecedentes": ("tiene_antecedentes", "antecedentes"),
        "tipoAntecedente": ("tipo_antecedente", "tipo"),
        "nivelRiesgo": ("nivel_riesgo", "riesgo"),
        "requiereCustodia": ("requiere_custodia", "custodia"),
    }
    salida = dict(datos)
    for campo, variantes in equivalentes.items():
        if campo not in salida:
            for v in variantes:
                if v in datos and not isinstance(datos[v], (list, dict)):
                    salida[campo] = datos[v]
                    break
    if isinstance(salida.get("nivelRiesgo"), str):
        salida["nivelRiesgo"] = salida["nivelRiesgo"].upper()
    return salida


@integraciones_bp.route("/api/v1/salud/seguridad/alertas", methods=["GET"])
@validar_token
@requiere_permiso("turnos.ver_cola")
def alertas_seguridad():
    """
    Alertas activas de Seguridad en la zona del hospital
    ---
    tags:
      - Integraciones
    security:
      - BearerAuth: []
    description: >
      Salud consulta a Seguridad (GET /api/v1/seguridad/alertas?zona=&departamento=)
      con el departamento configurado (DEPARTAMENTO_ALERTAS). Sirve para que
      Emergencias se prepare ante accidentes o eventos con posibles heridos.
    responses:
      200:
        description: Lista de alertas (id, tipo, zona, departamento, nivel, descripcion, estado)
      503:
        description: Seguridad no configurado o no disponible
    """
    r = obtener_alertas_seguridad(Config.ZONA_ALERTAS, Config.DEPARTAMENTO_ALERTAS)
    if not r["success"]:
        return _error_modulo(r, "Seguridad")
    datos = r["data"]
    if isinstance(datos, dict):   # {"alertas": [...]}, {"items": [...]} o similar
        datos = next((v for k in ("alertas", "items", "resultados", "data") if isinstance(v := datos.get(k), list)), [])
    lista = [a for a in (datos or []) if isinstance(a, dict)]
    activas = [a for a in lista if str(a.get("estado", "ACTIVA")).upper() in ("ACTIVA", "ACTIVO", "ABIERTA")]
    return jsonify(success=True, data={"departamento": Config.DEPARTAMENTO_ALERTAS, "alertas": activas}), 200


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
ESTADOS_ANULADO = ("ANULADO", "ANULADA", "CANCELADO", "CANCELADA")
TIPO_OBLIGACION = {"emergencia": "EMERGENCIA", "especialidad": "ESPECIALIDAD"}


def _siguiente_referencia():
    """SAL-AAAA-NNNNNN, correlativo por año, compartido por citas y cuentas del paciente."""
    prefijo = f"SAL-{date.today().year}-"
    ultimas = [
        db.session.query(db.func.max(modelo.numero_referencia)).filter(modelo.numero_referencia.like(prefijo + "%")).scalar()
        for modelo in (CitaMedica, CuentaPaciente)
    ]
    numeros = [int(u.rsplit("-", 1)[1]) for u in ultimas if u]
    return f"{prefijo}{(max(numeros) if numeros else 0) + 1:06d}"


def _estado_cobro(cita):
    return {
        "citaId": cita.id,
        "numeroReferencia": cita.numero_referencia,
        "estadoCobro": "PAGADO" if cita.pago_confirmado else cita.estado_cobro,
        "pagoConfirmado": bool(cita.pago_confirmado),
        "monto": float(cita.costo) if cita.costo is not None else None,
        "fechaVencimiento": cita.fecha_vencimiento.isoformat() if cita.fecha_vencimiento else None,
        "numeroAutorizacion": cita.numero_autorizacion,
        "referenciaTributario": cita.referencia_tributario,
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


def resultado_registro(r, modulo="Tributario"):
    """Interpreta la respuesta de Tributario al registrar una obligación.

    201 = nueva, 200 = reenvío idéntico (ya existía): las dos están bien.
    409 = la referencia ya existe con datos DISTINTOS: es un conflicto.
    Devuelve (datos, respuesta_error)."""
    if r["success"]:
        return (r.get("data") if isinstance(r.get("data"), dict) else {}), None
    if r.get("estado_http") == 409:
        return None, (jsonify(success=False, error="conflicto_tributario", modulo=modulo,
                              message="Tributario ya tiene esa referencia con datos distintos. "
                                      f"Detalle: {r.get('detalle') or r.get('message')}"), 409)
    return None, _error_modulo(r, modulo)


def emision_y_vencimiento(fecha_vencimiento):
    """Fechas del cobro. Si ya se registró, se reutilizan (un reenvío debe ser idéntico)."""
    dias = timedelta(days=Config.DIAS_VENCIMIENTO_COBRO)
    if fecha_vencimiento:
        return fecha_vencimiento - dias, fecha_vencimiento
    hoy = date.today()
    return hoy, hoy + dias


def _registrar_cobro(cita, paciente):
    """Envía la obligación a Tributario. Devuelve (ok, respuesta_error)."""
    if not cita.numero_referencia:
        cita.numero_referencia = _siguiente_referencia()
        db.session.commit()
    if not cita.costo:
        cita.costo = Config.COSTO_CONSULTA
    emision, vence = emision_y_vencimiento(cita.fecha_vencimiento)
    r = registrar_obligacion(cita.numero_referencia, paciente.cui, Config.TIPO_OBLIGACION_CONSULTA,
                             (cita.motivo or "Consulta médica general")[:200], cita.costo,
                             emision.isoformat(), vence.isoformat())
    datos, error = resultado_registro(r)
    if error:
        return False, error
    estado = str(datos.get("estado") or "PENDIENTE").upper()
    cita.estado_cobro = estado
    cita.fecha_vencimiento = vence
    cita.referencia_tributario = datos.get("referencia_tributario") or cita.referencia_tributario
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
            if not r["success"] and r.get("estado_http") in (404, 405):
                # Tributario no tiene consulta de estado (o aún no la publica): el pago se
                # confirma cuando Tributario envía su aviso a POST /pagos/confirmacion.
                return jsonify(success=True, data=_estado_cobro(cita),
                               message="Tributario aún no ha confirmado el pago"), 200
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
    if not Config.SIMULACIONES:
        query = query.filter(BitacoraIntegracion.simulado.is_(False))
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

    conteo = db.session.query(BitacoraIntegracion.modulo, db.func.count())
    if not Config.SIMULACIONES:
        conteo = conteo.filter(BitacoraIntegracion.simulado.is_(False))
    totales = dict(conteo.group_by(BitacoraIntegracion.modulo).all())
    return jsonify(success=True, data=[{
        "id": r.id, "fecha": r.fecha.isoformat(timespec="seconds"), "direccion": r.direccion,
        "modulo": r.modulo, "operacion": r.operacion, "metodo": r.metodo, "ruta": r.ruta,
        "estadoHttp": r.estado_http, "resultado": r.resultado, "duracionMs": r.duracion_ms,
        "simulado": r.simulado, "usuario": r.usuario, "detalle": r.detalle,
    } for r in registros], totales=totales), 200


# Contrato de integración: cada servicio que Salud consume (saliente) o expone (entrante).
# Se reconocen en la bitácora por su "operacion" (el nombre fijo con que se anota cada llamada)
# o, si no tiene nombre propio, por el inicio de la ruta.
SERVICIOS = [
    # --- Salud consume ---
    {"clave": "edu-estudiante", "direccion": "saliente", "modulo": "Educación", "codigo": "E1",
     "nombre": "Consultar si un paciente es estudiante", "metodo": "GET", "ruta": "/api/v1/educacion/estudiantes/{cui}",
     "operaciones": ["Consultar estudiante"], "donde": "Vacunación → Verificar en Educación"},
    {"clave": "edu-jornada", "direccion": "saliente", "modulo": "Educación", "codigo": "E2",
     "nombre": "Estudiantes convocados a una jornada", "metodo": "POST", "ruta": "/api/v1/educacion/jornadas/coordinar",
     "operaciones": ["Coordinar jornada de vacunación (WS-SALUD-01)"], "donde": "Cuando Educación coordina una jornada (WS-SALUD-01)"},
    {"clave": "edu-indicadores", "direccion": "saliente", "modulo": "Educación", "codigo": "E3",
     "nombre": "Indicadores de Educación", "metodo": "GET", "ruta": "/api/v1/educacion/indicadores",
     "prefijo": "/api/v1/educacion/indicadores", "conexion": "educacion", "donde": "Tarjeta de Educación (arriba)"},
    {"clave": "seg-antecedentes", "direccion": "saliente", "modulo": "Seguridad", "codigo": "WS-SALUD-08",
     "nombre": "Antecedentes del paciente y custodia", "metodo": "GET", "ruta": "/api/v1/seguridad/ciudadanos/antecedentes/{cui}",
     "operaciones": ["Consultar antecedentes (WS-SALUD-08)"], "donde": "Pacientes → Consultar"},
    {"clave": "seg-alertas", "direccion": "saliente", "modulo": "Seguridad", "codigo": None,
     "nombre": "Alertas de seguridad", "metodo": "GET", "ruta": "/api/v1/seguridad/alertas",
     "operaciones": ["Consultar alertas"], "donde": "Inicio (alertas de seguridad)"},
    {"clave": "seg-indicadores", "direccion": "saliente", "modulo": "Seguridad", "codigo": None,
     "nombre": "Indicadores de Seguridad", "metodo": "GET", "ruta": "/api/v1/seguridad/indicadores",
     "prefijo": "/api/v1/seguridad/indicadores", "conexion": "seguridad", "donde": "Tarjeta de Seguridad (arriba)"},
    {"clave": "tri-obligacion", "direccion": "saliente", "modulo": "Tributario", "codigo": None,
     "nombre": "Registrar el cobro (obligación de pago)", "metodo": "POST", "ruta": "/api/v1/integraciones/salud/obligaciones",
     "operaciones": ["Registrar obligación de pago"], "donde": "Citas o Caja → Enviar cobro"},
    {"clave": "tri-consulta", "direccion": "saliente", "modulo": "Tributario", "codigo": None,
     "nombre": "Consultar si el cobro ya se pagó", "metodo": "GET", "ruta": "/api/v1/integraciones/salud/obligaciones/{referencia}",
     "operaciones": ["Consultar obligación de pago"], "donde": "Citas o Caja → Verificar pago"},
    {"clave": "tri-indicadores", "direccion": "saliente", "modulo": "Tributario", "codigo": None,
     "nombre": "Indicadores de Tributario", "metodo": "GET", "ruta": "/api/v1/tributario/indicadores",
     "prefijo": "/api/v1/tributario/indicadores", "conexion": "tributario", "donde": "Tarjeta de Tributario (arriba)"},
    # --- Le consumen a Salud ---
    {"clave": "s-jornada", "direccion": "entrante", "modulo": "Educación", "codigo": "WS-SALUD-01",
     "nombre": "Coordinar una jornada de vacunación", "metodo": "POST", "ruta": "/api/v1/salud/jornadas/coordinar",
     "operaciones": ["Coordinar jornada de vacunación (WS-SALUD-01)"]},
    {"clave": "s-horas", "direccion": "entrante", "modulo": "Educación", "codigo": "WS-SALUD-06",
     "nombre": "Horas de práctica de un practicante", "metodo": "GET", "ruta": "/api/v1/salud/practicantes/{cui}/horas",
     "operaciones": ["Horas de práctica (WS-SALUD-06)"]},
    {"clave": "s-establecimientos", "direccion": "entrante", "modulo": "Seguridad", "codigo": "WS-SALUD-02",
     "nombre": "Establecimientos disponibles ante una emergencia", "metodo": "GET", "ruta": "/api/v1/salud/establecimientos/disponibilidad",
     "operaciones": ["Disponibilidad de establecimientos (WS-SALUD-02)"]},
    {"clave": "s-costo", "direccion": "entrante", "modulo": "Tributario", "codigo": None,
     "nombre": "Costo y estado de pago de una cita", "metodo": "GET", "ruta": "/api/v1/salud/citas/{id}/costo",
     "operaciones": ["Costo y pago de una cita"]},
    {"clave": "s-aviso-pago", "direccion": "entrante", "modulo": "Tributario", "codigo": None,
     "nombre": "Aviso o confirmación de pago de una obligación", "metodo": "POST", "ruta": "/api/v1/salud/pagos/notificacion (y /pagos/confirmacion)",
     "operaciones": ["Aviso de pago de una obligación", "Confirmación de pago (Tributario)"]},
    {"clave": "s-indicadores", "direccion": "entrante", "modulo": "Auditoría", "codigo": None,
     "nombre": "Indicadores agregados", "metodo": "GET", "ruta": "/api/v1/salud/indicadores",
     "operaciones": ["Indicadores agregados"]},
    {"clave": "s-presupuesto", "direccion": "entrante", "modulo": "Auditoría", "codigo": None,
     "nombre": "Ejecución presupuestaria", "metodo": "GET", "ruta": "/api/v1/salud/presupuesto/ejecucion",
     "operaciones": ["Ejecución presupuestaria"]},
    {"clave": "s-tablero", "direccion": "entrante", "modulo": "Auditoría", "codigo": None,
     "nombre": "Tablero de Auditoría (indicadores por rango)", "metodo": "GET", "ruta": "/api/v1/salud/auditoria/indicadores",
     "operaciones": ["Tablero de Auditoría (indicadores por rango)"]},
]


# "no_encontrado" también es una respuesta válida del otro módulo (por ejemplo, "ese CUI no es estudiante")
RESPUESTAS_VALIDAS = ("ok", "no_encontrado")


def _registro(r):
    return r and {"fecha": r.fecha.isoformat(timespec="seconds"), "modulo": r.modulo, "resultado": r.resultado,
                  "estadoHttp": r.estado_http, "duracionMs": r.duracion_ms, "detalle": r.detalle,
                  "usuario": r.usuario, "simulado": r.simulado}


def _llamadas_de(s):
    """Consulta de la bitácora con las llamadas de un servicio del contrato."""
    base = BitacoraIntegracion.query.filter(BitacoraIntegracion.direccion == s["direccion"])
    if not Config.SIMULACIONES:
        base = base.filter(BitacoraIntegracion.simulado.is_(False))
    if s.get("operaciones"):
        base = base.filter(BitacoraIntegracion.operacion.in_(s["operaciones"]))
    else:
        base = base.filter(BitacoraIntegracion.ruta.like(f"{s['prefijo']}%"))
    if s["direccion"] == "saliente":
        base = base.filter(BitacoraIntegracion.modulo == s["modulo"])
    return base


def _json(texto):
    if not texto:
        return None
    try:
        return json.loads(texto)
    except ValueError:
        return texto


@integraciones_bp.route("/api/v1/salud/integraciones/servicios/<string:clave>/llamadas", methods=["GET"])
@validar_token
@requiere_permiso("integraciones.ver")
def llamadas_servicio(clave):
    """
    Últimas llamadas de un servicio, con su detalle
    ---
    tags:
      - Integraciones
    security:
      - BearerAuth: []
    description: >
      A dónde se hizo cada llamada, qué se envió (encabezados sin la clave, parámetros y cuerpo) y
      qué se respondió. Los datos personales quedan enmascarados (DPI con sus últimos 4 dígitos,
      nombres como iniciales). Las llamadas de antes de guardar el detalle solo traen el resumen.
    parameters:
      - name: clave
        in: path
        type: string
        required: true
      - name: limite
        in: query
        type: integer
        default: 10
    responses:
      200:
        description: Servicio y sus llamadas, de la más reciente a la más antigua
      404:
        description: No existe ese servicio
    """
    servicio = next((s for s in SERVICIOS if s["clave"] == clave), None)
    if not servicio:
        return jsonify(success=False, error="no_encontrado", message="No existe ese servicio"), 404
    try:
        limite = max(1, min(int(request.args.get("limite", 10)), 50))
    except ValueError:
        limite = 10
    llamadas = _llamadas_de(servicio).order_by(BitacoraIntegracion.id.desc()).limit(limite).all()
    return jsonify(success=True, data={
        "servicio": {k: servicio.get(k) for k in ("clave", "direccion", "modulo", "codigo", "nombre", "metodo", "ruta", "donde")},
        "llamadas": [{
            **_registro(b), "id": b.id, "operacion": b.operacion, "metodo": b.metodo, "ruta": b.ruta,
            "url": b.url, "solicitud": _json(b.solicitud), "respuesta": _json(b.respuesta),
        } for b in llamadas],
    }), 200


@integraciones_bp.route("/api/v1/salud/integraciones/servicios", methods=["GET"])
@validar_token
@requiere_permiso("integraciones.ver")
def servicios_integracion():
    """
    Mapa de servicios entre Salud y los otros módulos, con la prueba de que funcionan
    ---
    tags:
      - Integraciones
    security:
      - BearerAuth: []
    description: >
      Cada servicio que Salud consume (saliente) o que otro módulo le consume (entrante), con la
      última respuesta válida (OK, o "no encontrado" cuando el dato no existe), la última llamada
      (aunque haya fallado) y cuántas hubo en 30 días,
      tomadas de la bitácora de integraciones. En producción no cuentan las pruebas ni simulaciones.
    responses:
      200:
        description: Lista de servicios
    """
    desde = datetime.now() - timedelta(days=30)
    datos = []
    for s in SERVICIOS:
        base = _llamadas_de(s)
        ultimo_ok = base.filter(BitacoraIntegracion.resultado.in_(RESPUESTAS_VALIDAS)).order_by(BitacoraIntegracion.id.desc()).first()
        ultimo = base.order_by(BitacoraIntegracion.id.desc()).first()
        recientes = base.filter(BitacoraIntegracion.fecha >= desde)
        ok_30 = recientes.filter(BitacoraIntegracion.resultado.in_(RESPUESTAS_VALIDAS)).count()
        datos.append({
            **{k: s.get(k) for k in ("clave", "direccion", "modulo", "codigo", "nombre", "metodo", "ruta", "donde", "conexion")},
            "ultimoOk": _registro(ultimo_ok), "ultimo": _registro(ultimo),
            "llamadasOk30": ok_30, "llamadasError30": recientes.count() - ok_30,
        })
    return jsonify(success=True, data=datos), 200


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
    if not Config.SIMULACIONES:
        return jsonify(success=False, error="no_disponible", message="Las demostraciones no están disponibles en este servidor"), 404
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
