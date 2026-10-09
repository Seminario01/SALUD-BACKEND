"""
Hospitalización y censo de camas.

Flujo:
  1. El médico ORDENA el ingreso (PENDIENTE), indicando el área y el diagnóstico.
  2. Enfermería ASIGNA una cama disponible de esa área (ACTIVO, la cama queda OCUPADA).
     Con el paciente ya ingresado, asignar otra cama es un TRASLADO.
  3. Médico y Enfermería registran notas de evolución y signos vitales.
  4. El médico da el EGRESO (alta, alta voluntaria, traslado a otro centro o
     defunción). La cama pasa a LIMPIEZA y Enfermería la deja DISPONIBLE.

Las camas por área en recursos_hospitalarios (total y disponibles) se
recalculan desde el censo en cada cambio: el panel y Recursos siempre
coinciden con las camas reales.

Reglas de la matriz de permisos:
  - hospitalizacion.ver: el personal; Recepción y Caja sin datos clínicos.
  - hospitalizacion.ordenar (Médico), hospitalizacion.camas (Enfermería),
    hospitalizacion.notas (Médico y Enfermería), recursos.gestionar (Admin: camas nuevas).
  - El ciudadano ve solo SUS hospitalizaciones (BOLA).
"""
import re
from datetime import datetime, timedelta

from flask import Blueprint, g, jsonify, request

from auth import puede, requiere_permiso, tiene_rol, validar_token, ROL_MEDICO
from extensions import db
from models import Cama, ExpedienteClinico, Hospitalizacion, NotaHospitalizacion, Paciente, RecursoHospitalario

hospitalizacion_bp = Blueprint("hospitalizacion", __name__)

# Área de hospitalización -> categoría de camas en recursos_hospitalarios
AREAS = {
    "Medicina general": "Camas área general",
    "Pediatría": "Camas de pediatría",
    "Cuidados intensivos": "Camas de cuidados intensivos",
}
ESTADOS_CAMA = ("DISPONIBLE", "OCUPADA", "LIMPIEZA", "MANTENIMIENTO")
TIPOS_EGRESO = {
    "ALTA": "Alta médica",
    "ALTA_VOLUNTARIA": "Alta voluntaria",
    "TRASLADO": "Traslado a otro centro",
    "DEFUNCION": "Defunción",
}


def _error(status, codigo, mensaje):
    return jsonify(success=False, error=codigo, message=mensaje), status


def _entero(valor):
    try:
        return int(valor)
    except (TypeError, ValueError):
        return None


def _usuario():
    return g.usuario.get("nombre") or g.usuario.get("usuario")


def _fecha(valor):
    return valor.isoformat(timespec="minutes") if valor else None


def _paciente_propio():
    return Paciente.query.filter_by(usuario_sub=g.usuario["sub"]).first()


# ------------------------------------------------------------------ recursos
def _recurso_de_area(area):
    """Categoría de camas del área (la crea si no existe)."""
    descripcion = AREAS[area]
    recurso = RecursoHospitalario.query.filter_by(tipo="cama", descripcion=descripcion) \
        .order_by(RecursoHospitalario.id).first()
    if recurso is None:
        recurso = RecursoHospitalario(tipo="cama", descripcion=descripcion, disponible=0, total=0)
        db.session.add(recurso)
        db.session.flush()
    return recurso


def sincronizar_recursos(*areas):
    """Recalcula total y disponibles de las áreas indicadas desde el censo de camas."""
    db.session.flush()
    for area in set(areas):
        if area not in AREAS:
            continue
        recurso = _recurso_de_area(area)
        camas = Cama.query.filter_by(area=area).all()
        recurso.total = len(camas)
        recurso.disponible = sum(1 for c in camas if c.estado == "DISPONIBLE")


# ---------------------------------------------------------------- serializar
def _dias(h):
    inicio = h.fecha_asignacion or h.fecha_ingreso
    if not inicio or h.estado in ("PENDIENTE", "ANULADO"):
        return None
    fin = h.fecha_egreso or datetime.now()
    return max(0, (fin.date() - inicio.date()).days)


