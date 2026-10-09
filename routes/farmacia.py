"""
Farmacia: inventario de medicamentos y recetas.

Flujo: el médico receta (PENDIENTE) -> Farmacia despacha (DESPACHADA) y se
descuenta el inventario con un movimiento de SALIDA por cada medicamento.
Reglas de la matriz de permisos:
  - recetas.crear (Médico), recetas.despachar (Farmacia): quien receta no despacha.
  - inventario.gestionar (Farmacia): medicamentos nuevos, entradas y ajustes.
  - El ciudadano ve solo SUS recetas (BOLA).
"""
from datetime import datetime

from flask import Blueprint, g, jsonify, request

import cuentas
from auth import puede, requiere_permiso, tiene_rol, validar_token, ROL_JEFATURA
from extensions import db
from models import DetalleReceta, ExpedienteClinico, Medicamento, MovimientoInventario, Paciente, Receta

farmacia_bp = Blueprint("farmacia", __name__)


def _error(status, codigo, mensaje):
    return jsonify(success=False, error=codigo, message=mensaje), status


def _entero(valor):
    try:
        return int(valor)
    except (TypeError, ValueError):
        return None


def _medicamento(m):
    return {
        "id": m.id, "codigo": m.codigo, "nombre": m.nombre, "presentacion": m.presentacion,
        "descripcion": m.descripcion, "existencia": m.existencia, "stock_minimo": m.stock_minimo,
        "precio": float(m.precio) if m.precio is not None else None,
        "bajo_minimo": m.existencia <= (m.stock_minimo or 0),
    }


def _receta(r, nombres=None):
    return {
        "id": r.id, "paciente_id": r.paciente_id,
        "paciente": (nombres or {}).get(r.paciente_id),
        "medico_sub": r.medico_sub, "medico": r.medico_nombre, "expediente_id": r.expediente_id,
        "fecha": r.fecha.isoformat(timespec="minutes") if r.fecha else None,
        "indicaciones": r.indicaciones, "estado": r.estado,
        "fecha_despacho": r.fecha_despacho.isoformat(timespec="minutes") if r.fecha_despacho else None,
        "motivo_anulacion": r.motivo_anulacion,
        "items": [{
            "medicamento_id": d.medicamento_id, "medicamento": d.medicamento.nombre if d.medicamento else None,
            "presentacion": d.medicamento.presentacion if d.medicamento else None,
            "cantidad": d.cantidad, "dosis": d.dosis,
            "existencia": d.medicamento.existencia if d.medicamento else None,
        } for d in r.detalles],
    }


def _paciente_propio():
    return Paciente.query.filter_by(usuario_sub=g.usuario["sub"]).first()


# ============================ Inventario ============================
@farmacia_bp.route("/api/v1/salud/medicamentos", methods=["GET"])
@validar_token
@requiere_permiso("inventario.ver", "recetas.crear")
def listar_medicamentos():
    """
    Inventario de medicamentos
    ---
    tags:
      - Farmacia
    security:
      - BearerAuth: []
    parameters:
      - name: q
        in: query
        type: string
        description: Buscar por nombre o código
      - name: bajo_minimo
        in: query
        type: boolean
        description: Solo los que están en o por debajo del stock mínimo
    responses:
      200:
        description: Medicamentos con existencia, stock mínimo y alerta bajo_minimo
    """
    query = Medicamento.query
    q = (request.args.get("q") or "").strip()
    if q:
        query = query.filter(db.or_(Medicamento.nombre.ilike(f"%{q}%"), Medicamento.codigo.ilike(f"%{q}%")))
    if request.args.get("bajo_minimo") in ("1", "true"):
        query = query.filter(Medicamento.existencia <= Medicamento.stock_minimo)
    return jsonify(success=True, data=[_medicamento(m) for m in query.order_by(Medicamento.nombre).all()]), 200


