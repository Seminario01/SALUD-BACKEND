"""
Red de establecimientos y referencias de pacientes.

  GET  /establecimientos                 la red (filtros: departamento, nivel, tipo, q)      personal de Salud
  POST /establecimientos                 agregar uno (centro de salud, puesto...)            establecimientos.gestionar
  PUT  /establecimientos/<id>            dirección, teléfono, estado, tipo de atención        establecimientos.gestionar
  GET  /referencias                      referencias (filtro: estado)                         referencias.ver
  GET  /referencias/<id>                 una referencia (para la hoja impresa)                referencias.ver o el ciudadano dueño
  GET  /pacientes/<id>/referencias       las del paciente                                     referencias.ver o el ciudadano dueño
  POST /referencias                      referir a un paciente                                referencias.crear (Médico)
  PUT  /referencias/<id>                 marcar RECIBIDA o CANCELADA                          referencias.gestionar

La red trae los 45 hospitales públicos del MSPAS (establecimientos.py). WS-SALUD-02 (Seguridad) usa
esta misma tabla, así que lo que se edite aquí también lo ve Seguridad.
"""
from datetime import datetime, timedelta

from flask import Blueprint, g, jsonify, request

import cie10
import ubicaciones
from auth import es_personal, puede, requiere_permiso, validar_token
from establecimientos import RED, TIPOS
from extensions import db
from models import Establecimiento, Paciente, Referencia
from routes.externos import TIPOS_ATENCION
from routes.pacientes import puede_ver_paciente
from validacion import DatoInvalido, booleano, entero, opcion, telefono, texto

red_bp = Blueprint("red", __name__)
ESTADOS_SERVICIO = ("ACTIVO", "INACTIVO", "EN_MANTENIMIENTO")
PRIORIDADES = ("URGENTE", "NORMAL")
TIPOS_REFERENCIA = ("REFERENCIA", "CONTRARREFERENCIA")


def _error(status, codigo, mensaje):
    return jsonify(success=False, error=codigo, message=mensaje), status


def _yo():
    return (g.usuario.get("nombre") or g.usuario.get("usuario") or "")[:150] or None


def _establecimiento(e, enviadas=0):
    return {"id": e.id_establecimiento, "nombre": e.nombre, "tipo": e.tipo, "nivel": e.nivel,
            "departamento": e.departamento, "municipio": e.municipio, "codigo_municipio": e.codigo_municipio,
            "direccion": e.direccion, "telefono": e.telefono, "estado_servicio": e.estado_servicio,
            "tipo_atencion": [t for t in (e.tipo_atencion_disponible or "").split(",") if t], "fuente": e.fuente,
            "referencias_90_dias": enviadas, "es_sede": bool(e.es_sede)}


def _referencia(r, paciente=None):
    p = paciente or Paciente.query.get(r.paciente_id)
    e = r.establecimiento
    return {"id": r.id, "paciente_id": r.paciente_id, "paciente": p.nombre_completo if p else None,
            "cui": p.cui if p else None, "fecha_nacimiento": str(p.fecha_nacimiento) if p and p.fecha_nacimiento else None,
            "genero": p.genero if p else None, "alergias": p.alergias if p else None,
            "establecimiento_id": r.establecimiento_id, "establecimiento": e.nombre if e else None,
            "establecimiento_municipio": f"{e.municipio}, {e.departamento}" if e else None, "establecimiento_telefono": e.telefono if e else None,
            "tipo": r.tipo, "prioridad": r.prioridad, "motivo": r.motivo, "codigo_cie10": r.codigo_cie10, "diagnostico": r.diagnostico,
            "resumen": r.resumen, "estado": r.estado, "medico_nombre": r.medico_nombre, "fecha": r.fecha.isoformat(),
            "fecha_cierre": r.fecha_cierre.isoformat() if r.fecha_cierre else None, "cerrada_por": r.cerrada_por,
            "nota_cierre": r.nota_cierre}


