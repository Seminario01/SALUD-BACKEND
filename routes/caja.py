"""
Caja: cuentas del paciente y cobro por Tributario.

Una cuenta de HOSPITALIZACIÓN se abre sola al asignar la cama y recibe sola el
día cama y los medicamentos despachados (cuentas.py). Una cuenta AMBULATORIA la
abre Caja para servicios sueltos (laboratorio, imágenes).

Caja agrega servicios del catálogo, aplica descuentos (exoneración de trabajo
social) y, con el paciente ya egresado, CIERRA la cuenta: el saldo se registra
como obligación en Tributario (mismo contrato que las citas, referencia
SAL-AAAA-NNNNNN). Se da por pagada al verificar en Tributario o cuando
Tributario envía el aviso de pago (POST /pagos/notificacion).

Matriz de permisos: cuentas.ver (Recepción, Caja, Admin), cuentas.gestionar
(Caja); el catálogo de servicios lo mantiene Administración (recursos.gestionar).
El ciudadano ve solo SUS cuentas.
"""
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from flask import Blueprint, g, jsonify, request

import cuentas
from auth import puede, requiere_permiso, validar_token
from config import Config
from extensions import db
from models import CuentaPaciente, Hospitalizacion, MovimientoCuenta, Paciente, Servicio
from routes.integraciones import ESTADOS_PAGADO, _error_modulo, _fecha_hora, _siguiente_referencia
from services_externos import consultar_obligacion, registrar_obligacion

caja_bp = Blueprint("caja", __name__)

