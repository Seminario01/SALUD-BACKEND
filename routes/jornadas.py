"""
Jornadas de vacunación coordinadas con Educación.

Una jornada nace de dos formas, y en las dos Educación devuelve los estudiantes convocados (E2):
  - Educación la pide a Salud con WS-SALUD-01 (routes/externos.py llama a guardar_jornada).
  - El personal de Salud la coordina desde Vacunación (POST /jornadas).
Después el personal ve cada jornada con sus estudiantes, si ya son pacientes de Salud y su
esquema, y marca a quién vacunó.

  GET  /jornadas                                    lista con convocados y vacunados   (vacunacion.ver)
  GET  /jornadas/<id>                               jornada con sus estudiantes        (vacunacion.ver)
  POST /jornadas                                    coordinar con Educación            (vacunacion.registrar)
  PUT  /jornadas/<id>/estudiantes/<eid>             {vacunado: true|false}             (vacunacion.registrar)
"""
import logging
import re
from datetime import date, datetime

from flask import Blueprint, g, jsonify, request

from auth import requiere_permiso, validar_token
from extensions import db
from models import EstudianteJornada, JornadaVacunacion, Paciente, Vacunacion
from services_externos import coordinar_jornada
from validacion import DatoInvalido, booleano, texto

jornadas_bp = Blueprint("jornadas", __name__)
log = logging.getLogger(__name__)


def _quien():
    usuario = getattr(g, "usuario", None) or {}
    return (usuario.get("nombre") or usuario.get("usuario") or "")[:150] or None


def _valor(e, *claves):
    """El primer campo que traiga el estudiante (Educación puede nombrarlos distinto)."""
    for clave in claves:
        v = e.get(clave)
        if v not in (None, ""):
            return str(v).strip()
    return None


def guardar_jornada(tipo_jornada, lugar, fecha, hora, estudiantes, origen):
    """Guarda (o actualiza, si ya existe la misma jornada) la jornada y sus estudiantes convocados.
    Si se vuelve a coordinar, se agregan los nuevos y se conserva quién ya fue vacunado."""
    j = JornadaVacunacion.query.filter_by(tipo_jornada=str(tipo_jornada)[:150], lugar=str(lugar)[:200],
                                          fecha=str(fecha)[:10], hora=str(hora)[:5]).first()
    if not j:
        j = JornadaVacunacion(tipo_jornada=str(tipo_jornada)[:150], lugar=str(lugar)[:200], fecha=str(fecha)[:10],
                              hora=str(hora)[:5], origen=origen, coordinada_por=_quien())
        db.session.add(j)
        db.session.flush()
    else:
        j.fecha_actualizacion = datetime.now()
    existentes = {e.cui: e for e in EstudianteJornada.query.filter_by(jornada_id=j.id) if e.cui}
    for e in estudiantes:
        if not isinstance(e, dict):
            continue
        cui = _valor(e, "cui", "dpi", "CUI")
        datos = {
            "nombre": (_valor(e, "nombreCompleto", "nombre_completo", "nombre") or "Sin nombre")[:200],
            "establecimiento": (_valor(e, "establecimiento") or "")[:200] or None,
            "grado": (_valor(e, "grado") or "")[:120] or None,
            "seccion": (_valor(e, "seccion", "sección") or "")[:20] or None,
            "jornada_escolar": (_valor(e, "jornada") or "")[:50] or None,
        }
        if cui and cui in existentes:
            for campo, valor in datos.items():
                setattr(existentes[cui], campo, valor)
        else:
            db.session.add(EstudianteJornada(jornada_id=j.id, cui=(cui or "")[:20] or None, **datos))
    db.session.commit()
    return j


