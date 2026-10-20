"""
Laboratorio clínico: órdenes de exámenes y sus resultados.

  GET  /laboratorio/examenes                 catálogo (exámenes, parámetros y rangos de referencia)
  POST /laboratorio/ordenes                  el médico pide exámenes                  (laboratorio.ordenar)
  GET  /laboratorio/ordenes                  lista (estado, paciente_id)              (laboratorio.ver; ciudadano: las suyas)
  GET  /laboratorio/ordenes/<id>             una orden con resultados interpretados
  POST /laboratorio/ordenes/<id>/muestra     Enfermería toma la muestra -> EN_PROCESO (laboratorio.procesar)
  PUT  /laboratorio/ordenes/<id>/resultados  registra resultados; completar=true -> COMPLETADA
  POST /laboratorio/ordenes/<id>/anular      con motivo, si no está completada        (laboratorio.anular)

Los valores se validan contra lo posible (laboratorio.py) y cada resultado sale con su nivel
(normal, alto, bajo o anormal) para marcarlo en rojo en la pantalla y en la impresión.
"""
import json
from datetime import datetime

from flask import Blueprint, g, jsonify, request

import laboratorio
from auth import puede, requiere_permiso, tiene_rol, validar_token, ROL_JEFATURA
from extensions import db
from models import ExamenOrdenLaboratorio, ExpedienteClinico, OrdenLaboratorio, Paciente
from validacion import DatoInvalido, booleano, entero, opcion, texto

laboratorio_bp = Blueprint("laboratorio", __name__)
ESTADOS = ("PENDIENTE", "EN_PROCESO", "COMPLETADA", "ANULADA")
PRIORIDADES = ("RUTINA", "URGENTE")
MAX_EXAMENES = 15


def _error(status, codigo, mensaje):
    return jsonify(success=False, error=codigo, message=mensaje), status


def _nombre_usuario():
    return (g.usuario.get("nombre") or g.usuario.get("usuario") or "")[:150] or None


def _orden(o, paciente=None, con_resultados=True):
    examenes = []
    fuera = 0
    for e in o.examenes:
        info = laboratorio.EXAMENES.get(e.codigo, {})
        valores = json.loads(e.resultados) if e.resultados else {}
        datos = {"codigo": e.codigo, "nombre": info.get("nombre", e.codigo), "categoria": info.get("categoria")}
        if con_resultados:
            datos["resultados"] = laboratorio.resultados_interpretados(e.codigo, valores)
            fuera += sum(1 for r in datos["resultados"] if r["nivel"] in ("alto", "bajo", "anormal"))
            datos["completo"] = all(r["valor"] is not None for r in datos["resultados"])
        examenes.append(datos)
    return {
        "id": o.id, "paciente_id": o.paciente_id,
        "paciente": paciente.nombre_completo if paciente else None,
        "paciente_cui": paciente.cui if paciente else None,
        "paciente_fecha_nacimiento": str(paciente.fecha_nacimiento) if paciente and paciente.fecha_nacimiento else None,
        "paciente_genero": paciente.genero if paciente else None,
        "expediente_id": o.expediente_id, "medico_sub": o.medico_sub, "medico": o.medico_nombre,
        "fecha": o.fecha.isoformat(timespec="minutes"), "prioridad": o.prioridad, "indicaciones": o.indicaciones,
        "estado": o.estado,
        "fecha_muestra": o.fecha_muestra.isoformat(timespec="minutes") if o.fecha_muestra else None,
        "muestra_por": o.muestra_por,
        "fecha_resultado": o.fecha_resultado.isoformat(timespec="minutes") if o.fecha_resultado else None,
        "resultado_por": o.resultado_por, "observaciones": o.observaciones if con_resultados else None,
        "motivo_anulacion": o.motivo_anulacion, "examenes": examenes,
        "fuera_de_rango": fuera if con_resultados else None,
    }


def _paciente_propio():
    return Paciente.query.filter_by(usuario_sub=g.usuario["sub"]).first()


def _puede_ver_orden(o):
    """(puede, ver_resultados). El ciudadano ve sus órdenes, y los resultados solo cuando están completos."""
    if puede("laboratorio.ver"):
        return True, True
    propio = _paciente_propio() if tiene_rol("ciudadano") else None
    if propio is not None and propio.id == o.paciente_id:
        return True, o.estado == "COMPLETADA"
    return False, False