CATEGORIAS = {
    "DIA_CAMA": "Día cama", "LABORATORIO": "Laboratorio", "IMAGEN": "Imágenes",
    "PROCEDIMIENTO": "Procedimiento", "MEDICAMENTO": "Medicamento", "DESCUENTO": "Descuento", "PAGO": "Pago",
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


def _f(valor):
    return float(valor) if valor is not None else None


def _fecha(valor):
    return valor.isoformat(timespec="minutes") if isinstance(valor, datetime) else (valor.isoformat() if valor else None)


def _paciente_propio():
    return Paciente.query.filter_by(usuario_sub=g.usuario["sub"]).first()


# --------------------------------------------------------------- serializar
def _servicio(s):
    return {"id": s.id, "codigo": s.codigo, "nombre": s.nombre, "descripcion": s.descripcion,
            "categoria": s.categoria, "costo": _f(s.costo), "estado": s.estado}


def _totales(cuenta):
    vivos = [m for m in cuenta.movimientos if not m.anulado]
    suma = lambda tipo: float(sum(Decimal(m.monto) for m in vivos if m.tipo == tipo))
    return {"cargos": suma("CARGO"), "descuentos": suma("DESCUENTO"), "pagos": suma("PAGO")}


def _cuenta(c, nombres=None, hosp=None, detalle=False):
    dato = {
        "id": c.id, "paciente_id": c.paciente_id, "paciente": (nombres or {}).get(c.paciente_id),
        "tipo": c.tipo, "estado": c.estado, "saldo": _f(c.saldo),
        "hospitalizacion_id": c.hospitalizacion_id,
        "area": hosp.sala if hosp else None, "cama": hosp.cama if hosp else None,
        "estado_hospitalizacion": hosp.estado if hosp else None,
        "fecha_apertura": _fecha(c.fecha_apertura), "fecha_cierre": _fecha(c.fecha_cierre),
        "numero_referencia": c.numero_referencia, "estado_cobro": c.estado_cobro,
        "fecha_vencimiento": _fecha(c.fecha_vencimiento), "numero_autorizacion": c.numero_autorizacion,
        "fecha_pago": _fecha(c.fecha_pago), "cerrada_por": c.cerrada_por,
        **_totales(c),
    }
    en_curso = cuentas.estancia_en_curso(c)
    dato["estancia_en_curso"] = en_curso
    dato["total_estimado"] = round(dato["saldo"] + (en_curso["monto"] if en_curso else 0), 2)
    if detalle:
        dato["movimientos"] = [{
            "id": m.id, "fecha": _fecha(m.fecha), "tipo": m.tipo, "categoria": m.categoria,
            "categoria_texto": CATEGORIAS.get(m.categoria, m.categoria), "descripcion": m.descripcion,
            "cantidad": m.cantidad, "precio_unitario": _f(m.precio_unitario), "monto": _f(m.monto),
            "usuario": m.usuario, "anulado": bool(m.anulado), "motivo_anulacion": m.motivo_anulacion,
        } for m in c.movimientos]
    return dato


def _contexto(lista):
    ids = {c.paciente_id for c in lista}
    nombres = {p.id: p.nombre_completo for p in Paciente.query.filter(Paciente.id.in_(ids)).all()} if ids else {}
    hids = {c.hospitalizacion_id for c in lista if c.hospitalizacion_id}
    hosp = {h.id: h for h in Hospitalizacion.query.filter(Hospitalizacion.id.in_(hids)).all()} if hids else {}
    return nombres, hosp


def _respuesta(c, status=200, mensaje=None):
    nombres, hosp = _contexto([c])
    return jsonify(success=True, data=_cuenta(c, nombres, hosp.get(c.hospitalizacion_id), detalle=True),
                   message=mensaje), status


def _cuenta_abierta(id):
    c = CuentaPaciente.query.get(id)
    if not c:
        return None, _error(404, "no_encontrado", "Cuenta no existe")
    if c.estado != "ABIERTA":
        return None, _error(409, "cuenta_cerrada", f"La cuenta está {c.estado.lower().replace('_', ' ')}")
    return c, None


# ============================ Servicios ============================
@caja_bp.route("/api/v1/salud/servicios", methods=["GET"])
@validar_token
@requiere_permiso("cuentas.ver", "recursos.gestionar")
def listar_servicios():
    """
    Catálogo de servicios y tarifas
    ---
    tags:
      - Caja
    security:
      - BearerAuth: []
    parameters:
      - name: todos
        in: query
        type: boolean
        description: Incluir los servicios inactivos
    responses:
      200:
        description: Servicios con su categoría y costo (GTQ)
    """
    query = Servicio.query
    if request.args.get("todos") not in ("1", "true"):
        query = query.filter((Servicio.estado == "ACTIVO") | (Servicio.estado.is_(None)))
    return jsonify(success=True, data=[_servicio(s) for s in query.order_by(Servicio.categoria, Servicio.nombre).all()]), 200


@caja_bp.route("/api/v1/salud/servicios", methods=["POST"])
@validar_token
@requiere_permiso("recursos.gestionar")
def crear_servicio():
    """
    Agregar un servicio al catálogo (Administración)
    ---
    tags:
      - Caja
    security:
      - BearerAuth: []
    parameters:
      - in: body
        name: body
        schema:
          type: object
          required: [codigo, nombre, categoria, costo]
          properties:
            codigo: {type: string, example: "LAB-010"}
            nombre: {type: string, example: "Perfil de lípidos"}
            categoria: {type: string, enum: [LABORATORIO, IMAGEN, PROCEDIMIENTO, DIA_CAMA]}
            costo: {type: number, example: 85.00}
    responses:
      201:
        description: Servicio creado
      400:
        description: Datos incompletos
      409:
        description: El código ya existe
    """
    data = request.get_json(silent=True) or {}
    codigo = str(data.get("codigo") or "").strip().upper()
    nombre = (data.get("nombre") or "").strip()
    categoria = str(data.get("categoria") or "").upper()
    try:
        costo = Decimal(str(data.get("costo")))
    except (InvalidOperation, TypeError):
        costo = Decimal("-1")
    if not codigo or not nombre or categoria not in ("LABORATORIO", "IMAGEN", "PROCEDIMIENTO", "DIA_CAMA") or costo < 0:
        return _error(400, "datos_invalidos", "Indique código, nombre, categoría y un costo válido")
    if Servicio.query.filter_by(codigo=codigo).first():
        return _error(409, "duplicado", f"Ya existe el servicio {codigo}")
    s = Servicio(codigo=codigo, nombre=nombre, categoria=categoria, costo=costo,
                 descripcion=(data.get("descripcion") or None), estado="ACTIVO")
    db.session.add(s)
    db.session.commit()
    return jsonify(success=True, data=_servicio(s), message="Servicio agregado"), 201


@caja_bp.route("/api/v1/salud/servicios/<int:id>", methods=["PUT"])
@validar_token
@requiere_permiso("recursos.gestionar")
def actualizar_servicio(id):
    """
    Cambiar tarifa o estado de un servicio (Administración)
    ---
    tags:
      - Caja
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
            costo: {type: number, example: 90.00}
            estado: {type: string, enum: [ACTIVO, INACTIVO]}
    responses:
      200:
        description: Servicio actualizado (los cargos ya hechos conservan su precio)
    """
    s = Servicio.query.get(id)
    if not s:
        return _error(404, "no_encontrado", "Servicio no existe")
    data = request.get_json(silent=True) or {}
    if "costo" in data:
        try:
            costo = Decimal(str(data["costo"]))
        except (InvalidOperation, TypeError):
            costo = Decimal("-1")
        if costo < 0:
            return _error(400, "datos_invalidos", "Costo inválido")
        s.costo = costo
    if "estado" in data:
        if data["estado"] not in ("ACTIVO", "INACTIVO"):
            return _error(400, "datos_invalidos", "Estado debe ser ACTIVO o INACTIVO")
        s.estado = data["estado"]
    db.session.commit()
    return jsonify(success=True, data=_servicio(s), message="Servicio actualizado"), 200


# ============================== Cuentas ==============================
@caja_bp.route("/api/v1/salud/cuentas", methods=["GET"])
@validar_token
def listar_cuentas():
    """
    Listar cuentas de pacientes
    ---
    tags:
      - Caja
    security:
      - BearerAuth: []
    description: >
      Recepción, Caja y Administración: todas. Ciudadano: solo las suyas.
    parameters:
      - name: estado
        in: query
        type: string
        enum: [ABIERTA, POR_COBRAR, PAGADA, EXONERADA]
      - name: paciente_id
        in: query
        type: integer
    responses:
      200:
        description: Cuentas con totales (cargos, descuentos, pagos, saldo)
    """
    query = CuentaPaciente.query
    if puede("cuentas.ver"):
        if request.args.get("paciente_id"):
            query = query.filter_by(paciente_id=_entero(request.args["paciente_id"]))
    else:
        propio = _paciente_propio()
        if propio is None:
            return jsonify(success=True, data=[]), 200
        query = query.filter_by(paciente_id=propio.id)
    if request.args.get("estado"):
        query = query.filter_by(estado=request.args["estado"].upper())
    lista = query.order_by(CuentaPaciente.id.desc()).limit(300).all()
    nombres, hosp = _contexto(lista)
    return jsonify(success=True, data=[_cuenta(c, nombres, hosp.get(c.hospitalizacion_id)) for c in lista]), 200


@caja_bp.route("/api/v1/salud/cuentas/<int:id>", methods=["GET"])
@validar_token
def ver_cuenta(id):
    """
    Detalle de una cuenta con sus movimientos
    ---
    tags:
      - Caja
    security:
      - BearerAuth: []
    parameters:
      - name: id
        in: path
        type: integer
        required: true
    responses:
      200:
        description: Cuenta, movimientos y día cama que corre (estancia_en_curso)
      403:
        description: No es personal autorizado ni el paciente
    """
    c = CuentaPaciente.query.get(id)
    if not puede("cuentas.ver"):
        propio = _paciente_propio()
        if not c or not propio or c.paciente_id != propio.id:
            return _error(403, "permiso_denegado", "Solo puede ver sus propias cuentas")
    if not c:
        return _error(404, "no_encontrado", "Cuenta no existe")
    return _respuesta(c)


@caja_bp.route("/api/v1/salud/cuentas", methods=["POST"])
@validar_token
@requiere_permiso("cuentas.gestionar")
def abrir_cuenta_ambulatoria():
    """
    Abrir una cuenta ambulatoria (servicios sin hospitalización)
    ---
    tags:
      - Caja
    security:
      - BearerAuth: []
    parameters:
      - in: body
        name: body
        schema:
          type: object
          required: [paciente_id]
          properties:
            paciente_id: {type: integer}
    responses:
      201:
        description: Cuenta ABIERTA
      404:
        description: Paciente no existe
      409:
        description: El paciente ya tiene una cuenta ambulatoria abierta
    """
    paciente = Paciente.query.get(_entero((request.get_json(silent=True) or {}).get("paciente_id")) or 0)
    if not paciente:
        return _error(404, "no_encontrado", "Paciente no existe")
    abierta = CuentaPaciente.query.filter_by(paciente_id=paciente.id, tipo="AMBULATORIA", estado="ABIERTA").first()
    if abierta:
        return _error(409, "cuenta_abierta", f"{paciente.nombre_completo} ya tiene la cuenta ambulatoria No. {abierta.id} abierta")
    c = CuentaPaciente(paciente_id=paciente.id, tipo="AMBULATORIA", estado="ABIERTA", saldo=0,
                       fecha_apertura=datetime.now(), abierta_por=_usuario())
    db.session.add(c)
    db.session.commit()
    return _respuesta(c, 201, "Cuenta ambulatoria abierta")


@caja_bp.route("/api/v1/salud/cuentas/<int:id>/cargos", methods=["POST"])
@validar_token
@requiere_permiso("cuentas.gestionar")
def agregar_cargo(id):
    """
    Cargar un servicio del catálogo a la cuenta
    ---
    tags:
      - Caja
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
          required: [servicio_id]
          properties:
            servicio_id: {type: integer}
            cantidad: {type: integer, example: 1}
    responses:
      201:
        description: Cargo registrado al precio vigente del catálogo
      400:
        description: Servicio inactivo, de día cama, o cantidad inválida
      409:
        description: La cuenta ya está cerrada
    """
    c, error = _cuenta_abierta(id)
    if error:
        return error
    data = request.get_json(silent=True) or {}
    s = Servicio.query.get(_entero(data.get("servicio_id")) or 0)
    if not s:
        return _error(404, "no_encontrado", "Servicio no existe")
    if s.estado == "INACTIVO":
        return _error(400, "datos_invalidos", f"{s.nombre} está inactivo")
    if s.categoria == "DIA_CAMA":
        return _error(400, "datos_invalidos", "El día cama se carga solo desde Hospitalización")
    cantidad = _entero(data.get("cantidad", 1))
    if not cantidad or not 1 <= cantidad <= 100:
        return _error(400, "datos_invalidos", "Cantidad entre 1 y 100")
    cuentas.cargar(c, s.categoria or "PROCEDIMIENTO", s.nombre, cantidad, s.costo, _usuario(), servicio_id=s.id)
    db.session.commit()
    return _respuesta(c, 201, f"{s.nombre} cargado")


@caja_bp.route("/api/v1/salud/cuentas/<int:id>/descuentos", methods=["POST"])
@validar_token
@requiere_permiso("cuentas.gestionar")
def agregar_descuento(id):
    """
    Descuento o exoneración (trabajo social)
    ---
    tags:
      - Caja
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
          required: [monto, motivo]
          properties:
            monto: {type: number, example: 200.00}
            motivo: {type: string, example: "Estudio socioeconómico No. 145"}
    responses:
      201:
        description: Descuento aplicado
      400:
        description: Monto inválido, mayor al saldo, o sin motivo
    """
    c, error = _cuenta_abierta(id)
    if error:
        return error
    data = request.get_json(silent=True) or {}
    motivo = (data.get("motivo") or "").strip()
    try:
        monto = Decimal(str(data.get("monto"))).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError):
        monto = Decimal("0")
    if monto <= 0 or not motivo:
        return _error(400, "datos_invalidos", "Indique un monto mayor a 0 y el motivo")
    if monto > Decimal(c.saldo or 0):
        return _error(400, "datos_invalidos", f"El descuento no puede ser mayor al saldo (Q{Decimal(c.saldo or 0):.2f})")
    cuentas.agregar(c, MovimientoCuenta(tipo="DESCUENTO", categoria="DESCUENTO", monto=monto,
                                        descripcion=motivo[:255], usuario=_usuario(), fecha=datetime.now()))
    db.session.commit()
    return _respuesta(c, 201, "Descuento aplicado")