# ---------------------------------------------------------------------------- red
@red_bp.route("/api/v1/salud/establecimientos", methods=["GET"])
@validar_token
def listar_establecimientos():
    """
    Red de establecimientos de salud (los 45 hospitales públicos del MSPAS y los que se agreguen)
    ---
    tags:
      - Red de establecimientos
    security:
      - BearerAuth: []
    parameters:
      - {name: departamento, in: query, type: string, description: "Código de 2 dígitos (13) o nombre"}
      - {name: nivel, in: query, type: string}
      - {name: tipo, in: query, type: string}
      - {name: q, in: query, type: string, description: "Parte del nombre o del municipio"}
    responses:
      200:
        description: "establecimientos, por_departamento y la fuente del catálogo"
      403:
        description: Solo personal de Salud
    """
    if not es_personal():
        return _error(403, "permiso_denegado", "Solo el personal de Salud consulta la red")
    query = Establecimiento.query
    depto = (request.args.get("departamento") or "").strip()
    if depto:
        if depto.isdigit():
            query = query.filter(Establecimiento.codigo_municipio.like(f"{depto.zfill(2)}%"))
        else:
            query = query.filter(Establecimiento.departamento == depto)
    if request.args.get("nivel"):
        query = query.filter(Establecimiento.nivel == request.args["nivel"])
    if request.args.get("tipo"):
        query = query.filter(Establecimiento.tipo == request.args["tipo"])
    q = (request.args.get("q") or "").strip()[:80]
    if q:
        query = query.filter(db.or_(Establecimiento.nombre.ilike(f"%{q}%"), Establecimiento.municipio.ilike(f"%{q}%")))
    lista = query.order_by(Establecimiento.departamento, Establecimiento.nombre).all()
    desde = datetime.now() - timedelta(days=90)
    conteo = dict(db.session.query(Referencia.establecimiento_id, db.func.count(Referencia.id))
                  .filter(Referencia.fecha >= desde, Referencia.tipo == "REFERENCIA").group_by(Referencia.establecimiento_id).all())
    por_depto = {}
    for e in lista:
        por_depto[e.departamento or "Sin departamento"] = por_depto.get(e.departamento or "Sin departamento", 0) + 1
    return jsonify(success=True, data={
        "establecimientos": [_establecimiento(e, conteo.get(e.id_establecimiento, 0)) for e in lista],
        "por_departamento": por_depto,
        "fuente": {"texto": RED["fuente"], "url": RED["url"], "nota": RED["nota"]},
        "tipos_atencion": list(TIPOS_ATENCION), "estados": list(ESTADOS_SERVICIO), "tipos": list(TIPOS),
    }), 200


def _datos_establecimiento(data, nuevo):
    cambios = {}
    if nuevo or "direccion" in data:
        cambios["direccion"] = texto(data, "direccion", 250, etiqueta="La dirección")
    if nuevo or "telefono" in data:
        cambios["telefono"] = telefono(data)
    if "estado_servicio" in data:
        cambios["estado_servicio"] = opcion(data, "estado_servicio", ESTADOS_SERVICIO, obligatorio=True, etiqueta="El estado")
    if nuevo or "tipo_atencion" in data:
        valor = data.get("tipo_atencion") or []
        if not isinstance(valor, list) or not all(isinstance(t, str) and t in TIPOS_ATENCION for t in valor):
            raise DatoInvalido(f"tipo_atencion es una lista con: {', '.join(TIPOS_ATENCION)}")
        cambios["tipo_atencion_disponible"] = ",".join(dict.fromkeys(valor)) or None
    if not nuevo and "es_sede" in data:
        cambios["es_sede"] = booleano(data, "es_sede")
    return cambios