@laboratorio_bp.route("/api/v1/salud/laboratorio/examenes", methods=["GET"])
@validar_token
@requiere_permiso("laboratorio.ver")
def examenes_laboratorio():
    """
    Catálogo de exámenes de laboratorio
    ---
    tags:
      - Laboratorio
    security:
      - BearerAuth: []
    responses:
      200:
        description: "[{codigo, nombre, categoria, parametros: [{clave, nombre, tipo, unidad, min, max, opciones, normales, referencia}]}]"
    """
    return jsonify(success=True, data=laboratorio.catalogo(), categorias=laboratorio.CATEGORIAS), 200


@laboratorio_bp.route("/api/v1/salud/laboratorio/ordenes", methods=["POST"])
@validar_token
@requiere_permiso("laboratorio.ordenar")
def crear_orden():
    """
    Pedir exámenes de laboratorio
    ---
    tags:
      - Laboratorio
    security:
      - BearerAuth: []
    parameters:
      - in: body
        name: body
        required: true
        schema:
          type: object
          required: [paciente_id, examenes]
          properties:
            paciente_id: {type: integer, example: 1}
            examenes: {type: array, items: {type: string}, example: ["HEMATO", "GLUCOSA"]}
            prioridad: {type: string, enum: [RUTINA, URGENTE]}
            expediente_id: {type: integer, description: "Atención del expediente (opcional)"}
            indicaciones: {type: string, example: "Ayuno de 8 horas"}
    responses:
      201:
        description: Orden creada (PENDIENTE)
      400:
        description: Datos inválidos
      404:
        description: El paciente no existe
    """
    data = request.get_json(silent=True) or {}
    paciente = Paciente.query.get(entero(data, "paciente_id", 1, 2**31 - 1, obligatorio=True, etiqueta="paciente_id"))
    if not paciente:
        return _error(404, "no_encontrado", "Paciente no existe")
    codigos = data.get("examenes")
    if not isinstance(codigos, list) or not codigos:
        return _error(400, "datos_invalidos", "Elija al menos un examen")
    if len(codigos) > MAX_EXAMENES:
        return _error(400, "datos_invalidos", f"Una orden admite como máximo {MAX_EXAMENES} exámenes")
    if not all(isinstance(c, str) for c in codigos):
        return _error(400, "datos_invalidos", "Los exámenes van como códigos de texto (GET /laboratorio/examenes)")
    desconocidos = [c for c in codigos if c not in laboratorio.EXAMENES]
    if desconocidos:
        return _error(400, "datos_invalidos", f"Examen desconocido: {', '.join(desconocidos)[:100]}")
    if len(set(codigos)) != len(codigos):
        return _error(400, "datos_invalidos", "Un examen aparece dos veces en la orden")
    expediente_id = entero(data, "expediente_id", 1, 2**31 - 1, etiqueta="expediente_id")
    if expediente_id:
        atencion = ExpedienteClinico.query.get(expediente_id)
        if not atencion or atencion.paciente_id != paciente.id:
            return _error(400, "datos_invalidos", "La atención no pertenece a este paciente")
    o = OrdenLaboratorio(
        paciente_id=paciente.id, expediente_id=expediente_id, medico_sub=g.usuario["sub"],
        medico_nombre=_nombre_usuario(), fecha=datetime.now(),
        prioridad=opcion(data, "prioridad", PRIORIDADES, etiqueta="La prioridad") or "RUTINA",
        indicaciones=texto(data, "indicaciones", 500, etiqueta="Las indicaciones"), estado="PENDIENTE",
        examenes=[ExamenOrdenLaboratorio(codigo=c) for c in codigos])
    db.session.add(o)
    db.session.commit()
    return jsonify(success=True, data=_orden(o, paciente), message=f"Orden de laboratorio No. {o.id} creada"), 201