@caja_bp.route("/api/v1/salud/cuentas/<int:id>/movimientos/<int:mid>/anular", methods=["POST"])
@validar_token
@requiere_permiso("cuentas.gestionar")
def anular_movimiento(id, mid):
    """
    Anular un cargo o descuento registrado por error
    ---
    tags:
      - Caja
    security:
      - BearerAuth: []
    parameters:
      - name: id
        in: path
        type: integer
        required: true
      - name: mid
        in: path
        type: integer
        required: true
      - in: body
        name: body
        schema:
          type: object
          required: [motivo]
          properties:
            motivo: {type: string, example: "Cargado a la cuenta equivocada"}
    responses:
      200:
        description: Movimiento anulado (queda en el historial, no suma)
      409:
        description: Cuenta cerrada, movimiento ya anulado o es un pago
    """
    c, error = _cuenta_abierta(id)
    if error:
        return error
    m = MovimientoCuenta.query.filter_by(id=mid, cuenta_id=c.id).first()
    if not m:
        return _error(404, "no_encontrado", "Movimiento no existe en esta cuenta")
    motivo = ((request.get_json(silent=True) or {}).get("motivo") or "").strip()
    if not motivo:
        return _error(400, "datos_invalidos", "Indique el motivo")
    if m.anulado or m.tipo == "PAGO":
        return _error(409, "estado_invalido", "Ese movimiento no se puede anular")
    m.anulado, m.motivo_anulacion = True, f"{motivo[:200]} ({_usuario()})"
    cuentas.recalcular(c)
    db.session.commit()
    return _respuesta(c, 200, "Movimiento anulado")


