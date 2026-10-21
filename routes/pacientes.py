from datetime import date, datetime, timedelta
from flask import Blueprint, request, jsonify, g
from extensions import db
from models import ExpedienteClinico, Paciente
from auth import validar_token, requiere_permiso, puede
from validacion import DatoInvalido, cui, fecha_pasada, opcion, telefono, texto
from alertas_clinicas import parecido_nombre
import ubicaciones

GENEROS = ("M", "F", "Otro")
SEGUROS = ("IGSS", "Privado", "Ninguno")

pacientes_bp = Blueprint("pacientes", __name__)


def puede_ver_paciente(paciente):
    """OWASP API1 (BOLA): el personal de Salud ve a cualquier paciente; un
    ciudadano solo el registro vinculado a su propio `sub`."""
    if puede("pacientes.ver"):
        return True
    return paciente is not None and paciente.usuario_sub == g.usuario["sub"]


def _validar(data, actual=None):
    """Valida los campos de paciente que vienen en `data` y devuelve solo esos,
    ya limpios. Con `actual` (edición), un valor que no cambió no se vuelve a
    validar: así los registros antiguos se pueden editar aunque no cumplan el formato."""
    reglas = {
        "nombre_completo": lambda: texto(data, "nombre_completo", 200, obligatorio=True, minimo=3,
                                         etiqueta="nombre_completo"),
        "cui": lambda: cui(data),
        "fecha_nacimiento": lambda: fecha_pasada(data, "fecha_nacimiento"),
        "genero": lambda: opcion(data, "genero", GENEROS),
        "telefono": lambda: telefono(data),
        "tipo_seguro": lambda: opcion(data, "tipo_seguro", SEGUROS),
        "cuidador": lambda: texto(data, "cuidador", 200, etiqueta="cuidador"),
        "alergias": lambda: texto(data, "alergias", 500, etiqueta="Las alergias"),
        "municipio": lambda: _municipio(data),
        "zona": lambda: texto(data, "zona", 120, etiqueta="La zona o aldea"),
    }
    limpio = {}
    for campo, regla in reglas.items():
        if campo not in data:
            continue
        if actual is not None and data[campo] == getattr(actual, campo):
            continue   # sin cambios
        limpio[campo] = regla()
    if limpio.get("cui"):
        otro = Paciente.query.filter(Paciente.cui == limpio["cui"])
        if actual is not None:
            otro = otro.filter(Paciente.id != actual.id)
        if otro.first():
            raise DatoInvalido("Ya hay un paciente registrado con ese CUI", status=409)
    return limpio


def _sub(data):
    """`sub` del ciudadano en el Login Único (36 caracteres) o None."""
    sub = texto(data, "usuario_sub", 36, etiqueta="El código de usuario")
    if sub and len(sub) != 36:
        raise DatoInvalido("El código de usuario debe tener 36 caracteres (el que ve el ciudadano en 'Mi resumen')")
    return sub


def _municipio(data):
    """Código del INE del municipio de residencia (4 dígitos, de ubicaciones.py)."""
    valor = texto(data, "municipio", 4, etiqueta="El municipio")
    if valor is not None and not ubicaciones.municipio(valor):
        raise DatoInvalido("El municipio no existe (use el código del INE, por ejemplo 0115 para Villa Nueva)")
    return valor


def serializar_paciente(p):
    return {
        "id": p.id,
        "cui": p.cui,
        "nombre_completo": p.nombre_completo,
        "fecha_nacimiento": str(p.fecha_nacimiento) if p.fecha_nacimiento else None,
        "genero": p.genero,
        "telefono": p.telefono,
        "tipo_seguro": p.tipo_seguro,
        "cuidador": p.cuidador,
        "alergias": p.alergias,
        "municipio": p.municipio,
        "municipio_nombre": ubicaciones.nombre_municipio(p.municipio),
        "departamento": p.municipio[:2] if p.municipio else None,
        "departamento_nombre": ubicaciones.nombre_departamento(p.municipio) if p.municipio else None,
        "zona": p.zona,
        "tiene_cuenta": p.usuario_sub is not None,
    }


@pacientes_bp.route("/api/v1/salud/pacientes", methods=["GET"])
@validar_token
@requiere_permiso("pacientes.ver")
def listar_pacientes():
    """
    Listar pacientes (solo personal de Salud)
    ---
    tags:
      - Pacientes
    security:
      - BearerAuth: []
    parameters:
      - name: q
        in: query
        type: string
        required: false
        description: Buscar por nombre o CUI
    responses:
      200:
        description: Lista de pacientes
      401:
        description: Sin token o token inválido
      403:
        description: El usuario no es personal de Salud
    """
    query = Paciente.query
    q = request.args.get("q", "").strip()
    if q:
        like = f"%{q}%"
        query = query.filter(db.or_(Paciente.nombre_completo.like(like), Paciente.cui.like(like)))
    pacientes = query.order_by(Paciente.nombre_completo).all()
    return jsonify(success=True, data=[serializar_paciente(p) for p in pacientes]), 200