def _hospitalizacion(h, nombres=None, clinico=True, con_notas=False):
    dato = {
        "id": h.id, "paciente_id": h.paciente_id, "paciente": (nombres or {}).get(h.paciente_id),
        "estado": h.estado, "area": h.sala, "cama": h.cama, "cama_id": h.cama_id,
        "fecha_orden": _fecha(h.fecha_ingreso), "fecha_ingreso": _fecha(h.fecha_asignacion),
        "fecha_egreso": _fecha(h.fecha_egreso), "dias_estancia": _dias(h),
        "medico": h.medico_nombre, "medico_sub": h.medico_sub,
    }
    if clinico:
        dato.update({
            "diagnostico": h.diagnostico, "indicaciones": h.indicaciones, "expediente_id": h.expediente_id,
            "tipo_egreso": h.tipo_egreso, "tipo_egreso_texto": TIPOS_EGRESO.get(h.tipo_egreso),
            "resumen_egreso": h.resumen_egreso, "egresado_por": h.egresado_por,
            "motivo_anulacion": h.motivo_anulacion,
        })
    if con_notas and clinico:
        dato["notas"] = [{
            "id": n.id, "fecha": _fecha(n.fecha), "autor": n.autor_nombre, "puesto": n.puesto, "nota": n.nota,
            "presion": n.presion, "temperatura": float(n.temperatura) if n.temperatura is not None else None,
            "frecuencia_cardiaca": n.frecuencia_cardiaca, "saturacion": n.saturacion,
        } for n in h.notas]
    return dato


def _nombres(ids):
    ids = set(ids)
    return {p.id: p.nombre_completo for p in Paciente.query.filter(Paciente.id.in_(ids)).all()} if ids else {}


def _cama(c, ocupantes):
    h = ocupantes.get(c.id)
    return {
        "id": c.id, "codigo": c.codigo, "area": c.area, "estado": c.estado, "observacion": c.observacion,
        "hospitalizacion_id": h.id if h else None,
        "paciente_id": h.paciente_id if h else None,
        "paciente": h.paciente_nombre if h else None,
        "desde": _fecha(h.fecha_asignacion) if h else None,
    }


# ============================== Camas ==============================
@hospitalizacion_bp.route("/api/v1/salud/camas", methods=["GET"])
@validar_token
@requiere_permiso("hospitalizacion.ver")
def listar_camas():
    """
    Censo de camas
    ---
    tags:
      - Hospitalización
    security:
      - BearerAuth: []
    parameters:
      - name: area
        in: query
        type: string
        enum: [Medicina general, Pediatría, Cuidados intensivos]
      - name: estado
        in: query
        type: string
        enum: [DISPONIBLE, OCUPADA, LIMPIEZA, MANTENIMIENTO]
    responses:
      200:
        description: Camas con su estado y, si está ocupada, el paciente
    """
    query = Cama.query
    if request.args.get("area"):
        query = query.filter_by(area=request.args["area"])
    if request.args.get("estado"):
        query = query.filter_by(estado=request.args["estado"].upper())
    camas = query.order_by(Cama.area, Cama.codigo).all()
    activos = Hospitalizacion.query.filter_by(estado="ACTIVO").all()
    nombres = _nombres(h.paciente_id for h in activos)
    ocupantes = {}
    for h in activos:
        h.paciente_nombre = nombres.get(h.paciente_id)
        ocupantes[h.cama_id] = h
    return jsonify(success=True, data=[_cama(c, ocupantes) for c in camas]), 200


@hospitalizacion_bp.route("/api/v1/salud/camas", methods=["POST"])
@validar_token
@requiere_permiso("recursos.gestionar")
def crear_cama():
    """
    Agregar una cama al censo
    ---
    tags:
      - Hospitalización
    security:
      - BearerAuth: []
    parameters:
      - in: body
        name: body
        schema:
          type: object
          required: [codigo, area]
          properties:
            codigo: {type: string, example: "GEN-21"}
            area: {type: string, example: "Medicina general"}
    responses:
      201:
        description: Cama creada (DISPONIBLE); el total del área se actualiza
      400:
        description: Datos incompletos o área desconocida
      409:
        description: El código ya existe
    """
    data = request.get_json(silent=True) or {}
    codigo = str(data.get("codigo") or "").strip().upper()
    area = data.get("area")
    if not codigo or area not in AREAS:
        return _error(400, "datos_invalidos", f"Indique el código y un área: {', '.join(AREAS)}")
    if Cama.query.filter_by(codigo=codigo).first():
        return _error(409, "duplicado", f"Ya existe la cama {codigo}")
    cama = Cama(codigo=codigo, area=area, recurso_id=_recurso_de_area(area).id, estado="DISPONIBLE")
    db.session.add(cama)
    sincronizar_recursos(area)
    db.session.commit()
    return jsonify(success=True, data=_cama(cama, {}), message="Cama agregada"), 201