@laboratorio_bp.route("/api/v1/salud/laboratorio/ordenes", methods=["GET"])
@validar_token
def listar_ordenes():
    """
    Órdenes de laboratorio
    ---
    tags:
      - Laboratorio
    security:
      - BearerAuth: []
    description: >
      Personal con laboratorio.ver: todas (filtros estado y paciente_id), las urgentes primero entre
      las pendientes. Ciudadano: solo las suyas, con resultados solo si están completadas.
    parameters:
      - {name: estado, in: query, type: string, enum: [PENDIENTE, EN_PROCESO, COMPLETADA, ANULADA]}
      - {name: paciente_id, in: query, type: integer}
    responses:
      200:
        description: Las 200 más recientes
    """
    q = OrdenLaboratorio.query
    if puede("laboratorio.ver"):
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
        return _error(403, "sin_permiso", "No tiene permiso para ver el laboratorio")
    estado = (request.args.get("estado") or "").upper()
    if estado:
        if estado not in ESTADOS:
            return _error(400, "datos_invalidos", f"estado debe ser uno de: {', '.join(ESTADOS)}")
        q = q.filter_by(estado=estado)
    ordenes = q.order_by(OrdenLaboratorio.id.desc()).limit(200).all()
    # En la cola de trabajo, lo urgente primero
    ordenes.sort(key=lambda o: (o.estado not in ("PENDIENTE", "EN_PROCESO"), o.prioridad != "URGENTE"))
    ids = {o.paciente_id for o in ordenes}
    pacientes = {p.id: p for p in Paciente.query.filter(Paciente.id.in_(ids)).all()} if ids else {}
    personal = puede("laboratorio.ver")
    return jsonify(success=True, data=[_orden(o, pacientes.get(o.paciente_id), personal or o.estado == "COMPLETADA")
                                       for o in ordenes]), 200


@laboratorio_bp.route("/api/v1/salud/laboratorio/ordenes/<int:id>", methods=["GET"])
@validar_token
def ver_orden(id):
    """
    Una orden de laboratorio con sus resultados
    ---
    tags:
      - Laboratorio
    security:
      - BearerAuth: []
    parameters:
      - {name: id, in: path, type: integer, required: true}
    responses:
      200:
        description: La orden (cada resultado con valor, unidad, referencia y nivel)
      403:
        description: Sin permiso
      404:
        description: No existe (o no es del ciudadano)
    """
    o = OrdenLaboratorio.query.get(id)
    if o:
        ver, con_resultados = _puede_ver_orden(o)
        if not ver:
            if not tiene_rol("ciudadano"):
                return _error(403, "sin_permiso", "No tiene permiso para ver el laboratorio")
            o = None
    if not o:
        return _error(404, "no_encontrado", "La orden de laboratorio no existe")
    return jsonify(success=True, data=_orden(o, Paciente.query.get(o.paciente_id), con_resultados)), 200


@laboratorio_bp.route("/api/v1/salud/laboratorio/ordenes/<int:id>/muestra", methods=["POST"])
@validar_token
@requiere_permiso("laboratorio.procesar")
def tomar_muestra(id):
    """
    Registrar que se tomó la muestra (PENDIENTE -> EN_PROCESO)
    ---
    tags:
      - Laboratorio
    security:
      - BearerAuth: []
    parameters:
      - {name: id, in: path, type: integer, required: true}
    responses:
      200:
        description: Muestra tomada
      404:
        description: No existe
      409:
        description: La orden no está pendiente
    """
    o = OrdenLaboratorio.query.get(id)
    if not o:
        return _error(404, "no_encontrado", "La orden de laboratorio no existe")
    if o.estado != "PENDIENTE":
        return _error(409, "estado_invalido", f"La orden está {o.estado.lower().replace('_', ' ')}: no se puede tomar la muestra")
    o.estado, o.fecha_muestra, o.muestra_por = "EN_PROCESO", datetime.now(), _nombre_usuario()
    db.session.commit()
    return jsonify(success=True, data=_orden(o, Paciente.query.get(o.paciente_id)),
                   message=f"Muestra tomada (orden No. {o.id})"), 200


