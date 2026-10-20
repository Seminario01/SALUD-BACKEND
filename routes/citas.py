from flask import Blueprint, request, jsonify, g
from extensions import db
from models import BitacoraAcceso, CitaMedica, ExpedienteClinico, Hospitalizacion, Paciente, PersonalSalud, Receta
from auth import ROL_MEDICO, requiere_permiso, validar_token, puede, tiene_rol
from bitacora_accesos import _puesto
from validacion import DatoInvalido, entero, fecha_hora_futura, texto

ESTADOS_CITA = ("pendiente", "confirmada", "atendida", "cancelada")

citas_bp = Blueprint("citas", __name__)


def _paciente_propio():
    """Registro de paciente vinculado al `sub` del usuario (o None)."""
    return Paciente.query.filter_by(usuario_sub=g.usuario["sub"]).first()


def _puede_gestionar(paciente_id):
    """OWASP API1 (BOLA): el personal de Salud gestiona citas de cualquier
    paciente; un ciudadano solo las de su propio registro."""
    if puede("citas.gestionar"):
        return True
    propio = _paciente_propio()
    return propio is not None and str(paciente_id) == str(propio.id)


def _cita_repetida(paciente_id, fecha_hora, excepto=None):
    """El paciente ya tiene otra cita (no cancelada) a esa misma hora."""
    q = CitaMedica.query.filter(CitaMedica.paciente_id == paciente_id, CitaMedica.fecha_hora == fecha_hora,
                                CitaMedica.estado != "cancelada")
    if excepto is not None:
        q = q.filter(CitaMedica.id != excepto)
    return q.first() is not None


def _yo():
    """Nombre del usuario actual para guardarlo en la cita."""
    return (g.usuario.get("nombre") or g.usuario.get("usuario") or "")[:150] or None


def _nombre_medico(sub, guardado=None):
    """Nombre del médico: el guardado en la cita o, para citas antiguas, el que quedó
    en sus recetas, hospitalizaciones u otras citas (el Login Único solo da el `sub`)."""
    if guardado or not sub:
        return guardado
    for modelo in (CitaMedica, Receta, Hospitalizacion):
        fila = modelo.query.filter(modelo.medico_sub == sub, modelo.medico_nombre.isnot(None)).first()
        if fila:
            return fila.medico_nombre
    return None


def medicos_conocidos():
    """Médicos que han usado el módulo (personal_salud) y, para datos anteriores, los que
    aparecen en citas, recetas u hospitalizaciones. {sub: nombre}"""
    conocidos = {}
    for modelo in (CitaMedica, Receta, Hospitalizacion):
        for sub, nombre in db.session.query(modelo.medico_sub, modelo.medico_nombre).filter(
                modelo.medico_sub.isnot(None), modelo.medico_nombre.isnot(None)).distinct():
            conocidos.setdefault(sub, nombre)
    for p in PersonalSalud.query.filter_by(es_medico=True).all():
        conocidos[p.sub] = p.nombre or p.usuario or conocidos.get(p.sub)
    return conocidos


def _medico_elegido(data):
    """medico_sub del cuerpo: debe ser un médico conocido. Devuelve (sub, nombre); (None, None) si no viene."""
    sub = texto(data, "medico_sub", 36, etiqueta="medico_sub")
    if not sub:
        return None, None
    nombre = medicos_conocidos().get(sub)
    if nombre is None:
        raise DatoInvalido("El médico elegido no está registrado en el módulo")
    return sub, nombre


def _asignarme_si_soy_medico(cita):
    """Si un médico agenda o atiende una cita sin médico, la cita queda a su nombre."""
    if not cita.medico_sub and tiene_rol(ROL_MEDICO):
        cita.medico_sub = g.usuario["sub"]
        cita.medico_nombre = _yo()


def _sin_permiso():
    return jsonify(success=False, error="permiso_denegado", message="Solo puede gestionar sus propias citas"), 403

