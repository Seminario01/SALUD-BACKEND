"""
Constancias médicas: constancia de consulta e incapacidad (días de reposo).

El médico las emite (constancias.emitir); se imprimen en /imprimir/constancia/<id> con un QR que
cualquiera (un patrono, un colegio) escanea para comprobar en /verificar/constancia/<código> que
es auténtica y sigue vigente. La verificación pública no muestra el diagnóstico.
"""
from datetime import date, datetime, timedelta

from flask import Blueprint, g, jsonify, request

from auth import puede, requiere_permiso, tiene_rol, validar_token, ROL_JEFATURA
from extensions import db
from migraciones import codigo_receta
from models import ConstanciaMedica, ExpedienteClinico, Paciente
from routes.farmacia import CODIGO_QR, _demasiadas_consultas, _iniciales
from validacion import DatoInvalido, entero, opcion, texto

constancias_bp = Blueprint("constancias", __name__)
TIPOS = ("CONSULTA", "INCAPACIDAD")
MAX_DIAS_REPOSO = 60


def _error(status, codigo, mensaje):
    return jsonify(success=False, error=codigo, message=mensaje), status


def _fecha(data, campo, etiqueta, defecto):
    valor = texto(data, campo, 10, etiqueta=etiqueta)
    if valor is None:
        return defecto
    try:
        return date.fromisoformat(valor)
    except ValueError:
        raise DatoInvalido(f"{etiqueta} inválida (AAAA-MM-DD)")


def _constancia(c, paciente=None):
    return {
        "id": c.id, "paciente_id": c.paciente_id, "tipo": c.tipo, "expediente_id": c.expediente_id,
        "paciente": paciente.nombre_completo if paciente else None,
        "paciente_cui": paciente.cui if paciente else None,
        "paciente_fecha_nacimiento": str(paciente.fecha_nacimiento) if paciente and paciente.fecha_nacimiento else None,
        "medico_sub": c.medico_sub, "medico": c.medico_nombre,
        "fecha": c.fecha.isoformat(timespec="minutes"),
        "fecha_atencion": c.fecha_atencion.isoformat(), "diagnostico": c.diagnostico,
        "dias_reposo": c.dias_reposo, "desde": c.desde.isoformat() if c.desde else None,
        "hasta": c.hasta.isoformat() if c.hasta else None, "observaciones": c.observaciones,
        "estado": c.estado, "motivo_anulacion": c.motivo_anulacion, "codigo_verificacion": c.codigo_verificacion,
    }


def _paciente_propio():
    return Paciente.query.filter_by(usuario_sub=g.usuario["sub"]).first()