@farmacia_bp.route("/api/v1/salud/medicamentos", methods=["POST"])
@validar_token
@requiere_permiso("inventario.gestionar")
def crear_medicamento():
    """
    Agregar un medicamento al catálogo
    ---
    tags:
      - Farmacia
    security:
      - BearerAuth: []
    parameters:
      - in: body
        name: body
        required: true
        schema:
          type: object
          required: [codigo, nombre]
          properties:
            codigo: {type: string, example: "MED-016"}
            nombre: {type: string, example: "Loratadina"}
            presentacion: {type: string, example: "Tableta 10 mg"}
            existencia: {type: integer, example: 100}
            stock_minimo: {type: integer, example: 20}
            precio: {type: number, example: 1.50}
    responses:
      201:
        description: Medicamento creado
      400:
        description: Datos inválidos
      409:
        description: Ya existe un medicamento con ese código
    """
    data = request.get_json(silent=True) or {}
    codigo = (data.get("codigo") or "").strip().upper()
    nombre = (data.get("nombre") or "").strip()
    existencia = _entero(data.get("existencia", 0))
    minimo = _entero(data.get("stock_minimo", 10))
    if not codigo or not nombre:
        return _error(400, "datos_incompletos", "codigo y nombre son requeridos")
    if existencia is None or existencia < 0 or minimo is None or minimo < 0:
        return _error(400, "datos_invalidos", "existencia y stock_minimo deben ser números enteros, 0 o más")
    if Medicamento.query.filter_by(codigo=codigo).first():
        return _error(409, "ya_existe", "Ya existe un medicamento con ese código")
    m = Medicamento(codigo=codigo, nombre=nombre, presentacion=(data.get("presentacion") or None),
                    descripcion=data.get("descripcion"), existencia=existencia, stock_minimo=minimo,
                    precio=data.get("precio"))
    db.session.add(m)
    db.session.flush()
    if existencia:
        db.session.add(MovimientoInventario(medicamento_id=m.id, tipo_movimiento="ENTRADA", cantidad=existencia,
                                            observacion="Existencia inicial", usuario=g.usuario.get("usuario")))
    db.session.commit()
    return jsonify(success=True, data=_medicamento(m), message="Medicamento agregado"), 201


@farmacia_bp.route("/api/v1/salud/medicamentos/<int:id>/movimientos", methods=["POST"])
@validar_token
@requiere_permiso("inventario.gestionar")
def registrar_movimiento(id):
    """
    Registrar una entrada (compra o donación) o un ajuste de inventario
    ---
    tags:
      - Farmacia
    security:
      - BearerAuth: []
    parameters:
      - name: id
        in: path
        type: integer
        required: true
      - in: body
        name: body
        required: true
        schema:
          type: object
          required: [tipo, cantidad]
          properties:
            tipo: {type: string, enum: [ENTRADA, AJUSTE], example: ENTRADA}
            cantidad: {type: integer, example: 50, description: "ENTRADA: mayor a 0. AJUSTE: positivo o negativo"}
            observacion: {type: string, example: "Compra orden 2026-118"}
    responses:
      201:
        description: Movimiento registrado; devuelve el medicamento con la nueva existencia
      400:
        description: Datos inválidos o la existencia quedaría negativa
    """
    m = Medicamento.query.get(id)
    if not m:
        return _error(404, "no_encontrado", "Medicamento no existe")
    data = request.get_json(silent=True) or {}
    tipo = str(data.get("tipo") or "").upper()
    cantidad = _entero(data.get("cantidad"))
    if tipo not in ("ENTRADA", "AJUSTE") or cantidad is None or cantidad == 0:
        return _error(400, "datos_invalidos", "tipo (ENTRADA o AJUSTE) y una cantidad distinta de 0 son requeridos")
    if tipo == "ENTRADA" and cantidad < 0:
        return _error(400, "datos_invalidos", "Una entrada debe ser mayor a 0")
    if m.existencia + cantidad < 0:
        return _error(400, "datos_invalidos", f"La existencia quedaría negativa (hay {m.existencia})")
    m.existencia += cantidad
    db.session.add(MovimientoInventario(medicamento_id=m.id, tipo_movimiento=tipo, cantidad=cantidad,
                                        observacion=(data.get("observacion") or None),
                                        usuario=g.usuario.get("usuario")))
    db.session.commit()
    return jsonify(success=True, data=_medicamento(m), message="Movimiento registrado"), 201


@farmacia_bp.route("/api/v1/salud/medicamentos/<int:id>/movimientos", methods=["GET"])
@validar_token
@requiere_permiso("inventario.ver")
def listar_movimientos(id):
    """
    Movimientos de inventario de un medicamento (kardex)
    ---
    tags:
      - Farmacia
    security:
      - BearerAuth: []
    parameters:
      - name: id
        in: path
        type: integer
        required: true
    responses:
      200:
        description: Entradas, salidas por receta y ajustes, del más reciente al más antiguo
    """
    if not Medicamento.query.get(id):
        return _error(404, "no_encontrado", "Medicamento no existe")
    movimientos = MovimientoInventario.query.filter_by(medicamento_id=id) \
        .order_by(MovimientoInventario.id.desc()).limit(100).all()
    return jsonify(success=True, data=[{
        "id": mv.id, "tipo": mv.tipo_movimiento, "cantidad": mv.cantidad,
        "fecha": mv.fecha.isoformat(timespec="minutes") if mv.fecha else None,
        "observacion": mv.observacion, "receta_id": mv.receta_id, "usuario": mv.usuario,
    } for mv in movimientos]), 200