def _registrar_en_tributario(c, paciente, hosp):
    hoy = date.today()
    vence = c.fecha_vencimiento or hoy + timedelta(days=Config.DIAS_VENCIMIENTO_COBRO)
    if c.tipo == "HOSPITALIZACION" and hosp:
        dias = sum(m.cantidad or 0 for m in c.movimientos if m.categoria == "DIA_CAMA" and not m.anulado)
        concepto, tipo = f"Hospitalización — {hosp.sala}, {dias} {'día' if dias == 1 else 'días'}", "HOSPITALIZACION"
    else:
        concepto, tipo = "Servicios médicos ambulatorios", "SERVICIOS_MEDICOS"
    r = registrar_obligacion(c.numero_referencia, paciente.cui, tipo, concepto, c.saldo, hoy.isoformat(), vence.isoformat())
    duplicada = not r["success"] and r.get("estado_http") == 409
    if not r["success"] and not duplicada:
        return _error_modulo(r, "Tributario")
    c.fecha_vencimiento = vence
    c.estado_cobro = c.estado_cobro or "PENDIENTE"
    return None


def _marcar_pagada(c, autorizacion=None, fecha_pago=None, usuario="Tributario"):
    if c.estado == "PAGADA":
        return
    saldo = Decimal(c.saldo or 0)
    if saldo > 0:
        cuentas.agregar(c, MovimientoCuenta(
            tipo="PAGO", categoria="PAGO", monto=saldo, usuario=usuario, fecha=fecha_pago or datetime.now(),
            descripcion=f"Pago en Tributario, referencia {c.numero_referencia}"
                        + (f", autorización {autorizacion}" if autorizacion else "")))
    c.estado, c.estado_cobro = "PAGADA", "PAGADO"
    c.numero_autorizacion = autorizacion or c.numero_autorizacion
    c.fecha_pago = fecha_pago or c.fecha_pago or datetime.now()
    cuentas.recalcular(c)