@hospitalizacion_bp.route("/api/v1/salud/camas/<int:id>", methods=["PUT"])
@validar_token
@requiere_permiso("hospitalizacion.camas", "recursos.gestionar")
def actualizar_cama(id):
    """
    Cambiar el estado de una cama (limpieza, mantenimiento, disponible)
    ---
    tags:
      - Hospitalización
    security:
      - BearerAuth: []
    parameters:
      - name: id
        in: path
        type: integer
        required: true
      - in: body
        name: body
        schema:
          type: object
          properties:
            estado: {type: string, enum: [DISPONIBLE, LIMPIEZA, MANTENIMIENTO]}
            observacion: {type: string, example: "Monitor en reparación"}
    responses:
      200:
        description: Estado actualizado
      409:
        description: La cama está ocupada (se libera con el egreso o un traslado)
    """
    cama = Cama.query.get(id)
    if not cama:
        return _error(404, "no_encontrado", "Cama no existe")
    data = request.get_json(silent=True) or {}
    estado = str(data.get("estado") or "").upper()
    if estado not in ("DISPONIBLE", "LIMPIEZA", "MANTENIMIENTO"):
        return _error(400, "datos_invalidos", "Estado debe ser DISPONIBLE, LIMPIEZA o MANTENIMIENTO")
    if cama.estado == "OCUPADA":
        return _error(409, "cama_ocupada", f"La cama {cama.codigo} está ocupada")
    cama.estado = estado
    cama.observacion = (data.get("observacion") or None) if estado == "MANTENIMIENTO" else None
    sincronizar_recursos(cama.area)
    db.session.commit()
    return jsonify(success=True, data=_cama(cama, {}), message="Cama actualizada"), 200


# ========================= Hospitalizaciones =========================
@hospitalizacion_bp.route("/api/v1/salud/hospitalizaciones", methods=["GET"])
@validar_token
def listar_hospitalizaciones():
    """
    Listar hospitalizaciones
    ---
    tags:
      - Hospitalización
    security:
      - BearerAuth: []
    description: >
      Personal con hospitalizacion.ver: todas (Recepción y Caja sin diagnóstico).
      Ciudadano: solo las suyas.
    parameters:
      - name: estado
        in: query
        type: string
        enum: [PENDIENTE, ACTIVO, EGRESADO, ANULADO]
      - name: paciente_id
        in: query
        type: integer
    responses:
      200:
        description: Hospitalizaciones, de la más reciente a la más antigua
    """
    query = Hospitalizacion.query
    if puede("hospitalizacion.ver"):
        clinico = puede("expediente.ver")
        if request.args.get("paciente_id"):
            query = query.filter_by(paciente_id=_entero(request.args["paciente_id"]))
    else:
        propio = _paciente_propio()
        if propio is None:
            return jsonify(success=True, data=[]), 200
        clinico = True
        query = query.filter_by(paciente_id=propio.id)
    if request.args.get("estado"):
        query = query.filter_by(estado=request.args["estado"].upper())
    lista = query.order_by(Hospitalizacion.id.desc()).limit(300).all()
    nombres = _nombres(h.paciente_id for h in lista)
    return jsonify(success=True, data=[_hospitalizacion(h, nombres, clinico) for h in lista]), 200


@hospitalizacion_bp.route("/api/v1/salud/hospitalizaciones/<int:id>", methods=["GET"])
@validar_token
def ver_hospitalizacion(id):
    """
    Detalle de una hospitalización con sus notas de evolución
    ---
    tags:
      - Hospitalización
    security:
      - BearerAuth: []
    parameters:
      - name: id
        in: path
        type: integer
        required: true
    responses:
      200:
        description: Hospitalización y notas (las notas, solo con acceso clínico)
      403:
        description: No es personal ni el paciente
    """
    h = Hospitalizacion.query.get(id)
    if puede("hospitalizacion.ver"):
        if not h:
            return _error(404, "no_encontrado", "Hospitalización no existe")
        clinico = puede("expediente.ver")
    else:
        propio = _paciente_propio()
        if not h or not propio or h.paciente_id != propio.id:
            return _error(403, "permiso_denegado", "Solo puede ver sus propias hospitalizaciones")
        clinico = True
    return jsonify(success=True, data=_hospitalizacion(h, _nombres([h.paciente_id]), clinico, con_notas=True)), 200