@laboratorio_bp.route("/api/v1/salud/laboratorio/ordenes/<int:id>/resultados", methods=["PUT"])
@validar_token
@requiere_permiso("laboratorio.procesar")
def registrar_resultados(id):
    """
    Registrar resultados (parciales o completos)
    ---
    tags:
      - Laboratorio
    security:
      - BearerAuth: []
    description: >
      Solo con la muestra tomada (EN_PROCESO). Los valores se guardan aunque falten otros;
      con completar=true deben estar todos los parámetros y la orden queda COMPLETADA (ya no se edita).
    parameters:
      - {name: id, in: path, type: integer, required: true}
      - in: body
        name: body
        required: true
        schema:
          type: object
          required: [resultados]
          properties:
            resultados:
              type: object
              example: {"GLUCOSA": {"glucosa": 126}, "HEMATO": {"hemoglobina": 13.2}}
            observaciones: {type: string}
            completar: {type: boolean}
    responses:
      200:
        description: Resultados guardados (con su interpretación)
      400:
        description: Un valor no es posible o falta alguno al completar
      409:
        description: La orden no está en proceso
    """
    o = OrdenLaboratorio.query.get(id)
    if not o:
        return _error(404, "no_encontrado", "La orden de laboratorio no existe")
    if o.estado != "EN_PROCESO":
        return _error(409, "estado_invalido", "Primero se toma la muestra; una orden completada o anulada ya no se edita")
    data = request.get_json(silent=True) or {}
    completar = booleano(data, "completar")
    resultados = data.get("resultados")
    if not isinstance(resultados, dict):
        return _error(400, "datos_invalidos", "resultados debe ser un objeto {examen: {parametro: valor}}")
    por_codigo = {e.codigo: e for e in o.examenes}
    otros = [c for c in resultados if c not in por_codigo]
    if otros:
        return _error(400, "datos_invalidos", f"Estos exámenes no están en la orden: {', '.join(map(str, otros))[:100]}")
    for codigo, valores in resultados.items():
        if not isinstance(valores, dict):
            return _error(400, "datos_invalidos", f"Los resultados de {codigo} deben ser un objeto {{parametro: valor}}")
        parametros = {p["clave"]: p for p in laboratorio.EXAMENES[codigo]["parametros"]}
        extra = [k for k in valores if k not in parametros]
        if extra:
            return _error(400, "datos_invalidos", f"{codigo} no tiene el parámetro: {', '.join(map(str, extra))[:100]}")
        guardados = json.loads(por_codigo[codigo].resultados) if por_codigo[codigo].resultados else {}
        for clave, valor in valores.items():
            limpio = laboratorio.validar_valor(parametros[clave], valor)
            if limpio is None:
                guardados.pop(clave, None)
            else:
                guardados[clave] = limpio
        por_codigo[codigo].resultados = json.dumps(guardados, ensure_ascii=False)
    observaciones = texto(data, "observaciones", 2000, etiqueta="Las observaciones")
    if observaciones is not None:
        o.observaciones = observaciones
    if completar:
        faltan = []
        for e in o.examenes:
            valores = json.loads(e.resultados) if e.resultados else {}
            faltan += [f"{laboratorio.EXAMENES[e.codigo]['nombre']}: {p['nombre']}"
                       for p in laboratorio.EXAMENES[e.codigo]["parametros"] if p["clave"] not in valores]
        if faltan:
            raise DatoInvalido(f"Faltan resultados para completar: {'; '.join(faltan)[:300]}")
        o.estado, o.fecha_resultado, o.resultado_por = "COMPLETADA", datetime.now(), _nombre_usuario()
    db.session.commit()
    datos = _orden(o, Paciente.query.get(o.paciente_id))
    mensaje = f"Resultados de la orden No. {o.id} {'completados' if completar else 'guardados'}"
    if datos["fuera_de_rango"]:
        mensaje += f". ⚠ {datos['fuera_de_rango']} fuera de rango"
    return jsonify(success=True, data=datos, message=mensaje), 200


@laboratorio_bp.route("/api/v1/salud/laboratorio/ordenes/<int:id>/anular", methods=["POST"])
@validar_token
@requiere_permiso("laboratorio.anular")
def anular_orden(id):
    """
    Anular una orden de laboratorio (no completada)
    ---
    tags:
      - Laboratorio
    security:
      - BearerAuth: []
    description: El médico solo anula las suyas; Jefatura, cualquiera.
    parameters:
      - {name: id, in: path, type: integer, required: true}
      - in: body
        name: body
        required: true
        schema:
          type: object
          required: [motivo]
          properties:
            motivo: {type: string}
    responses:
      200:
        description: Anulada
      403:
        description: No es suya (y no es Jefatura)
      409:
        description: Ya completada o anulada
    """
    o = OrdenLaboratorio.query.get(id)
    if not o:
        return _error(404, "no_encontrado", "La orden de laboratorio no existe")
    if not tiene_rol(ROL_JEFATURA) and o.medico_sub != g.usuario["sub"]:
        return _error(403, "sin_permiso", "Solo el médico que la pidió o Jefatura pueden anularla")
    if o.estado in ("COMPLETADA", "ANULADA"):
        return _error(409, "estado_invalido", f"La orden ya está {o.estado.lower()}")
    o.motivo_anulacion = texto(request.get_json(silent=True) or {}, "motivo", 255, obligatorio=True, minimo=5,
                               etiqueta="El motivo")
    o.estado = "ANULADA"
    db.session.commit()
    return jsonify(success=True, data=_orden(o, Paciente.query.get(o.paciente_id)),
                   message=f"Orden de laboratorio No. {o.id} anulada"), 200
