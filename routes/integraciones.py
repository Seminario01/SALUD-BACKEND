"""
Integración con los otros módulos (Salud CONSUME sus servicios).

El frontend nunca llama directo a otro módulo: pide aquí, con el token del
usuario, y el backend de Salud llama al módulo destino (servidor a servidor).
Si el otro módulo no está configurado o no responde, se devuelve un error
claro (503) y la operación propia de Salud no se ve afectada.
"""
from flask import Blueprint, jsonify

from auth import validar_token, requiere_rol, ROL_ADMIN, ROL_MEDICO, ROL_RECEPCION
from config import Config
from extensions import db
from models import CitaMedica, Paciente
from services_externos import (
    consultar_antecedentes_seguridad,
    generar_numero_referencia_pago,
    obtener_estudiante,
    obtener_indicadores_educacion,
    obtener_indicadores_seguridad,
    obtener_indicadores_tributario,
    verificar_pago_tributario,
)

integraciones_bp = Blueprint("integraciones", __name__)

PERSONAL = (ROL_ADMIN, ROL_MEDICO, ROL_RECEPCION)

MENSAJES = {
    "no_configurado": "El módulo {m} no está configurado (falta su URL en el .env del backend).",
    "modulo_no_disponible": "El módulo {m} no está disponible en este momento. Intente más tarde.",
    "respuesta_invalida": "El módulo {m} respondió con un formato inesperado.",
}


def _error_modulo(resultado, modulo):
    codigo = resultado.get("error", "modulo_no_disponible")
    status = 502 if codigo == "respuesta_invalida" else 503
    return jsonify(success=False, error=codigo, modulo=modulo,
                   message=MENSAJES.get(codigo, MENSAJES["modulo_no_disponible"]).format(m=modulo)), status


@integraciones_bp.route("/api/v1/salud/integraciones/estado", methods=["GET"])
@validar_token
@requiere_rol(*PERSONAL)
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
        r = ping()
        if r["success"] or r.get("error") == "no_encontrado":
            datos = r.get("data") if isinstance(r.get("data"), dict) else {}
            estado[nombre] = {"estado": "conectado", "simulado": bool(datos.get("simulado"))}
        elif r.get("error") == "no_configurado":
            estado[nombre] = {"estado": "no_configurado", "simulado": False}
        else:
            estado[nombre] = {"estado": "no_disponible", "simulado": False}
    return jsonify(success=True, data=estado), 200


@integraciones_bp.route("/api/v1/salud/pacientes/<int:id>/antecedentes", methods=["GET"])
@validar_token
@requiere_rol(*PERSONAL)
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
@requiere_rol(ROL_ADMIN, ROL_MEDICO)
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


@integraciones_bp.route("/api/v1/salud/citas/<int:id>/verificar-pago", methods=["POST"])
@validar_token
@requiere_rol(*PERSONAL)
def verificar_pago_cita(id):
    """
    WS-SALUD-09 - Verificar en Tributario el pago de una cita
    ---
    tags:
      - Integraciones
    security:
      - BearerAuth: []
    parameters:
      - name: id
        in: path
        type: integer
        required: true
    responses:
      200:
        description: "pagoConfirmado true/false; si es true, la cita queda marcada como pagada"
      503:
        description: Tributario no configurado o no disponible
    """
    cita = CitaMedica.query.get(id)
    if not cita:
        return jsonify(success=False, error="no_encontrado", message="Cita no existe"), 404
    paciente = Paciente.query.get(cita.paciente_id)
    if not paciente or not paciente.cui:
        return jsonify(success=False, error="datos_incompletos",
                       message="El paciente no tiene CUI registrado; Tributario lo necesita"), 400

    monto = float(cita.costo) if cita.costo else Config.COSTO_CONSULTA
    referencia = generar_numero_referencia_pago()
    r = verificar_pago_tributario(referencia, paciente.cui, "CONSULTA_MEDICA", monto, "PENDIENTE_VERIFICACION")
    if not r["success"]:
        return _error_modulo(r, "Tributario")

    datos = r["data"] if isinstance(r["data"], dict) else {}
    estado = str(datos.get("estado") or datos.get("estadoPago") or datos.get("estado_pago") or "").upper()
    confirmado = bool(datos.get("pagoConfirmado") or datos.get("confirmado")) or estado in ("CONFIRMADO", "PAGADO", "APROBADO")
    if confirmado:
        cita.pago_confirmado = True
        cita.costo = monto
        db.session.commit()
    return jsonify(success=True, data={
        "pagoConfirmado": confirmado,
        "numeroReferencia": referencia,
        "monto": monto,
        "respuestaTributario": datos,
    }), 200