@hospitalizacion_bp.route("/api/v1/salud/hospitalizaciones", methods=["POST"])
@validar_token
@requiere_permiso("hospitalizacion.ordenar")
def ordenar_ingreso():
    """
    Ordenar el ingreso de un paciente (médico)
    ---
    tags:
      - Hospitalización
    security:
      - BearerAuth: []
    parameters:
      - in: body
        name: body
        schema:
          type: object
          required: [paciente_id, area, diagnostico]
          properties:
            paciente_id: {type: integer, example: 4}
            area: {type: string, example: "Medicina general"}
            diagnostico: {type: string, example: "Dolor abdominal agudo en estudio"}
            indicaciones: {type: string, example: "Ayuno, hidratación IV, control de signos cada 4 h"}
            expediente_id: {type: integer, description: "Atención del expediente que origina el ingreso"}
    responses:
      201:
        description: Orden PENDIENTE; Enfermería asigna la cama
      400:
        description: Datos incompletos
      404:
        description: Paciente no existe
      409:
        description: El paciente ya tiene un ingreso pendiente o activo
    """
    data = request.get_json(silent=True) or {}
    paciente = Paciente.query.get(_entero(data.get("paciente_id")) or 0)
    if not paciente:
        return _error(404, "no_encontrado", "Paciente no existe")
    area = data.get("area")
    diagnostico = (data.get("diagnostico") or "").strip()
    if area not in AREAS or not diagnostico:
        return _error(400, "datos_invalidos", f"Indique el diagnóstico de ingreso y un área: {', '.join(AREAS)}")
    abierta = Hospitalizacion.query.filter(Hospitalizacion.paciente_id == paciente.id,
                                           Hospitalizacion.estado.in_(("PENDIENTE", "ACTIVO"))).first()
    if abierta:
        estado = "pendiente de cama" if abierta.estado == "PENDIENTE" else f"en la cama {abierta.cama}"
        return _error(409, "ya_hospitalizado", f"{paciente.nombre_completo} ya tiene un ingreso {estado}")
    expediente_id = _entero(data.get("expediente_id"))
    if expediente_id:
        atencion = ExpedienteClinico.query.get(expediente_id)
        if not atencion or atencion.paciente_id != paciente.id:
            return _error(400, "datos_invalidos", "La atención no pertenece a este paciente")
    h = Hospitalizacion(paciente_id=paciente.id, sala=area, diagnostico=diagnostico,
                        indicaciones=(data.get("indicaciones") or "").strip() or None,
                        expediente_id=expediente_id, estado="PENDIENTE", fecha_ingreso=datetime.now(),
                        medico_sub=g.usuario["sub"], medico_nombre=_usuario())
    db.session.add(h)
    db.session.commit()
    return jsonify(success=True, data=_hospitalizacion(h, {paciente.id: paciente.nombre_completo}),
                   message="Ingreso ordenado; pendiente de cama"), 201


@hospitalizacion_bp.route("/api/v1/salud/hospitalizaciones/<int:id>/asignar-cama", methods=["POST"])
@validar_token
@requiere_permiso("hospitalizacion.camas")
def asignar_cama(id):
    """
    Asignar cama (ingreso) o trasladar a otra cama (Enfermería)
    ---
    tags:
      - Hospitalización
    security:
      - BearerAuth: []
    parameters:
      - name: id
        in: path
        type: integer
        required: true
      - in: body
        name: body
        schema:
          type: object
          required: [cama_id]
          properties:
            cama_id: {type: integer}
    responses:
      200:
        description: Paciente en la cama (ACTIVO). En un traslado, la cama anterior pasa a LIMPIEZA
      400:
        description: La cama no es del área ordenada
      409:
        description: Cama no disponible, u hospitalización egresada o anulada
    """
    h = Hospitalizacion.query.get(id)
    if not h:
        return _error(404, "no_encontrado", "Hospitalización no existe")
    if h.estado not in ("PENDIENTE", "ACTIVO"):
        return _error(409, "estado_invalido", f"La hospitalización está {h.estado.lower()}")
    cama = Cama.query.filter_by(id=_entero((request.get_json(silent=True) or {}).get("cama_id")) or 0) \
        .with_for_update().first()
    if not cama:
        return _error(404, "no_encontrado", "Cama no existe")
    if cama.estado != "DISPONIBLE":
        return _error(409, "cama_no_disponible", f"La cama {cama.codigo} está {cama.estado.lower()}")
    if h.estado == "PENDIENTE" and cama.area != h.sala:
        return _error(400, "area_distinta", f"El ingreso es para {h.sala}; la cama {cama.codigo} es de {cama.area}")

    areas = {cama.area}
    if h.estado == "ACTIVO":                                   # traslado
        anterior = Cama.query.get(h.cama_id) if h.cama_id else None
        if anterior:
            anterior.estado = "LIMPIEZA"
            areas.add(anterior.area)
        db.session.add(NotaHospitalizacion(
            hospitalizacion_id=h.id, autor_sub=g.usuario["sub"], autor_nombre=_usuario(), puesto="Enfermería",
            nota=f"Traslado de la cama {h.cama} ({h.sala}) a la cama {cama.codigo} ({cama.area})."))
        mensaje = f"Paciente trasladado a la cama {cama.codigo}"
    else:
        h.fecha_asignacion = datetime.now()
        h.asignado_por = _usuario()
        h.estado = "ACTIVO"
        mensaje = f"Paciente ingresado en la cama {cama.codigo}"
    cama.estado = "OCUPADA"
    h.cama_id, h.cama, h.sala = cama.id, cama.codigo, cama.area
    sincronizar_recursos(*areas)
    db.session.commit()
    return jsonify(success=True, data=_hospitalizacion(h, _nombres([h.paciente_id])), message=mensaje), 200