@pacientes_bp.route("/api/v1/salud/pacientes/me", methods=["GET"])
@validar_token
def mi_registro():
    """
    Registro de paciente del usuario autenticado (ciudadano)
    ---
    tags:
      - Pacientes
    security:
      - BearerAuth: []
    responses:
      200:
        description: Registro propio
      404:
        description: El usuario no tiene registro de paciente vinculado
    """
    paciente = Paciente.query.filter_by(usuario_sub=g.usuario["sub"]).first()
    if not paciente:
        # Se devuelve su código (sub) para que recepción pueda vincularlo
        return jsonify(success=False, error="no_vinculado", sub=g.usuario["sub"],
                       message="No tiene un registro de paciente vinculado"), 404
    return jsonify(success=True, data=serializar_paciente(paciente)), 200


@pacientes_bp.route("/api/v1/salud/pacientes", methods=["POST"])
@validar_token
@requiere_permiso("pacientes.registrar")
def crear_paciente():
    """
    Registrar paciente
    ---
    tags:
      - Pacientes
    security:
      - BearerAuth: []
    parameters:
      - name: body
        in: body
        required: true
        schema:
          type: object
          required: [nombre_completo]
          properties:
            cui: {type: string, description: "13 dígitos, único"}
            nombre_completo: {type: string, description: "3 a 200 caracteres"}
            fecha_nacimiento: {type: string, example: "2000-01-15", description: "no puede estar en el futuro"}
            genero: {type: string, enum: [M, F, Otro]}
            telefono: {type: string, description: "8 a 15 dígitos"}
            tipo_seguro: {type: string, enum: [IGSS, Privado, Ninguno]}
            cuidador: {type: string}
            alergias: {type: string, example: "Penicilina, AINE", description: "texto libre, se revisa al recetar"}
            usuario_sub:
              type: string
              description: sub del ciudadano en el Login Único (opcional)
    responses:
      201:
        description: Paciente registrado
      400:
        description: Algún campo no cumple el formato
      409:
        description: Ya hay un paciente con ese CUI
    """
    data = request.get_json(silent=True) or {}
    if "nombre_completo" not in data:
        data["nombre_completo"] = None
    campos = _validar(data)
    paciente = Paciente(**campos, usuario_sub=_sub(data))
    db.session.add(paciente)
    db.session.commit()
    return jsonify(success=True, data={"id": paciente.id}, message="Paciente registrado"), 201


@pacientes_bp.route("/api/v1/salud/pacientes/sin-residencia", methods=["GET"])
@validar_token
@requiere_permiso("pacientes.registrar")
def pacientes_sin_residencia():
    """
    Pacientes sin municipio de residencia (para completarlos y que entren al mapa de vigilancia)
    ---
    tags:
      - Pacientes
    security:
      - BearerAuth: []
    description: >
      Primero los que tuvieron atenciones en los últimos 90 días (son los que cuentan en el mapa).
      Cada uno trae el municipio sugerido por su DPI (donde se inscribió: hay que confirmar que vive ahí).
    parameters:
      - {name: limite, in: query, type: integer, default: 100, description: "1 a 500"}
    responses:
      200:
        description: "total y data [{id, nombre_completo, cui, fecha_nacimiento, telefono, atenciones_recientes, ultima_atencion, sugerido}]"
    """
    limite = request.args.get("limite", "100")
    if not limite.isdigit() or not 1 <= int(limite) <= 500:
        return jsonify(success=False, error="datos_invalidos", message="limite debe ser un número de 1 a 500"), 400
    desde = datetime.now() - timedelta(days=90)
    recientes = dict(db.session.query(ExpedienteClinico.paciente_id, db.func.count())
                     .filter(ExpedienteClinico.fecha_atencion >= desde).group_by(ExpedienteClinico.paciente_id).all())
    ultimas = dict(db.session.query(ExpedienteClinico.paciente_id, db.func.max(ExpedienteClinico.fecha_atencion))
                   .group_by(ExpedienteClinico.paciente_id).all())
    sin = Paciente.query.filter(db.or_(Paciente.municipio.is_(None), Paciente.municipio == "")).all()
    sin.sort(key=lambda p: (-recientes.get(p.id, 0), -(ultimas[p.id].timestamp() if ultimas.get(p.id) else 0), p.nombre_completo))

    def sugerido(p):
        codigo = ubicaciones.desde_cui(p.cui)
        return {"codigo": codigo, "nombre": ubicaciones.nombre_municipio(codigo),
                "departamento": codigo[:2], "departamento_nombre": ubicaciones.nombre_departamento(codigo)} if codigo else None
    return jsonify(success=True, total=len(sin), data=[{
        "id": p.id, "nombre_completo": p.nombre_completo, "cui": p.cui, "telefono": p.telefono,
        "fecha_nacimiento": str(p.fecha_nacimiento) if p.fecha_nacimiento else None,
        "atenciones_recientes": recientes.get(p.id, 0),
        "ultima_atencion": ultimas[p.id].isoformat(timespec="minutes") if ultimas.get(p.id) else None,
        "sugerido": sugerido(p),
    } for p in sin[:int(limite)]]), 200