@red_bp.route("/api/v1/salud/establecimientos", methods=["POST"])
@validar_token
@requiere_permiso("establecimientos.gestionar")
def crear_establecimiento():
    """
    Agregar un establecimiento a la red
    ---
    tags:
      - Red de establecimientos
    security:
      - BearerAuth: []
    parameters:
      - in: body
        name: body
        schema:
          type: object
          required: [nombre, tipo, codigo_municipio]
          properties:
            nombre: {type: string}
            tipo: {type: string, enum: [HOSPITAL, CENTRO_SALUD, PUESTO_SALUD, OTRO]}
            codigo_municipio: {type: string, example: "0301"}
            direccion: {type: string}
            telefono: {type: string}
            tipo_atencion: {type: array, items: {type: string}}
    responses:
      201:
        description: Agregado
      409:
        description: Ya hay uno con ese nombre
    """
    data = request.get_json(silent=True) or {}
    nombre = texto(data, "nombre", 150, obligatorio=True, minimo=5, etiqueta="El nombre")
    tipo = opcion(data, "tipo", TIPOS, obligatorio=True, etiqueta="El tipo")
    codigo = texto(data, "codigo_municipio", 4, obligatorio=True, etiqueta="El municipio")
    if not ubicaciones.municipio(codigo) or codigo.endswith("00"):
        return _error(400, "datos_invalidos", "El municipio debe ser un código del INE de 4 dígitos, por ejemplo 0301")
    if Establecimiento.query.filter(db.func.lower(Establecimiento.nombre) == nombre.lower()).first():
        return _error(409, "ya_existe", "Ya hay un establecimiento con ese nombre")
    e = Establecimiento(nombre=nombre, tipo=tipo, codigo_municipio=codigo, municipio=ubicaciones.nombre_municipio(codigo),
                        departamento=ubicaciones.nombre_departamento(codigo), estado_servicio="ACTIVO",
                        fuente=f"Agregado por {_yo() or 'Administración'}", **_datos_establecimiento(data, True))
    db.session.add(e)
    db.session.commit()
    return jsonify(success=True, data=_establecimiento(e), message="Establecimiento agregado"), 201


@red_bp.route("/api/v1/salud/establecimientos/<int:id>", methods=["PUT"])
@validar_token
@requiere_permiso("establecimientos.gestionar")
def editar_establecimiento(id):
    """
    Completar o corregir un establecimiento (dirección, teléfono, estado, tipo de atención)
    ---
    tags:
      - Red de establecimientos
    security:
      - BearerAuth: []
    parameters:
      - {name: id, in: path, type: integer, required: true}
      - in: body
        name: body
        schema:
          type: object
          properties:
            direccion: {type: string}
            telefono: {type: string}
            estado_servicio: {type: string, enum: [ACTIVO, INACTIVO, EN_MANTENIMIENTO]}
            tipo_atencion: {type: array, items: {type: string}}
            es_sede: {type: boolean, description: "Sede de este sistema (turnos, camas y recursos propios)"}
    responses:
      200:
        description: Guardado
      404:
        description: No existe
      409:
        description: No se puede quitar la sede (es la principal o tiene personal o camas)
    """
    e = Establecimiento.query.get(id)
    if not e:
        return _error(404, "no_encontrado", "El establecimiento no existe")
    cambios = _datos_establecimiento(request.get_json(silent=True) or {}, False)
    if not cambios:
        return _error(400, "datos_incompletos", "No hay nada que cambiar")
    if cambios.get("es_sede") is False and e.es_sede:
        from models import Cama, SedeUsuario
        from sedes import principal_id
        if e.id_establecimiento == principal_id():
            return _error(409, "sede_principal", "Es la sede principal: no se puede quitar")
        if SedeUsuario.query.filter_by(sede_id=e.id_establecimiento).first() or Cama.query.filter_by(sede_id=e.id_establecimiento).first():
            return _error(409, "sede_en_uso", "La sede tiene personal o camas: cámbielos de sede primero")
    for campo, valor in cambios.items():
        setattr(e, campo, valor)
    db.session.commit()
    return jsonify(success=True, data=_establecimiento(e), message="Establecimiento actualizado"), 200