@hospitalizacion_bp.route("/api/v1/salud/hospitalizaciones/<int:id>/egreso", methods=["POST"])
@validar_token
@requiere_permiso("hospitalizacion.ordenar")
def dar_egreso(id):
    """
    Dar el egreso (médico)
    ---
    tags:
      - Hospitalización
    security:
      - BearerAuth: []
    parameters:
      - name: id
        in: path
        type: integer
        required: true
      - in: body
        name: body
        schema:
          type: object
          required: [tipo_egreso, resumen]
          properties:
            tipo_egreso: {type: string, enum: [ALTA, ALTA_VOLUNTARIA, TRASLADO, DEFUNCION]}
            resumen: {type: string, example: "Evolución favorable; control en consulta externa en 7 días"}
    responses:
      200:
        description: EGRESADO; la cama pasa a LIMPIEZA
      400:
        description: Tipo de egreso o resumen faltante
      409:
        description: El paciente no está ingresado en una cama
    """
    h = Hospitalizacion.query.get(id)
    if not h:
        return _error(404, "no_encontrado", "Hospitalización no existe")
    data = request.get_json(silent=True) or {}
    tipo = str(data.get("tipo_egreso") or "").upper()
    resumen = (data.get("resumen") or "").strip()
    if tipo not in TIPOS_EGRESO or not resumen:
        return _error(400, "datos_invalidos", "Indique el tipo de egreso y el resumen")
    if h.estado != "ACTIVO":
        mensaje = "La orden aún no tiene cama: anúlela en lugar de dar egreso" if h.estado == "PENDIENTE" \
            else f"La hospitalización ya está {h.estado.lower()}"
        return _error(409, "estado_invalido", mensaje)
    cama = Cama.query.get(h.cama_id) if h.cama_id else None
    if cama:
        cama.estado = "LIMPIEZA"
        sincronizar_recursos(cama.area)
    h.estado, h.tipo_egreso, h.resumen_egreso = "EGRESADO", tipo, resumen
    h.fecha_egreso, h.egresado_por = datetime.now(), _usuario()
    db.session.commit()
    return jsonify(success=True, data=_hospitalizacion(h, _nombres([h.paciente_id])),
                   message=f"{TIPOS_EGRESO[tipo]} registrada"), 200


@hospitalizacion_bp.route("/api/v1/salud/hospitalizaciones/<int:id>/anular", methods=["POST"])
@validar_token
@requiere_permiso("hospitalizacion.ordenar")
def anular_orden(id):
    """
    Anular una orden de ingreso que aún no tiene cama (médico)
    ---
    tags:
      - Hospitalización
    security:
      - BearerAuth: []
    parameters:
      - name: id
        in: path
        type: integer
        required: true
      - in: body
        name: body
        schema:
          type: object
          properties:
            motivo: {type: string, example: "Se resolvió en observación de emergencia"}
    responses:
      200:
        description: ANULADO
      409:
        description: La orden ya tiene cama o está cerrada
    """
    h = Hospitalizacion.query.get(id)
    if not h:
        return _error(404, "no_encontrado", "Hospitalización no existe")
    if h.estado != "PENDIENTE":
        return _error(409, "estado_invalido", "Solo se anulan órdenes que aún no tienen cama")
    h.estado = "ANULADO"
    h.motivo_anulacion = ((request.get_json(silent=True) or {}).get("motivo") or "Orden anulada")[:255]
    db.session.commit()
    return jsonify(success=True, data=_hospitalizacion(h, _nombres([h.paciente_id])), message="Orden anulada"), 200