@citas_bp.route("/api/v1/salud/citas", methods=["POST"])
@validar_token
def crear_cita():
    """
    Agendar una nueva cita médica
    ---
    tags:
      - Citas
    security:
      - BearerAuth: []
    parameters:
      - name: body
        in: body
        required: true
        schema:
          type: object
          properties:
            paciente_id:
              type: integer
            medico_sub:
              type: string
              description: sub del médico en el Login Único
            fecha_hora:
              type: string
            motivo:
              type: string
    responses:
      201:
        description: Cita creada
      403:
        description: Un ciudadano intentó agendar para otro paciente
    """
    data = request.get_json(silent=True) or {}
    paciente_id = entero(data, "paciente_id", 1, 2_147_483_647, obligatorio=True)
    if not _puede_gestionar(paciente_id):
        return _sin_permiso()
    fecha_hora = fecha_hora_futura(data.get("fecha_hora"))
    motivo = texto(data, "motivo", 300, etiqueta="El motivo")
    medico_sub, medico_nombre = _medico_elegido(data)
    if not Paciente.query.get(paciente_id):
        return jsonify(success=False, error="no_encontrado", message="Paciente no existe"), 404
    if _cita_repetida(paciente_id, fecha_hora):
        return jsonify(success=False, error="ya_existe",
                       message="El paciente ya tiene una cita a esa misma hora"), 409

    puesto = _puesto(g.usuario.get("roles", []))
    cita = CitaMedica(paciente_id=paciente_id, medico_sub=medico_sub, medico_nombre=medico_nombre,
                      fecha_hora=fecha_hora, motivo=motivo,
                      agendada_por=f"{_yo() or ''}{f' ({puesto})' if puesto else ''}"[:150] or None)
    _asignarme_si_soy_medico(cita)
    db.session.add(cita)
    db.session.commit()
    return jsonify(success=True, data={"id": cita.id}, message="Cita creada"), 201


@citas_bp.route("/api/v1/salud/citas/<int:id>", methods=["PUT"])
@validar_token
def reprogramar_cita(id):
    """
    Reprogramar o cambiar estado de una cita
    ---
    tags:
      - Citas
    security:
      - BearerAuth: []
    parameters:
      - name: id
        in: path
        type: integer
        required: true
      - name: body
        in: body
        required: true
        schema:
          type: object
          properties:
            fecha_hora:
              type: string
            estado:
              type: string
    responses:
      200:
        description: Cita actualizada
      404:
        description: Cita no existe
    """
    cita = CitaMedica.query.get(id)
    if cita is None:
        if not puede("citas.gestionar"):
            return _sin_permiso()
        return jsonify(success=False, error="no_encontrado", message="Cita no existe"), 404
    if not _puede_gestionar(cita.paciente_id):
        return _sin_permiso()

    data = request.get_json(silent=True) or {}
    if "fecha_hora" in data:
        fecha_hora = fecha_hora_futura(data["fecha_hora"])
        if _cita_repetida(cita.paciente_id, fecha_hora, excepto=cita.id):
            return jsonify(success=False, error="ya_existe",
                           message="El paciente ya tiene otra cita a esa misma hora"), 409
        cita.fecha_hora = fecha_hora
    if "medico_sub" in data:
        # Asignar o cambiar el médico (null o "" lo deja sin asignar): solo el personal que gestiona citas
        if not puede("citas.gestionar"):
            return jsonify(success=False, error="permiso_denegado", message="Solo el personal puede asignar el médico"), 403
        cita.medico_sub, cita.medico_nombre = _medico_elegido(data) if data["medico_sub"] else (None, None)
    if "estado" in data:
        # El estado (confirmada, atendida...) solo lo cambia el personal que gestiona citas.
        if not puede("citas.gestionar"):
            return jsonify(success=False, error="permiso_denegado", message="Solo el personal puede cambiar el estado"), 403
        if data["estado"] not in ESTADOS_CITA:
            return jsonify(success=False, error="datos_invalidos",
                           message=f"estado debe ser uno de: {', '.join(ESTADOS_CITA)}"), 400
        cita.estado = data["estado"]
        if cita.estado in ("confirmada", "atendida"):
            _asignarme_si_soy_medico(cita)

    db.session.commit()
    return jsonify(success=True, data={"id": cita.id}, message="Cita actualizada"), 200