@pacientes_bp.route("/api/v1/salud/pacientes/posibles-duplicados", methods=["GET"])
@validar_token
@requiere_permiso("pacientes.registrar")
def posibles_duplicados():
    """
    Pacientes parecidos al que se va a registrar (para no crearlo dos veces)
    ---
    tags:
      - Pacientes
    security:
      - BearerAuth: []
    description: >
      Recepción lo consulta antes de registrar. Parecido = mismo CUI, o mismo nombre
      (sin importar tildes, mayúsculas ni el orden), o nombre parecido con la misma fecha de nacimiento.
    parameters:
      - {name: nombre_completo, in: query, type: string, required: true}
      - {name: fecha_nacimiento, in: query, type: string, required: false, description: "AAAA-MM-DD"}
      - {name: cui, in: query, type: string, required: false}
    responses:
      200:
        description: "Hasta 5 pacientes: [{id, nombre_completo, fecha_nacimiento, cui, motivo}]"
      400:
        description: Falta el nombre o la fecha no tiene formato AAAA-MM-DD
    """
    nombre = (request.args.get("nombre_completo") or "").strip()[:200]
    if len(nombre) < 3:
        return jsonify(success=False, error="datos_invalidos", message="Escriba el nombre (al menos 3 letras)"), 400
    nacimiento = None
    if request.args.get("fecha_nacimiento"):
        try:
            nacimiento = datetime.strptime(request.args["fecha_nacimiento"], "%Y-%m-%d").date()
        except ValueError:
            return jsonify(success=False, error="datos_invalidos", message="fecha_nacimiento con formato AAAA-MM-DD"), 400
    cui_buscado = "".join(c for c in (request.args.get("cui") or "") if c.isdigit())[:13]

    candidatos = {}
    if len(cui_buscado) == 13:
        for p in Paciente.query.filter(Paciente.cui == cui_buscado).limit(5):
            candidatos[p.id] = (p, "Mismo CUI", 2.0)
    filtro = [Paciente.fecha_nacimiento == nacimiento] if nacimiento else []
    # Para el mismo nombre sin fecha basta con revisar los que comparten alguna palabra larga
    palabras = sorted((w for w in nombre.split() if len(w) >= 3), key=len, reverse=True)[:3]
    if palabras:
        filtro.append(db.or_(*[Paciente.nombre_completo.like(f"%{w}%") for w in palabras]))
    if not filtro and not candidatos:
        return jsonify(success=True, data=[]), 200
    for p in (Paciente.query.filter(db.or_(*filtro)).limit(500) if filtro else []):
        if p.id in candidatos:
            continue
        parecido = parecido_nombre(nombre, p.nombre_completo)
        misma_fecha = nacimiento is not None and p.fecha_nacimiento == nacimiento
        if parecido == 1.0:
            candidatos[p.id] = (p, "Mismo nombre y fecha de nacimiento" if misma_fecha else "Mismo nombre", 1.5 if misma_fecha else 1.0)
        elif misma_fecha and parecido >= 0.85:
            candidatos[p.id] = (p, "Nombre parecido y misma fecha de nacimiento", parecido)
    mejores = sorted(candidatos.values(), key=lambda c: -c[2])[:5]
    return jsonify(success=True, data=[{
        "id": p.id, "nombre_completo": p.nombre_completo, "cui": p.cui,
        "fecha_nacimiento": str(p.fecha_nacimiento) if p.fecha_nacimiento else None, "motivo": motivo,
    } for p, motivo, _ in mejores]), 200