# ---------------------------------------------------------------------------- referencias
@red_bp.route("/api/v1/salud/referencias", methods=["GET"])
@validar_token
@requiere_permiso("referencias.ver")
def listar_referencias():
    """
    Referencias de pacientes a otros establecimientos
    ---
    tags:
      - Referencias
    security:
      - BearerAuth: []
    parameters:
      - {name: estado, in: query, type: string, enum: [ENVIADA, RECIBIDA, CANCELADA]}
      - {name: limite, in: query, type: integer, default: 100}
    responses:
      200:
        description: Primero las urgentes y las más recientes
    """
    query = Referencia.query
    if request.args.get("estado"):
        query = query.filter(Referencia.estado == request.args["estado"].upper())
    limite = max(1, min(request.args.get("limite", 100, type=int) or 100, 500))
    filas = query.order_by(db.case((Referencia.estado == "ENVIADA", 0), else_=1), db.case((Referencia.prioridad == "URGENTE", 0), else_=1),
                           Referencia.fecha.desc()).limit(limite).all()
    return jsonify(success=True, data=[_referencia(r) for r in filas]), 200


@red_bp.route("/api/v1/salud/referencias/<int:id>", methods=["GET"])
@validar_token
def ver_referencia(id):
    """
    Una referencia (con los datos para la hoja impresa)
    ---
    tags:
      - Referencias
    security:
      - BearerAuth: []
    parameters:
      - {name: id, in: path, type: integer, required: true}
    responses:
      200:
        description: La referencia
      403:
        description: Sin permiso
      404:
        description: No existe
    """
    r = Referencia.query.get(id)
    paciente = Paciente.query.get(r.paciente_id) if r else None
    if not (puede("referencias.ver") or (paciente and paciente.usuario_sub == g.usuario["sub"])):
        return _error(403, "permiso_denegado", "Sin permiso para ver esta referencia")
    if not r:
        return _error(404, "no_encontrado", "La referencia no existe")
    return jsonify(success=True, data=_referencia(r, paciente)), 200


@red_bp.route("/api/v1/salud/pacientes/<int:id>/referencias", methods=["GET"])
@validar_token
def referencias_paciente(id):
    """
    Referencias de un paciente
    ---
    tags:
      - Referencias
    security:
      - BearerAuth: []
    parameters:
      - {name: id, in: path, type: integer, required: true}
    responses:
      200:
        description: La más reciente primero
    """
    paciente = Paciente.query.get(id)
    if not (puede("referencias.ver") or (paciente and paciente.usuario_sub == g.usuario["sub"])):
        return _error(403, "permiso_denegado", "Sin permiso para ver estas referencias")
    if not paciente:
        return _error(404, "no_encontrado", "Paciente no existe")
    filas = Referencia.query.filter_by(paciente_id=id).order_by(Referencia.fecha.desc()).all()
    return jsonify(success=True, data=[_referencia(r, paciente) for r in filas]), 200