@caja_bp.route("/api/v1/salud/cuentas/<int:id>/cerrar", methods=["POST"])
@validar_token
@requiere_permiso("cuentas.gestionar")
def cerrar_cuenta(id):
    """
    Cerrar la cuenta y enviar el cobro a Tributario
    ---
    tags:
      - Caja
    security:
      - BearerAuth: []
    description: >
      Una cuenta de hospitalización se cierra cuando el paciente ya egresó.
      Con saldo, se registra la obligación en Tributario (tipo HOSPITALIZACION o
      SERVICIOS_MEDICOS) y la cuenta queda POR_COBRAR. Con saldo 0, queda EXONERADA.
    parameters:
      - name: id
        in: path
        type: integer
        required: true
    responses:
      200:
        description: POR_COBRAR (con numero_referencia) o EXONERADA
      400:
        description: El paciente no tiene CUI o la cuenta no tiene cargos
      409:
        description: Cuenta cerrada, o el paciente sigue ingresado
      503:
        description: Tributario no configurado o no disponible (la cuenta sigue ABIERTA)
    """
    c, error = _cuenta_abierta(id)
    if error:
        return error
    hosp = Hospitalizacion.query.get(c.hospitalizacion_id) if c.hospitalizacion_id else None
    if hosp and hosp.estado == "ACTIVO":
        return _error(409, "paciente_ingresado", "El paciente sigue ingresado: la cuenta se cierra después del egreso")
    if not any(m.tipo == "CARGO" and not m.anulado for m in c.movimientos):
        return _error(400, "sin_cargos", "La cuenta no tiene cargos")
    paciente = Paciente.query.get(c.paciente_id)
    cuentas.recalcular(c)
    if Decimal(c.saldo or 0) == 0:
        c.estado, c.fecha_cierre, c.cerrada_por = "EXONERADA", datetime.now(), _usuario()
        db.session.commit()
        return _respuesta(c, 200, "Cuenta cerrada sin saldo (exonerada)")
    if not paciente or not paciente.cui:
        return _error(400, "datos_incompletos", "El paciente no tiene CUI registrado; Tributario lo necesita")
    if not c.numero_referencia:
        c.numero_referencia = _siguiente_referencia()
        db.session.commit()
    error = _registrar_en_tributario(c, paciente, hosp)
    if error:
        return error
    c.estado, c.fecha_cierre, c.cerrada_por = "POR_COBRAR", datetime.now(), _usuario()
    db.session.commit()
    return _respuesta(c, 200, f"Cobro enviado a Tributario: referencia {c.numero_referencia}, Q{Decimal(c.saldo):.2f}")