@constancias_bp.route("/api/v1/salud/constancias", methods=["POST"])
@validar_token
@requiere_permiso("constancias.emitir")
def crear_constancia():
    """
    Emitir una constancia de consulta o de incapacidad
    ---
    tags:
      - Constancias
    security:
      - BearerAuth: []
    parameters:
      - in: body
        name: body
        required: true
        schema:
          type: object
          required: [paciente_id, tipo]
          properties:
            paciente_id: {type: integer, example: 1}
            tipo: {type: string, enum: [CONSULTA, INCAPACIDAD]}
            expediente_id: {type: integer, description: "Atención del expediente (opcional; da la fecha de atención)"}
            fecha_atencion: {type: string, format: date, description: "Por defecto, hoy (o la de la atención)"}
            diagnostico: {type: string, description: "Solo si el médico decide que se imprima"}
            dias_reposo: {type: integer, description: "INCAPACIDAD: 1 a 60 días"}
            desde: {type: string, format: date, description: "INCAPACIDAD: primer día de reposo (por defecto, hoy)"}
            observaciones: {type: string, example: "Puede reincorporarse a sus labores el lunes."}
    responses:
      201:
        description: Constancia emitida a nombre del médico, con su código de verificación
      400:
        description: Datos inválidos
      404:
        description: El paciente no existe
    """
    data = request.get_json(silent=True) or {}
    tipo = opcion(data, "tipo", TIPOS, obligatorio=True, etiqueta="El tipo")
    paciente = Paciente.query.get(entero(data, "paciente_id", 1, 2**31 - 1, obligatorio=True, etiqueta="paciente_id"))
    if not paciente:
        return _error(404, "no_encontrado", "Paciente no existe")
    expediente_id = entero(data, "expediente_id", 1, 2**31 - 1, etiqueta="expediente_id")
    atencion = None
    if expediente_id:
        atencion = ExpedienteClinico.query.get(expediente_id)
        if not atencion or atencion.paciente_id != paciente.id:
            return _error(400, "datos_invalidos", "La atención no pertenece a este paciente")
    hoy = date.today()
    fecha_atencion = _fecha(data, "fecha_atencion", "La fecha de atención",
                            atencion.fecha_atencion.date() if atencion and atencion.fecha_atencion else hoy)
    if fecha_atencion > hoy or fecha_atencion < hoy - timedelta(days=365):
        return _error(400, "datos_invalidos", "La fecha de atención debe ser de hoy o del último año")

    dias = entero(data, "dias_reposo", 1, MAX_DIAS_REPOSO, etiqueta="Los días de reposo")
    desde = hasta = None
    if tipo == "INCAPACIDAD":
        if dias is None:
            return _error(400, "datos_invalidos", f"La incapacidad necesita los días de reposo (1 a {MAX_DIAS_REPOSO})")
        desde = _fecha(data, "desde", "La fecha de inicio del reposo", hoy)
        if not fecha_atencion <= desde <= hoy + timedelta(days=30):
            return _error(400, "datos_invalidos", "El reposo empieza el día de la atención o después (máximo en 30 días)")
        hasta = desde + timedelta(days=dias - 1)
    elif dias is not None or data.get("desde"):
        return _error(400, "datos_invalidos", "La constancia de consulta no lleva días de reposo")

    c = ConstanciaMedica(
        paciente_id=paciente.id, tipo=tipo, expediente_id=expediente_id, medico_sub=g.usuario["sub"],
        medico_nombre=g.usuario.get("nombre") or g.usuario.get("usuario"), fecha=datetime.now(),
        fecha_atencion=fecha_atencion, diagnostico=texto(data, "diagnostico", 300, etiqueta="El diagnóstico"),
        dias_reposo=dias if tipo == "INCAPACIDAD" else None, desde=desde, hasta=hasta,
        observaciones=texto(data, "observaciones", 500, etiqueta="Las observaciones"),
        estado="VIGENTE", codigo_verificacion=codigo_receta())
    db.session.add(c)
    db.session.commit()
    nombre = "Incapacidad" if tipo == "INCAPACIDAD" else "Constancia de consulta"
    return jsonify(success=True, data=_constancia(c, paciente), message=f"{nombre} No. {c.id} emitida"), 201


@constancias_bp.route("/api/v1/salud/constancias", methods=["GET"])
@validar_token
def listar_constancias():
    """
    Constancias emitidas
    ---
    tags:
      - Constancias
    security:
      - BearerAuth: []
    description: >
      Personal con constancias.ver: todas (filtro paciente_id). Ciudadano: solo las suyas.
    parameters:
      - {name: paciente_id, in: query, type: integer}
    responses:
      200:
        description: Las 200 más recientes
    """
    q = ConstanciaMedica.query
    if puede("constancias.ver"):
        pid = request.args.get("paciente_id", "")
        if pid:
            if not pid.isdigit():
                return _error(400, "datos_invalidos", "paciente_id debe ser un número")
            q = q.filter_by(paciente_id=int(pid))
    elif tiene_rol("ciudadano"):
        propio = _paciente_propio()
        if propio is None:
            return jsonify(success=True, data=[]), 200
        q = q.filter_by(paciente_id=propio.id)
    else:
        return _error(403, "sin_permiso", "No tiene permiso para ver constancias")
    lista = q.order_by(ConstanciaMedica.id.desc()).limit(200).all()
    ids = {c.paciente_id for c in lista}
    pacientes = {p.id: p for p in Paciente.query.filter(Paciente.id.in_(ids)).all()} if ids else {}
    return jsonify(success=True, data=[_constancia(c, pacientes.get(c.paciente_id)) for c in lista]), 200


@constancias_bp.route("/api/v1/salud/constancias/<int:id>", methods=["GET"])
@validar_token
def ver_constancia(id):
    """
    Una constancia, para verla o imprimirla
    ---
    tags:
      - Constancias
    security:
      - BearerAuth: []
    description: Personal con constancias.ver, o el ciudadano dueño (si no es suya, 404).
    parameters:
      - {name: id, in: path, type: integer, required: true}
    responses:
      200:
        description: La constancia
      404:
        description: No existe (o no es del ciudadano)
    """
    c = ConstanciaMedica.query.get(id)
    if c and not puede("constancias.ver"):
        propio = _paciente_propio() if tiene_rol("ciudadano") else None
        if propio is None or propio.id != c.paciente_id:
            if not tiene_rol("ciudadano"):
                return _error(403, "sin_permiso", "No tiene permiso para ver constancias")
            c = None
    if not c:
        return _error(404, "no_encontrado", "La constancia no existe")
    return jsonify(success=True, data=_constancia(c, Paciente.query.get(c.paciente_id))), 200