@red_bp.route("/api/v1/salud/referencias", methods=["POST"])
@validar_token
@requiere_permiso("referencias.crear")
def crear_referencia():
    """
    Referir a un paciente a otro establecimiento de la red
    ---
    tags:
      - Referencias
    security:
      - BearerAuth: []
    parameters:
      - in: body
        name: body
        schema:
          type: object
          required: [paciente_id, establecimiento_id, motivo]
          properties:
            paciente_id: {type: integer}
            establecimiento_id: {type: integer}
            tipo: {type: string, enum: [REFERENCIA, CONTRARREFERENCIA], default: REFERENCIA}
            prioridad: {type: string, enum: [URGENTE, NORMAL], default: NORMAL}
            motivo: {type: string, example: "Requiere valoración por cirugía pediátrica"}
            codigo_cie10: {type: string, example: "K35.8"}
            diagnostico: {type: string}
            resumen: {type: string, description: "Resumen clínico para quien recibe"}
    responses:
      201:
        description: Referencia enviada
      400:
        description: Datos inválidos
      404:
        description: El paciente o el establecimiento no existe
      409:
        description: El establecimiento no está activo
    """
    data = request.get_json(silent=True) or {}
    paciente_id = entero(data, "paciente_id", 1, 2_147_483_647, obligatorio=True, etiqueta="El paciente")
    destino_id = entero(data, "establecimiento_id", 1, 2_147_483_647, obligatorio=True, etiqueta="El establecimiento")
    tipo = opcion(data, "tipo", TIPOS_REFERENCIA, etiqueta="El tipo") or "REFERENCIA"
    prioridad = opcion(data, "prioridad", PRIORIDADES, etiqueta="La prioridad") or "NORMAL"
    motivo = texto(data, "motivo", 500, obligatorio=True, minimo=5, etiqueta="El motivo")
    resumen = texto(data, "resumen", 4000, etiqueta="El resumen clínico")
    diagnostico = texto(data, "diagnostico", 255, etiqueta="El diagnóstico")
    codigo = texto(data, "codigo_cie10", 8, etiqueta="El código CIE-10")
    if codigo:
        codigo = cie10.normalizar_codigo(codigo)
        if not cie10.descripcion(codigo):
            return _error(400, "datos_invalidos", "El código CIE-10 no está en el catálogo")
        diagnostico = diagnostico or cie10.descripcion(codigo)
    paciente = Paciente.query.get(paciente_id)
    if not paciente:
        return _error(404, "no_encontrado", "Paciente no existe")
    destino = Establecimiento.query.get(destino_id)
    if not destino:
        return _error(404, "no_encontrado", "El establecimiento no existe")
    if destino.estado_servicio != "ACTIVO":
        return _error(409, "establecimiento_inactivo", f"{destino.nombre} no está activo ({destino.estado_servicio})")
    r = Referencia(paciente_id=paciente_id, establecimiento_id=destino_id, tipo=tipo, prioridad=prioridad, motivo=motivo,
                   codigo_cie10=codigo, diagnostico=diagnostico, resumen=resumen, estado="ENVIADA",
                   medico_sub=g.usuario["sub"], medico_nombre=_yo(), fecha=datetime.now())
    db.session.add(r)
    db.session.commit()
    return jsonify(success=True, data=_referencia(r, paciente),
                   message=f"Referencia a {destino.nombre} registrada{'. Coordine el traslado urgente.' if prioridad == 'URGENTE' else ''}"), 201


@red_bp.route("/api/v1/salud/referencias/<int:id>", methods=["PUT"])
@validar_token
@requiere_permiso("referencias.gestionar")
def cerrar_referencia(id):
    """
    Marcar una referencia como RECIBIDA (el paciente llegó / fue aceptado) o CANCELADA
    ---
    tags:
      - Referencias
    security:
      - BearerAuth: []
    parameters:
      - {name: id, in: path, type: integer, required: true}
      - in: body
        name: body
        schema:
          type: object
          required: [estado]
          properties:
            estado: {type: string, enum: [RECIBIDA, CANCELADA]}
            nota: {type: string, description: "Obligatoria al cancelar"}
    responses:
      200:
        description: Actualizada
      409:
        description: Ya estaba cerrada
    """
    r = Referencia.query.get(id)
    if not r:
        return _error(404, "no_encontrado", "La referencia no existe")
    data = request.get_json(silent=True) or {}
    estado = opcion(data, "estado", ("RECIBIDA", "CANCELADA"), obligatorio=True, etiqueta="El estado")
    nota = texto(data, "nota", 500, etiqueta="La nota")
    if estado == "CANCELADA" and not nota:
        return _error(400, "datos_incompletos", "Escriba el motivo de la cancelación")
    if r.estado != "ENVIADA":
        return _error(409, "ya_cerrada", f"La referencia ya está {r.estado.lower()}")
    r.estado, r.nota_cierre, r.cerrada_por, r.fecha_cierre = estado, nota, _yo(), datetime.now()
    db.session.commit()
    return jsonify(success=True, data=_referencia(r), message=f"Referencia marcada como {estado.lower()}"), 200
