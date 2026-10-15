"""
Indicadores para el tablero de Auditoría Social (lo administra la ingeniera).

    GET /api/v1/salud/auditoria/indicadores?desde=YYYY-MM-DD&hasta=YYYY-MM-DD
    GET /api/indicadores  y  GET /api/v1/indicadores   (la misma consulta; ver RUTAS_ALIAS)

Solo datos AGREGADOS del rango pedido, nunca datos personales.
No reemplaza a GET /indicadores (routes/externos.py), que usan el panel y los otros módulos.

PROVISIONAL, a la espera de la respuesta de la ingeniera. Cada punto se cambia en un solo lugar:
  - la ruta ............................ RUTA y RUTAS_ALIAS
  - el rol ............................. ROLES_PERMITIDOS
  - el formato del cuerpo de error ..... cuerpo_error()
  - la forma de la respuesta 200 ....... cuerpo_ok()
  - el rango máximo de fechas .......... MAX_DIAS
"""
import logging
from datetime import date, datetime, timedelta

from flask import Blueprint, jsonify, request
from extensions import db
from models import (
    Paciente, CitaMedica, ExpedienteClinico, Turno, Vacunacion, Hospitalizacion, MovimientoCuenta,
)
from auth import validar_token, requiere_rol, ROL_AUDITORIA_LECTURA

log = logging.getLogger(__name__)

auditoria_bp = Blueprint("auditoria", __name__)

RUTA = "/api/v1/salud/auditoria/indicadores"
# La especificación de Auditoría pide "GET /api/indicadores" y el estándar de contratos usa la
# base /api/v1: se publican las dos lecturas, mientras la ingeniera confirma cuál usará el
# tablero. Ninguna choca con /api/v1/salud/indicadores (otro formato, lo usan los otros módulos).
RUTAS_ALIAS = ("/api/indicadores", "/api/v1/indicadores")
ROLES_PERMITIDOS = (ROL_AUDITORIA_LECTURA,)
MAX_DIAS = 5 * 366
# Lista corta de unidades que acepta el tablero.
UNIDADES = ("citas", "personas", "casos", "dias", "porcentaje", "quetzales")


def cuerpo_error(codigo, mensaje):
    """Cuerpo uniforme de error que espera el tablero."""
    return {"error": codigo, "mensaje": mensaje}


def cuerpo_ok(desde, hasta, indicadores, series):
    return {
        "modulo": "salud",
        "desde": desde.isoformat(),
        "hasta": hasta.isoformat(),
        "indicadores": indicadores,
        "series": series,
    }


def _error(status, codigo, mensaje):
    return jsonify(success=False, error=codigo, message=mensaje), status


@auditoria_bp.after_request
def _errores_uniformes(respuesta):
    """Todos los errores de este blueprint (también los 401/403 de auth.py y el 500
    de app.py) salen con el mismo cuerpo."""
    if respuesta.status_code >= 400:
        cuerpo = respuesta.get_json(silent=True) or {}
        respuesta.data = jsonify(cuerpo_error(cuerpo.get("error") or f"error_{respuesta.status_code}",
                                              cuerpo.get("message") or "No se pudo completar la solicitud")).data
    return respuesta


def _fecha(nombre):
    """(fecha, None) o (None, respuesta 400)."""
    texto = (request.args.get(nombre) or "").strip()
    if not texto:
        return None, _error(400, "parametro_faltante", f"Falta el parámetro {nombre} (formato YYYY-MM-DD)")
    try:
        # strptime acepta "2026-1-5"; se exige el formato exacto
        if len(texto) != 10:
            raise ValueError
        return datetime.strptime(texto, "%Y-%m-%d").date(), None
    except ValueError:
        return None, _error(400, "fecha_invalida", f"El parámetro {nombre} debe tener el formato YYYY-MM-DD")


def _entre(columna, desde, hasta):
    """Filtro de una columna de fecha y hora para el rango [desde, hasta], días completos."""
    inicio = datetime.combine(desde, datetime.min.time())
    return columna >= inicio, columna < inicio + timedelta(days=(hasta - desde).days + 1)


def _meses(desde, hasta):
    anio, mes = desde.year, desde.month
    while (anio, mes) <= (hasta.year, hasta.month):
        yield f"{anio:04d}-{mes:02d}"
        anio, mes = (anio + 1, 1) if mes == 12 else (anio, mes + 1)


def _serie_mensual(clave, etiqueta, unidad, columna, desde, hasta, *filtros):
    """Serie por mes (x = YYYY-MM). Los meses sin datos van con valor 0."""
    mes = db.func.date_format(columna, "%Y-%m")
    conteo = dict(db.session.query(mes, db.func.count()).filter(*_entre(columna, desde, hasta), *filtros)
                  .group_by(mes).all())
    return {"clave": clave, "etiqueta": etiqueta, "unidad": unidad,
            "puntos": [{"x": m, "valor": int(conteo.get(m, 0))} for m in _meses(desde, hasta)]}


def _indicador(clave, etiqueta, valor, unidad):
    assert unidad in UNIDADES, unidad
    return {"clave": clave, "etiqueta": etiqueta, "valor": valor, "unidad": unidad}