PRESION = re.compile(r"^\d{2,3}/\d{2,3}$")


@hospitalizacion_bp.route("/api/v1/salud/hospitalizaciones/<int:id>/notas", methods=["POST"])
@validar_token
@requiere_permiso("hospitalizacion.notas")
def agregar_nota(id):
    """
    Nota de evolución o de enfermería, con signos vitales opcionales
    ---
    tags:
      - Hospitalización
    security:
      - BearerAuth: []
    parameters:
      - name: id
        in: path
        type: integer
        required: true
      - in: body
        name: body
        schema:
          type: object
          required: [nota]
          properties:
            nota: {type: string, example: "Paciente afebril, tolera dieta blanda"}
            presion: {type: string, example: "120/80"}
            temperatura: {type: number, example: 36.8}
            frecuencia_cardiaca: {type: integer, example: 78}
            saturacion: {type: integer, example: 97}
    responses:
      201:
        description: Nota registrada
      400:
        description: Nota vacía o signos vitales fuera de rango
      409:
        description: El paciente no está ingresado
    """
    h = Hospitalizacion.query.get(id)
    if not h:
        return _error(404, "no_encontrado", "Hospitalización no existe")
    if h.estado != "ACTIVO":
        return _error(409, "estado_invalido", "Solo se registran notas de pacientes ingresados")
    data = request.get_json(silent=True) or {}
    nota = (data.get("nota") or "").strip()
    if not nota:
        return _error(400, "datos_invalidos", "Escriba la nota")
    presion = (data.get("presion") or "").strip() or None
    if presion and not PRESION.match(presion):
        return _error(400, "datos_invalidos", "Presión arterial con formato 120/80")
    try:
        temperatura = float(data["temperatura"]) if data.get("temperatura") not in (None, "") else None
    except (TypeError, ValueError):
        temperatura = -1
    fc = _entero(data.get("frecuencia_cardiaca")) if data.get("frecuencia_cardiaca") not in (None, "") else None
    sat = _entero(data.get("saturacion")) if data.get("saturacion") not in (None, "") else None
    if temperatura is not None and not 30 <= temperatura <= 45:
        return _error(400, "datos_invalidos", "Temperatura fuera de rango (30–45 °C)")
    if data.get("frecuencia_cardiaca") not in (None, "") and (fc is None or not 20 <= fc <= 250):
        return _error(400, "datos_invalidos", "Frecuencia cardiaca fuera de rango (20–250 lpm)")
    if data.get("saturacion") not in (None, "") and (sat is None or not 50 <= sat <= 100):
        return _error(400, "datos_invalidos", "Saturación fuera de rango (50–100 %)")
    n = NotaHospitalizacion(hospitalizacion_id=h.id, autor_sub=g.usuario["sub"], autor_nombre=_usuario(),
                            puesto="Médico" if tiene_rol(ROL_MEDICO) else "Enfermería", nota=nota,
                            presion=presion, temperatura=temperatura, frecuencia_cardiaca=fc, saturacion=sat)
    db.session.add(n)
    db.session.commit()
    return jsonify(success=True, data={"id": n.id}, message="Nota registrada"), 201


def resumen_hospitalizacion():
    """Indicadores agregados (panel e /indicadores). Sin datos personales."""
    camas = Cama.query.all()
    total = len(camas)
    ocupadas = sum(1 for c in camas if c.estado == "OCUPADA")
    hace30 = datetime.now() - timedelta(days=30)
    return {
        "hospitalizados": Hospitalizacion.query.filter_by(estado="ACTIVO").count(),
        "ordenes_pendientes": Hospitalizacion.query.filter_by(estado="PENDIENTE").count(),
        "egresos_ultimos_30_dias": Hospitalizacion.query.filter(Hospitalizacion.estado == "EGRESADO",
                                                                Hospitalizacion.fecha_egreso >= hace30).count(),
        "camas_total": total,
        "camas_disponibles": sum(1 for c in camas if c.estado == "DISPONIBLE"),
        "camas_ocupadas": ocupadas,
        "ocupacion_porcentaje": round(ocupadas * 100 / total, 1) if total else 0,
    }