# ============================== Recetas ==============================
@farmacia_bp.route("/api/v1/salud/recetas", methods=["POST"])
@validar_token
@requiere_permiso("recetas.crear")
def crear_receta():
    """
    Recetar medicamentos a un paciente
    ---
    tags:
      - Farmacia
    security:
      - BearerAuth: []
    parameters:
      - in: body
        name: body
        required: true
        schema:
          type: object
          required: [paciente_id, items]
          properties:
            paciente_id: {type: integer, example: 1}
            expediente_id: {type: integer, description: "Atención del expediente (opcional)"}
            indicaciones: {type: string, example: "Tomar con alimentos. Regresar si persiste la fiebre."}
            items:
              type: array
              items:
                type: object
                required: [medicamento_id, cantidad]
                properties:
                  medicamento_id: {type: integer, example: 1}
                  cantidad: {type: integer, example: 15}
                  dosis: {type: string, example: "1 tableta cada 8 horas por 5 días"}
    responses:
      201:
        description: Receta creada en estado PENDIENTE (queda a nombre del médico que receta)
      400:
        description: Datos inválidos
      404:
        description: El paciente o algún medicamento no existe
    """
    data = request.get_json(silent=True) or {}
    paciente = Paciente.query.get(_entero(data.get("paciente_id")) or 0)
    if not paciente:
        return _error(404, "no_encontrado", "Paciente no existe")
    items = data.get("items") or []
    if not isinstance(items, list) or not items:
        return _error(400, "datos_incompletos", "La receta necesita al menos un medicamento")
    detalles, vistos = [], set()
    for item in items:
        mid, cantidad = _entero((item or {}).get("medicamento_id")), _entero((item or {}).get("cantidad"))
        if mid is None or cantidad is None or cantidad <= 0:
            return _error(400, "datos_invalidos", "Cada medicamento necesita medicamento_id y una cantidad mayor a 0")
        if mid in vistos:
            return _error(400, "datos_invalidos", "Un medicamento aparece dos veces en la receta")
        vistos.add(mid)
        if not Medicamento.query.get(mid):
            return _error(404, "no_encontrado", f"El medicamento {mid} no existe")
        detalles.append(DetalleReceta(medicamento_id=mid, cantidad=cantidad,
                                      dosis=((item.get("dosis") or "").strip() or None)))
    expediente_id = _entero(data.get("expediente_id"))
    if expediente_id:
        atencion = ExpedienteClinico.query.get(expediente_id)
        if not atencion or atencion.paciente_id != paciente.id:
            return _error(400, "datos_invalidos", "La atención no pertenece a este paciente")
    receta = Receta(paciente_id=paciente.id, medico_sub=g.usuario["sub"],
                    medico_nombre=g.usuario.get("nombre") or g.usuario.get("usuario"), expediente_id=expediente_id,
                    indicaciones=(data.get("indicaciones") or None), estado="PENDIENTE", detalles=detalles)
    db.session.add(receta)
    db.session.commit()
    return jsonify(success=True, data=_receta(receta, {paciente.id: paciente.nombre_completo}),
                   message="Receta creada"), 201


@farmacia_bp.route("/api/v1/salud/recetas", methods=["GET"])
@validar_token
def listar_recetas():
    """
    Listar recetas
    ---
    tags:
      - Farmacia
    security:
      - BearerAuth: []
    description: >
      Personal con permiso recetas.ver: todas (filtros estado y paciente_id).
      Ciudadano: solo sus propias recetas.
    parameters:
      - name: estado
        in: query
        type: string
        enum: [PENDIENTE, DESPACHADA, ANULADA]
      - name: paciente_id
        in: query
        type: integer
    responses:
      200:
        description: Recetas con sus medicamentos, de la más reciente a la más antigua
    """
    query = Receta.query
    if puede("recetas.ver"):
        if request.args.get("paciente_id"):
            query = query.filter_by(paciente_id=_entero(request.args["paciente_id"]))
    else:
        propio = _paciente_propio()
        if propio is None:
            return jsonify(success=True, data=[]), 200
        query = query.filter_by(paciente_id=propio.id)
    estado = (request.args.get("estado") or "").upper()
    if estado:
        query = query.filter_by(estado=estado)
    recetas = query.order_by(Receta.id.desc()).limit(200).all()
    ids = {r.paciente_id for r in recetas}
    nombres = {p.id: p.nombre_completo for p in Paciente.query.filter(Paciente.id.in_(ids)).all()} if ids else {}
    return jsonify(success=True, data=[_receta(r, nombres) for r in recetas]), 200