def calcular(desde, hasta):
    citas = CitaMedica.query.filter(*_entre(CitaMedica.fecha_hora, desde, hasta))
    pacientes_atendidos = db.session.query(db.func.count(db.func.distinct(ExpedienteClinico.paciente_id))) \
        .filter(*_entre(ExpedienteClinico.fecha_atencion, desde, hasta)).scalar()
    egresos = Hospitalizacion.query.filter(Hospitalizacion.estado == "EGRESADO",
                                           *_entre(Hospitalizacion.fecha_egreso, desde, hasta)).all()
    dias_estancia = [(h.fecha_egreso - (h.fecha_asignacion or h.fecha_ingreso)).total_seconds() / 86400
                     for h in egresos]
    cobrado = db.session.query(db.func.coalesce(db.func.sum(MovimientoCuenta.monto), 0)) \
        .filter(MovimientoCuenta.tipo == "PAGO", MovimientoCuenta.anulado.is_(False),
                *_entre(MovimientoCuenta.fecha, desde, hasta)).scalar()

    indicadores = [
        _indicador("citas_agendadas", "Citas agendadas", citas.count(), "citas"),
        _indicador("citas_atendidas", "Citas atendidas", citas.filter_by(estado="atendida").count(), "citas"),
        _indicador("citas_canceladas", "Citas canceladas", citas.filter_by(estado="cancelada").count(), "citas"),
        _indicador("pacientes_registrados", "Pacientes registrados",
                   Paciente.query.filter(*_entre(Paciente.fecha_registro, desde, hasta)).count(), "personas"),
        _indicador("pacientes_atendidos", "Pacientes atendidos", int(pacientes_atendidos or 0), "personas"),
        _indicador("esquemas_vacunacion_completos", "Personas con esquema de vacunación completo",
                   Vacunacion.query.filter(Vacunacion.esquema_completo.is_(True),
                                           *_entre(Vacunacion.fecha_actualizacion, desde, hasta)).count(), "personas"),
        _indicador("emergencias_atendidas", "Emergencias atendidas",
                   Turno.query.filter(Turno.tipo_atencion == "emergencia", Turno.estado == "atendido",
                                      *_entre(Turno.fecha_hora_ingreso, desde, hasta)).count(), "casos"),
        _indicador("ingresos_hospitalarios", "Ingresos hospitalarios",
                   Hospitalizacion.query.filter(Hospitalizacion.estado.in_(("ACTIVO", "EGRESADO")),
                                                *_entre(Hospitalizacion.fecha_ingreso, desde, hasta)).count(), "casos"),
        _indicador("egresos_hospitalarios", "Egresos hospitalarios", len(egresos), "casos"),
        _indicador("estancia_promedio", "Estancia hospitalaria promedio",
                   round(sum(dias_estancia) / len(dias_estancia), 1) if dias_estancia else 0, "dias"),
        _indicador("monto_cobrado_cuentas", "Monto cobrado en cuentas de pacientes", float(cobrado or 0), "quetzales"),
    ]
    series = [
        _serie_mensual("citas_atendidas", "Citas atendidas por mes", "citas", CitaMedica.fecha_hora, desde, hasta,
                       CitaMedica.estado == "atendida"),
        _serie_mensual("pacientes_registrados", "Pacientes registrados por mes", "personas",
                       Paciente.fecha_registro, desde, hasta),
    ]
    return indicadores, series


@auditoria_bp.route(RUTAS_ALIAS[1], methods=["GET"])
@auditoria_bp.route(RUTAS_ALIAS[0], methods=["GET"])
@auditoria_bp.route(RUTA, methods=["GET"])
@validar_token
@requiere_rol(*ROLES_PERMITIDOS)
def indicadores_auditoria():
    """
    Indicadores de Salud para el tablero de Auditoría Social
    ---
    tags:
      - Auditoría Social
    description: >
      Datos agregados del rango de fechas (sin datos personales). Requiere el
      token de un usuario con el rol auditoria:lectura.
    security:
      - BearerAuth: []
    parameters:
      - in: query
        name: desde
        type: string
        required: true
        description: YYYY-MM-DD
      - in: query
        name: hasta
        type: string
        required: true
        description: YYYY-MM-DD
    responses:
      200:
        description: "indicadores (clave, etiqueta, valor, unidad) y series (x, valor)"
      400:
        description: Faltan desde o hasta, el formato no es YYYY-MM-DD o el rango no es válido
      401:
        description: Sin token o token inválido
      403:
        description: El token no tiene el rol auditoria:lectura
      500:
        description: Error del módulo
    """
    desde, error = _fecha("desde")
    if error:
        return error
    hasta, error = _fecha("hasta")
    if error:
        return error
    if hasta < desde:
        return _error(400, "rango_invalido", "El parámetro hasta es anterior a desde")
    if (hasta - desde).days > MAX_DIAS:
        return _error(400, "rango_invalido", "El rango entre desde y hasta no puede pasar de 5 años")

    try:
        indicadores, series = calcular(desde, hasta)
    except Exception:  # noqa: BLE001
        # La traza queda solo en el log del servidor, nunca en la respuesta.
        log.exception("Error al calcular los indicadores de Auditoría")
        db.session.rollback()
        return _error(500, "error_interno", "Error interno del Módulo de Salud. Intente de nuevo más tarde.")
    return jsonify(cuerpo_ok(desde, hasta, indicadores, series)), 200