@pacientes_bp.route("/api/v1/salud/pacientes/<int:id>/alergias", methods=["PUT"])
@validar_token
@requiere_permiso("pacientes.alergias")
def actualizar_alergias(id):
    """
    Registrar o cambiar las alergias del paciente (Médico, Enfermería, Recepción)
    ---
    tags:
      - Pacientes
    security:
      - BearerAuth: []
    parameters:
      - {name: id, in: path, type: integer, required: true}
      - name: body
        in: body
        required: true
        schema:
          type: object
          properties:
            alergias: {type: string, example: "Penicilina, AINE", description: "vacío = sin alergias registradas"}
    responses:
      200:
        description: Alergias guardadas
      404:
        description: Paciente no existe
    """
    paciente = Paciente.query.get(id)
    if not paciente:
        return jsonify(success=False, error="no_encontrado", message="Paciente no existe"), 404
    data = request.get_json(silent=True) or {}
    paciente.alergias = texto(data, "alergias", 500, etiqueta="Las alergias")
    db.session.commit()
    return jsonify(success=True, data={"id": paciente.id, "alergias": paciente.alergias},
                   message="Alergias guardadas"), 200


@pacientes_bp.route("/api/v1/salud/pacientes/<int:id>", methods=["GET"])
@validar_token
def obtener_paciente(id):
    """
    Obtener paciente por id (personal, o el propio ciudadano)
    ---
    tags:
      - Pacientes
    security:
      - BearerAuth: []
    parameters:
      - name: id
        in: path
        type: integer
        required: true
    responses:
      200:
        description: Paciente
      403:
        description: El registro no pertenece al usuario
      404:
        description: Paciente no existe
    """
    paciente = Paciente.query.get(id)
    # Para un ciudadano, "no existe" y "no es tuyo" responden igual (403),
    # así no puede adivinar qué ids existen.
    if not puede_ver_paciente(paciente):
        return jsonify(success=False, error="permiso_denegado", message="Solo puede ver su propio registro"), 403
    if not paciente:
        return jsonify(success=False, error="no_encontrado", message="Paciente no existe"), 404

    return jsonify(success=True, data=serializar_paciente(paciente)), 200


@pacientes_bp.route("/api/v1/salud/pacientes/<int:id>", methods=["PUT"])
@validar_token
def actualizar_paciente(id):
    """
    Actualizar paciente (admin/recepción: todo; el propio ciudadano: contacto)
    ---
    tags:
      - Pacientes
    security:
      - BearerAuth: []
    parameters:
      - name: id
        in: path
        type: integer
        required: true
      - name: body
        in: body
        schema:
          type: object
          properties:
            telefono: {type: string}
            tipo_seguro: {type: string}
            cuidador: {type: string}
            nombre_completo: {type: string, description: "solo admin/recepción"}
            cui: {type: string, description: "solo admin/recepción"}
            fecha_nacimiento: {type: string, description: "solo admin/recepción"}
            genero: {type: string, description: "solo admin/recepción"}
            usuario_sub: {type: string, description: "solo admin/recepción; vincula al ciudadano"}
    responses:
      200:
        description: Actualizado
      409:
        description: Ese usuario ya está vinculado a otro paciente
      403:
        description: Sin permiso sobre este registro
    """
    paciente = Paciente.query.get(id)
    es_dueno = paciente is not None and paciente.usuario_sub == g.usuario["sub"]
    if not (es_dueno or puede("pacientes.registrar")):
        return jsonify(success=False, error="permiso_denegado", message="No puede modificar este registro"), 403
    if not paciente:
        return jsonify(success=False, error="no_encontrado", message="Paciente no existe"), 404

    data = request.get_json(silent=True) or {}
    # El propio ciudadano solo cambia sus datos de contacto y residencia; admin/recepción, todo.
    permitidos = ["telefono", "tipo_seguro", "cuidador", "municipio", "zona"]   # residencia: también la cambia el ciudadano
    if puede("pacientes.registrar"):
        permitidos += ["nombre_completo", "cui", "fecha_nacimiento", "genero", "usuario_sub"]
    data = {campo: valor for campo, valor in data.items() if campo in permitidos}
    if data.get("fecha_nacimiento") == str(paciente.fecha_nacimiento):
        del data["fecha_nacimiento"]   # sin cambios (en la base es una fecha, no texto)
    campos = _validar(data, actual=paciente)
    if "usuario_sub" in data:
        sub = _sub(data)
        if sub and Paciente.query.filter(Paciente.usuario_sub == sub, Paciente.id != paciente.id).first():
            return jsonify(success=False, error="ya_existe",
                           message="Ese usuario ya está vinculado a otro paciente"), 409
        campos["usuario_sub"] = sub

    for campo, valor in campos.items():
        setattr(paciente, campo, valor)
    db.session.commit()
    return jsonify(success=True, data={"id": paciente.id}, message="Actualizado"), 200