def _resumen(j, conteos=None):
    convocados, vacunados = conteos or (
        EstudianteJornada.query.filter_by(jornada_id=j.id).count(),
        EstudianteJornada.query.filter_by(jornada_id=j.id, vacunado=True).count())
    return {"id": j.id, "tipo_jornada": j.tipo_jornada, "lugar": j.lugar, "fecha": j.fecha, "hora": j.hora,
            "origen": j.origen, "coordinada_por": j.coordinada_por,
            "fecha_registro": j.fecha_registro.isoformat(timespec="minutes"),
            "convocados": convocados, "vacunados": vacunados}


def _detalle(j):
    estudiantes = EstudianteJornada.query.filter_by(jornada_id=j.id).order_by(EstudianteJornada.nombre).all()
    cuis = [e.cui for e in estudiantes if e.cui]
    pacientes = {p.cui: p for p in Paciente.query.filter(Paciente.cui.in_(cuis))} if cuis else {}
    ids = [p.id for p in pacientes.values()]
    vacunas = {v.paciente_id: v for v in Vacunacion.query.filter(Vacunacion.paciente_id.in_(ids))} if ids else {}
    lista = []
    for e in estudiantes:
        p = pacientes.get(e.cui)
        v = vacunas.get(p.id) if p else None
        lista.append({
            "id": e.id, "cui": e.cui, "nombre": e.nombre, "establecimiento": e.establecimiento, "grado": e.grado,
            "seccion": e.seccion, "jornada": e.jornada_escolar, "vacunado": e.vacunado,
            "fecha_vacunado": e.fecha_vacunado.isoformat(timespec="minutes") if e.fecha_vacunado else None,
            "vacunado_por": e.vacunado_por,
            "paciente_id": p.id if p else None,
            "esquema_completo": v.esquema_completo if v else None,
            "vacunas_pendientes": v.vacunas_pendientes if v else None,
        })
    return {**_resumen(j, (len(lista), sum(1 for x in lista if x["vacunado"]))), "estudiantes": lista}


@jornadas_bp.route("/api/v1/salud/jornadas", methods=["GET"])
@validar_token
@requiere_permiso("vacunacion.ver")
def listar_jornadas():
    """
    Jornadas de vacunación coordinadas con Educación
    ---
    tags:
      - Vacunación
    security:
      - BearerAuth: []
    responses:
      200:
        description: Jornadas (la más próxima o reciente primero) con convocados y vacunados
    """
    jornadas = JornadaVacunacion.query.order_by(JornadaVacunacion.fecha.desc(), JornadaVacunacion.hora.desc()).all()
    conteo = dict(db.session.query(EstudianteJornada.jornada_id, db.func.count()).group_by(EstudianteJornada.jornada_id).all())
    vacunados = dict(db.session.query(EstudianteJornada.jornada_id, db.func.count())
                     .filter(EstudianteJornada.vacunado.is_(True)).group_by(EstudianteJornada.jornada_id).all())
    return jsonify(success=True, data=[_resumen(j, (conteo.get(j.id, 0), vacunados.get(j.id, 0))) for j in jornadas]), 200


@jornadas_bp.route("/api/v1/salud/jornadas/<int:id>", methods=["GET"])
@validar_token
@requiere_permiso("vacunacion.ver")
def obtener_jornada(id):
    """
    Jornada con sus estudiantes convocados
    ---
    tags:
      - Vacunación
    security:
      - BearerAuth: []
    parameters:
      - {name: id, in: path, type: integer, required: true}
    responses:
      200:
        description: Jornada, estudiantes, si ya son pacientes de Salud y su esquema
      404:
        description: No existe
    """
    j = JornadaVacunacion.query.get(id)
    if not j:
        return jsonify(success=False, error="no_encontrado", message="La jornada no existe"), 404
    return jsonify(success=True, data=_detalle(j)), 200