@caja_bp.route("/api/v1/salud/cuentas/<int:id>/verificar-pago", methods=["POST"])
@validar_token
@requiere_permiso("cuentas.gestionar")
def verificar_pago_cuenta(id):
    """
    Consultar en Tributario si la cuenta ya se pagó
    ---
    tags:
      - Caja
    security:
      - BearerAuth: []
    parameters:
      - name: id
        in: path
        type: integer
        required: true
    responses:
      200:
        description: PAGADA (con autorización) o sigue POR_COBRAR
      409:
        description: La cuenta no tiene cobro enviado
      503:
        description: Tributario no configurado o no disponible
    """
    c = CuentaPaciente.query.get(id)
    if not c:
        return _error(404, "no_encontrado", "Cuenta no existe")
    if c.estado == "PAGADA":
        return _respuesta(c, 200, "La cuenta ya está pagada")
    if c.estado != "POR_COBRAR" or not c.numero_referencia:
        return _error(409, "sin_cobro", "La cuenta todavía no se ha cerrado ni enviado a cobro")
    r = consultar_obligacion(c.numero_referencia)
    if not r["success"] and r.get("estado_http") == 404:
        # Tributario no la tiene (p. ej. se reinició): se vuelve a registrar y se consulta
        error = _registrar_en_tributario(c, Paciente.query.get(c.paciente_id),
                                         Hospitalizacion.query.get(c.hospitalizacion_id) if c.hospitalizacion_id else None)
        if error:
            return error
        r = consultar_obligacion(c.numero_referencia)
    if not r["success"]:
        return _error_modulo(r, "Tributario")
    datos = r["data"] if isinstance(r["data"], dict) else {}
    estado = str(datos.get("estado") or datos.get("estado_pago") or "PENDIENTE").upper()
    if estado in ESTADOS_PAGADO or datos.get("pagoConfirmado") is True:
        _marcar_pagada(c, datos.get("numero_autorizacion") or datos.get("numeroAutorizacion"),
                       _fecha_hora(datos.get("fecha_pago") or datos.get("fechaPago")), _usuario())
        mensaje = f"Tributario confirmó el pago de {c.numero_referencia}"
    else:
        c.estado_cobro = estado
        mensaje = f"{c.numero_referencia}: Tributario aún no registra el pago"
    db.session.commit()
    return _respuesta(c, 200, mensaje)


def aviso_de_pago(referencia, estado, autorizacion, fecha_pago):
    """Aviso de Tributario para una cuenta (lo llama POST /pagos/notificacion). None si no es una cuenta."""
    c = CuentaPaciente.query.filter_by(numero_referencia=referencia).first()
    if c is None:
        return None
    if estado == "PAGADO":
        _marcar_pagada(c, autorizacion, fecha_pago)
    elif c.estado != "PAGADA":
        # Obligación anulada en Tributario: la cuenta vuelve a ABIERTA y se reenvía con referencia nueva
        c.estado, c.estado_cobro, c.numero_referencia, c.fecha_vencimiento = "ABIERTA", None, None, None
    db.session.commit()
    return c


def resumen_cuentas():
    """Indicadores agregados (sin datos personales)."""
    hace30 = datetime.now() - timedelta(days=30)
    por_cobrar = CuentaPaciente.query.filter_by(estado="POR_COBRAR").all()
    cobrado = db.session.query(db.func.coalesce(db.func.sum(MovimientoCuenta.monto), 0)) \
        .filter(MovimientoCuenta.tipo == "PAGO", MovimientoCuenta.anulado.is_(False), MovimientoCuenta.fecha >= hace30).scalar()
    return {
        "cuentas_abiertas": CuentaPaciente.query.filter_by(estado="ABIERTA").count(),
        "cuentas_por_cobrar": len(por_cobrar),
        "monto_por_cobrar": float(sum(Decimal(c.saldo or 0) for c in por_cobrar)),
        "cobrado_30_dias": float(cobrado or 0),
    }