@constancias_bp.route("/api/v1/salud/constancias/<int:id>/anular", methods=["POST"])
@validar_token
@requiere_permiso("constancias.anular")
def anular_constancia(id):
    """
    Anular una constancia emitida por error
    ---
    tags:
      - Constancias
    security:
      - BearerAuth: []
    description: El médico solo anula las suyas; Jefatura, cualquiera. Al verificar el QR saldrá ANULADA.
    parameters:
      - {name: id, in: path, type: integer, required: true}
      - in: body
        name: body
        required: true
        schema:
          type: object
          required: [motivo]
          properties:
            motivo: {type: string, example: "Se emitió al paciente equivocado"}
    responses:
      200:
        description: Anulada
      403:
        description: No es suya (y no es Jefatura)
      404:
        description: No existe
      409:
        description: Ya estaba anulada
    """
    c = ConstanciaMedica.query.get(id)
    if not c:
        return _error(404, "no_encontrado", "La constancia no existe")
    if not tiene_rol(ROL_JEFATURA) and c.medico_sub != g.usuario["sub"]:
        return _error(403, "sin_permiso", "Solo el médico que la emitió o Jefatura pueden anularla")
    if c.estado == "ANULADA":
        return _error(409, "ya_anulada", "La constancia ya estaba anulada")
    c.motivo_anulacion = texto(request.get_json(silent=True) or {}, "motivo", 255, obligatorio=True, minimo=5,
                               etiqueta="El motivo")
    c.estado = "ANULADA"
    db.session.commit()
    return jsonify(success=True, data=_constancia(c, Paciente.query.get(c.paciente_id)),
                   message=f"Constancia No. {c.id} anulada"), 200


@constancias_bp.route("/api/v1/salud/verificar/constancia/<codigo>", methods=["GET"])
def verificar_constancia(codigo):
    """
    Verificar una constancia impresa por su código QR (público, sin token)
    ---
    tags:
      - Constancias
    description: >
      Para el patrono o el colegio que recibe la constancia: tipo, número, fechas, días de reposo,
      médico y si está vigente o anulada. Sin diagnóstico; del paciente solo las iniciales y los
      últimos 4 dígitos del DPI. 30 consultas por minuto por visitante.
    parameters:
      - {name: codigo, in: path, type: string, required: true}
    responses:
      200:
        description: Constancia auténtica
      404:
        description: El código no corresponde a ninguna constancia
      429:
        description: Demasiadas consultas seguidas
    """
    if _demasiadas_consultas():
        return _error(429, "demasiadas_peticiones", "Demasiadas consultas seguidas. Espere un minuto e intente de nuevo.")
    c = ConstanciaMedica.query.filter_by(codigo_verificacion=codigo).first() if CODIGO_QR.match(codigo) else None
    if c and c.codigo_verificacion != codigo:      # exacto: MySQL no distingue mayúsculas
        c = None
    if not c:
        return _error(404, "no_encontrado", "Esta constancia no existe en el sistema del Módulo Salud. Puede ser falsa o el código estar alterado.")
    paciente = Paciente.query.get(c.paciente_id)
    cui = (paciente.cui or "") if paciente else ""
    return jsonify(success=True, data={
        "numero": c.id, "tipo": c.tipo, "estado": c.estado,
        "fecha": c.fecha.isoformat(timespec="minutes"), "fecha_atencion": c.fecha_atencion.isoformat(),
        "dias_reposo": c.dias_reposo, "desde": c.desde.isoformat() if c.desde else None,
        "hasta": c.hasta.isoformat() if c.hasta else None, "medico": c.medico_nombre,
        "paciente_iniciales": _iniciales(paciente.nombre_completo if paciente else None),
        "paciente_dpi": f"•••• {cui[-4:]}" if len(cui) >= 4 else None,
        "establecimiento": "Módulo Salud — Red Inteligente de Servicios Digitales",
    }), 200