@farmacia_bp.route("/api/v1/salud/recetas/<int:id>/despachar", methods=["POST"])
@validar_token
@requiere_permiso("recetas.despachar")
def despachar_receta(id):
    """
    Despachar una receta y descontar el inventario
    ---
    tags:
      - Farmacia
    security:
      - BearerAuth: []
    description: >
      Verifica que haya existencia de TODOS los medicamentos; si falta alguno no
      se despacha nada. Registra una SALIDA de inventario por medicamento.
      Quien recetó no puede despachar su propia receta.
    parameters:
      - name: id
        in: path
        type: integer
        required: true
    responses:
      200:
        description: Receta DESPACHADA
      403:
        description: Quien recetó intenta despacharla
      409:
        description: La receta no está pendiente, o no hay existencia suficiente
    """
    receta = Receta.query.get(id)
    if not receta:
        return _error(404, "no_encontrado", "Receta no existe")
    if receta.estado != "PENDIENTE":
        return _error(409, "estado_invalido", f"La receta ya está {receta.estado.lower()}")
    if receta.medico_sub == g.usuario["sub"]:
        return _error(403, "permiso_denegado", "Quien receta no puede despachar su propia receta")
    faltantes = []
    medicamentos = {}
    for d in receta.detalles:
        m = Medicamento.query.filter_by(id=d.medicamento_id).with_for_update().first()
        medicamentos[d.medicamento_id] = m
        if m.existencia < d.cantidad:
            faltantes.append(f"{m.nombre} (hay {m.existencia}, se necesitan {d.cantidad})")
    if faltantes:
        db.session.rollback()
        return _error(409, "sin_existencia", "No hay existencia suficiente: " + "; ".join(faltantes))
    for d in receta.detalles:
        medicamentos[d.medicamento_id].existencia -= d.cantidad
        db.session.add(MovimientoInventario(medicamento_id=d.medicamento_id, tipo_movimiento="SALIDA",
                                            cantidad=-d.cantidad, receta_id=receta.id,
                                            observacion=f"Despacho de la receta {receta.id}",
                                            usuario=g.usuario.get("usuario")))
    receta.estado = "DESPACHADA"
    receta.despachado_por = g.usuario["sub"]
    receta.fecha_despacho = datetime.now()
    cuenta = cuentas.cargar_receta(receta, g.usuario.get("nombre") or g.usuario.get("usuario"))
    db.session.commit()
    mensaje = "Receta despachada" + (f"; cargada a la cuenta No. {cuenta.id}" if cuenta else "")
    return jsonify(success=True, data=_receta(receta), message=mensaje), 200


@farmacia_bp.route("/api/v1/salud/recetas/<int:id>/anular", methods=["POST"])
@validar_token
@requiere_permiso("recetas.anular")
def anular_receta(id):
    """
    Anular una receta pendiente
    ---
    tags:
      - Farmacia
    security:
      - BearerAuth: []
    description: El médico que la recetó, o Jefatura. Solo recetas PENDIENTES (no toca el inventario).
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
            motivo: {type: string, example: "Dosis equivocada; se emitió una receta nueva"}
    responses:
      200:
        description: Receta ANULADA
      403:
        description: No es el médico que la recetó ni Jefatura
      409:
        description: La receta no está pendiente
    """
    receta = Receta.query.get(id)
    if not receta:
        return _error(404, "no_encontrado", "Receta no existe")
    if receta.medico_sub != g.usuario["sub"] and not tiene_rol(ROL_JEFATURA):
        return _error(403, "permiso_denegado", "Solo el médico que la recetó o Jefatura pueden anularla")
    if receta.estado != "PENDIENTE":
        return _error(409, "estado_invalido", f"La receta ya está {receta.estado.lower()}")
    receta.estado = "ANULADA"
    receta.motivo_anulacion = ((request.get_json(silent=True) or {}).get("motivo") or "Anulada por el médico")[:255]
    db.session.commit()
    return jsonify(success=True, data=_receta(receta), message="Receta anulada"), 200