@citas_bp.route("/api/v1/salud/citas/<int:id>", methods=["DELETE"])
@validar_token
def cancelar_cita(id):
    """
    Cancelar una cita médica
    ---
    tags:
      - Citas
    security:
      - BearerAuth: []
    parameters:
      - name: id
        in: path
        type: integer
        required: true
    responses:
      200:
        description: Cita cancelada
      404:
        description: Cita no existe
    """
    cita = CitaMedica.query.get(id)
    if cita is None:
        if not puede("citas.gestionar"):
            return _sin_permiso()
        return jsonify(success=False, error="no_encontrado", message="Cita no existe"), 404
    if not _puede_gestionar(cita.paciente_id):
        return _sin_permiso()

    cita.estado = "cancelada"
    db.session.commit()
    # Se liberó un espacio: Recepción ve cuántos pacientes esperan uno
    from routes.lista_espera import en_espera
    esperan = en_espera()
    mensaje = "Cita cancelada" + (f". Hay {esperan} paciente(s) en lista de espera" if esperan else "")
    return jsonify(success=True, data={"en_lista_espera": esperan}, message=mensaje), 200


@citas_bp.route("/api/v1/salud/citas", methods=["GET"])
@validar_token
def listar_citas():
    """
    Listar citas médicas
    ---
    tags:
      - Citas
    security:
      - BearerAuth: []
    parameters:
      - name: paciente_id
        in: query
        type: integer
        required: false
        description: Filtrar por paciente (solo personal; un ciudadano siempre ve solo las suyas)
    responses:
      200:
        description: Lista de citas
    """
    query = CitaMedica.query
    if puede("citas.ver"):
        paciente_id = request.args.get("paciente_id")
        if paciente_id:
            query = query.filter_by(paciente_id=paciente_id)
    else:
        # OWASP API1 (BOLA): el ciudadano nunca ve citas de otros.
        propio = _paciente_propio()
        if propio is None:
            return jsonify(success=True, data=[]), 200
        query = query.filter_by(paciente_id=propio.id)

    citas = query.order_by(CitaMedica.fecha_hora.desc()).all()
    return jsonify(success=True, data=[{
        "id": c.id,
        "paciente_id": c.paciente_id,
        "medico_sub": c.medico_sub,
        "medico_nombre": c.medico_nombre,
        "fecha_hora": str(c.fecha_hora),
        "estado": c.estado,
        "motivo": c.motivo,
        "costo": float(c.costo) if c.costo is not None else None,
        "pago_confirmado": bool(c.pago_confirmado),
        # Cobro en Tributario
        "numero_referencia": c.numero_referencia,
        "estado_cobro": "PAGADO" if c.pago_confirmado else c.estado_cobro,
        "fecha_vencimiento": c.fecha_vencimiento.isoformat() if c.fecha_vencimiento else None,
        "numero_autorizacion": c.numero_autorizacion,
        "referencia_tributario": c.referencia_tributario,
        "fecha_pago": c.fecha_pago.isoformat(timespec="seconds") if c.fecha_pago else None,
    } for c in citas]), 200