@jornadas_bp.route("/api/v1/salud/jornadas", methods=["POST"])
@validar_token
@requiere_permiso("vacunacion.registrar")
def crear_jornada():
    """
    Coordinar una jornada con Educación (Salud le pide los estudiantes convocados)
    ---
    tags:
      - Vacunación
    security:
      - BearerAuth: []
    parameters:
      - in: body
        name: body
        required: true
        schema:
          type: object
          required: [tipo_jornada, lugar, fecha, hora]
          properties:
            tipo_jornada: {type: string, example: "Vacunación Td y VPH"}
            lugar: {type: string, example: "INEB Jornada Matutina, Antigua Guatemala"}
            fecha: {type: string, example: "2026-11-05"}
            hora: {type: string, example: "08:00"}
    responses:
      201:
        description: Jornada guardada con los estudiantes que convocó Educación
      404:
        description: Educación no encontró estudiantes para ese lugar
      422:
        description: Educación rechazó la petición (con su motivo)
      503:
        description: Educación no está configurado o no responde
    """
    from routes.integraciones import _error_modulo   # evita una importación circular al arrancar

    data = request.get_json(silent=True) or {}
    tipo_jornada = texto(data, "tipo_jornada", 150, obligatorio=True, minimo=3, etiqueta="El tipo de jornada")
    lugar = texto(data, "lugar", 200, obligatorio=True, minimo=3, etiqueta="El lugar")
    fecha = texto(data, "fecha", 10, obligatorio=True, etiqueta="La fecha")
    hora = texto(data, "hora", 5, obligatorio=True, etiqueta="La hora")
    try:
        dia = date.fromisoformat(fecha)
    except ValueError:
        raise DatoInvalido("La fecha debe tener el formato AAAA-MM-DD")
    if dia < date.today():
        raise DatoInvalido("La fecha de la jornada no puede ser pasada")
    if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", hora):
        raise DatoInvalido("La hora debe tener el formato HH:MM")

    resultado = coordinar_jornada(tipo_jornada, lugar, fecha, hora)
    if resultado.get("error") == "no_encontrado":
        return jsonify(success=False, error="no_encontrado", message="Educación no encontró estudiantes para ese lugar"), 404
    if not resultado["success"]:
        return _error_modulo(resultado, "Educación")
    estudiantes = resultado["data"]
    if not isinstance(estudiantes, list) or not estudiantes:
        return jsonify(success=False, error="no_encontrado", message="Educación no devolvió estudiantes para esa jornada"), 404
    j = guardar_jornada(tipo_jornada, lugar, fecha, hora, estudiantes, "Salud")
    return jsonify(success=True, data=_detalle(j),
                   message=f"Jornada coordinada con Educación: {len(estudiantes)} estudiante(s) convocado(s)"), 201


@jornadas_bp.route("/api/v1/salud/jornadas/<int:id>/estudiantes/<int:eid>", methods=["PUT"])
@validar_token
@requiere_permiso("vacunacion.registrar")
def marcar_vacunado(id, eid):
    """
    Marcar (o desmarcar) a un estudiante como vacunado en la jornada
    ---
    tags:
      - Vacunación
    security:
      - BearerAuth: []
    parameters:
      - {name: id, in: path, type: integer, required: true}
      - {name: eid, in: path, type: integer, required: true}
      - in: body
        name: body
        required: true
        schema:
          type: object
          properties:
            vacunado: {type: boolean}
    responses:
      200:
        description: Estudiante actualizado
      404:
        description: No existe en esa jornada
    """
    e = EstudianteJornada.query.filter_by(id=eid, jornada_id=id).first()
    if not e:
        return jsonify(success=False, error="no_encontrado", message="El estudiante no está en esa jornada"), 404
    vacunado = booleano(request.get_json(silent=True) or {}, "vacunado", True)
    e.vacunado = vacunado
    e.fecha_vacunado = datetime.now() if vacunado else None
    e.vacunado_por = _quien() if vacunado else None
    db.session.commit()
    return jsonify(success=True, data={"id": e.id, "vacunado": e.vacunado},
                   message=f"{e.nombre}: {'vacunado' if vacunado else 'pendiente'}"), 200