@citas_bp.route("/api/v1/salud/citas/<int:id>", methods=["GET"])
@validar_token
def ver_cita(id):
    """
    Detalle de una cita: paciente, médico, fecha, pago, atención e historial
    ---
    tags:
      - Citas
    security:
      - BearerAuth: []
    description: >
      Personal con citas.ver: cualquier cita. Ciudadano: solo las suyas (404 si es de otro,
      para no revelar que existe). La atención registrada (diagnóstico) solo se incluye para
      quien puede ver expedientes; el historial de cambios, solo para el personal.
    parameters:
      - name: id
        in: path
        type: integer
        required: true
    responses:
      200:
        description: Detalle de la cita
      404:
        description: La cita no existe (o es de otro paciente)
    """
    cita = CitaMedica.query.get(id)
    personal = puede("citas.ver")
    if cita is not None and not personal:
        propio = _paciente_propio()
        if propio is None or propio.id != cita.paciente_id:
            cita = None
    if cita is None:
        return jsonify(success=False, error="no_encontrado", message="Cita no existe"), 404

    p = Paciente.query.get(cita.paciente_id)
    dato = {
        "id": cita.id,
        "estado": cita.estado,
        "fecha_hora": str(cita.fecha_hora),
        "motivo": cita.motivo,
        # fecha_creacion se guarda en UTC (datetime.utcnow): se marca para que el navegador la pase a hora local
        "fecha_creacion": cita.fecha_creacion.isoformat(timespec="seconds") + "Z" if cita.fecha_creacion else None,
        "agendada_por": cita.agendada_por,
        "medico_sub": cita.medico_sub,
        "medico_nombre": _nombre_medico(cita.medico_sub, cita.medico_nombre),
        "paciente_id": cita.paciente_id,
        "paciente": p.nombre_completo if p else None,
        "paciente_cui": p.cui if p else None,
        "paciente_telefono": p.telefono if p else None,
        "paciente_fecha_nacimiento": str(p.fecha_nacimiento) if p and p.fecha_nacimiento else None,
        # Pago (Tributario)
        "costo": float(cita.costo) if cita.costo is not None else None,
        "pago_confirmado": bool(cita.pago_confirmado),
        "estado_cobro": "PAGADO" if cita.pago_confirmado else cita.estado_cobro,
        "numero_referencia": cita.numero_referencia,
        "referencia_tributario": cita.referencia_tributario,
        "fecha_vencimiento": cita.fecha_vencimiento.isoformat() if cita.fecha_vencimiento else None,
        "numero_autorizacion": cita.numero_autorizacion,
        "fecha_pago": cita.fecha_pago.isoformat(timespec="seconds") if cita.fecha_pago else None,
    }
    if puede("expediente.ver") or not personal:
        dato["atenciones"] = [{
            "id": a.id, "fecha_atencion": str(a.fecha_atencion), "diagnostico": a.diagnostico,
            "tratamiento": a.tratamiento, "medico": _nombre_medico(a.medico_sub),
        } for a in ExpedienteClinico.query.filter_by(cita_id=cita.id).order_by(ExpedienteClinico.fecha_atencion).all()]
    if personal:
        ruta = f"/api/v1/salud/citas/{cita.id}"
        cambios = BitacoraAcceso.query.filter(
            BitacoraAcceso.accion != "ver",
            db.or_(BitacoraAcceso.ruta == ruta, BitacoraAcceso.ruta.like(ruta + "/%"),
                   BitacoraAcceso.descripcion == f"Agendó la cita No. {cita.id}"),
        ).order_by(BitacoraAcceso.fecha).limit(100).all()
        dato["historial"] = [{
            "fecha": h.fecha.isoformat(timespec="seconds"), "descripcion": h.descripcion,
            "usuario": h.nombre or h.usuario, "puesto": h.puesto,
        } for h in cambios]
    return jsonify(success=True, data=dato), 200


@citas_bp.route("/api/v1/salud/medicos", methods=["GET"])
@validar_token
@requiere_permiso("citas.ver")
def listar_medicos():
    """
    Médicos para asignar a una cita
    ---
    tags:
      - Citas
    security:
      - BearerAuth: []
    description: >
      El Login Único no entrega la lista de usuarios, así que el módulo anota a cada médico
      la primera vez que entra (tabla personal_salud). También incluye a los médicos que ya
      aparecen en citas, recetas u hospitalizaciones. Ordenados por nombre.
    responses:
      200:
        description: "[{sub, nombre}]"
    """
    lista = sorted(({"sub": s, "nombre": n} for s, n in medicos_conocidos().items()), key=lambda m: (m["nombre"] or "").lower())
    return jsonify(success=True, data=lista), 200
