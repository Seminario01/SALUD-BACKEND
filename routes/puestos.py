"""
Puestos asignados en Salud (Administración, permiso puestos.asignar).

Un usuario del Login Único sin rol de Salud (por ejemplo, un compañero que entra como ciudadano)
recibe aquí un puesto que vale solo dentro de este módulo. auth.py lo suma a los roles de su token.

  GET    /puestos/asignados        puestos asignados y personas que entraron sin puesto de Salud
  POST   /puestos/asignados        asignar  {usuario_sub, rol, nota?}
  DELETE /puestos/asignados/<id>   quitar

Nadie puede asignarse ni quitarse su propio puesto. Cada cambio queda en la bitácora de accesos.
"""
import re
from datetime import datetime, timedelta

from flask import Blueprint, g, jsonify, request

from auth import PUESTOS_ASIGNABLES, olvidar_puestos, requiere_permiso, validar_token
from extensions import db
from models import PuestoAsignado, UsuarioReciente
from validacion import texto

puestos_bp = Blueprint("puestos", __name__)
NOMBRES = {"salud:medico": "Médico", "salud:enfermeria": "Enfermería", "salud:recepcion": "Recepción",
           "salud:farmacia": "Farmacia", "salud:caja": "Caja", "salud:jefatura": "Jefatura médica",
           "salud:admin": "Administración"}
SUB = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
DIAS_RECIENTES = 30


def _error(status, codigo, mensaje):
    return jsonify(success=False, error=codigo, message=mensaje), status


def _persona(p):
    return {"id": p.id, "usuario_sub": p.usuario_sub, "rol": p.rol, "puesto": NOMBRES.get(p.rol, p.rol),
            "usuario": p.usuario, "nombre": p.nombre, "email": p.email, "nota": p.nota,
            "asignado_por": p.asignado_por, "fecha": p.fecha.isoformat() if p.fecha else None}


def _yo():
    return (g.usuario.get("nombre") or g.usuario.get("usuario") or "")[:150] or None


@puestos_bp.route("/api/v1/salud/puestos/asignados", methods=["GET"])
@validar_token
@requiere_permiso("puestos.asignar")
def listar_puestos():
    """
    Puestos asignados en Salud y personas que entraron sin puesto
    ---
    tags:
      - Puestos
    security:
      - BearerAuth: []
    responses:
      200:
        description: "asignados, recientes (entraron en los últimos 30 días sin rol de Salud) y puestos posibles"
    """
    asignados = PuestoAsignado.query.order_by(PuestoAsignado.fecha.desc()).all()
    con_puesto = {p.usuario_sub for p in asignados}
    desde = datetime.now() - timedelta(days=DIAS_RECIENTES)
    recientes = []
    for u in UsuarioReciente.query.filter(UsuarioReciente.ultimo_acceso >= desde).order_by(UsuarioReciente.ultimo_acceso.desc()).limit(200):
        roles = [r for r in (u.roles or "").split(",") if r]
        if u.sub in con_puesto or any(r in PUESTOS_ASIGNABLES or r.startswith("auditoria:") for r in roles):
            continue
        recientes.append({"usuario_sub": u.sub, "usuario": u.usuario, "nombre": u.nombre, "email": u.email,
                          "roles": roles, "ultimo_acceso": u.ultimo_acceso.isoformat() if u.ultimo_acceso else None})
    return jsonify(success=True, data={
        "asignados": [_persona(p) for p in asignados], "recientes": recientes,
        "puestos": [{"rol": r, "nombre": NOMBRES[r]} for r in PUESTOS_ASIGNABLES],
    }), 200


@puestos_bp.route("/api/v1/salud/puestos/asignados", methods=["POST"])
@validar_token
@requiere_permiso("puestos.asignar")
def asignar_puesto():
    """
    Asignar un puesto de Salud a una cuenta del Login Único
    ---
    tags:
      - Puestos
    security:
      - BearerAuth: []
    parameters:
      - in: body
        name: body
        required: true
        schema:
          type: object
          required: [usuario_sub, rol]
          properties:
            usuario_sub: {type: string, description: "Código del usuario (sub), el que muestra 'Mi resumen'"}
            rol: {type: string, example: "salud:jefatura"}
            nota: {type: string}
    responses:
      201:
        description: Puesto asignado
      400:
        description: Código o puesto inválido
      403:
        description: Sin permiso, o es su propio usuario
      409:
        description: Ya tiene ese puesto
    """
    data = request.get_json(silent=True) or {}
    sub = (texto(data, "usuario_sub", 36, obligatorio=True, etiqueta="El código del usuario") or "").lower()
    if not SUB.fullmatch(sub):
        return _error(400, "datos_invalidos", "El código del usuario tiene 36 caracteres, como el que muestra 'Mi resumen'")
    rol = texto(data, "rol", 40, obligatorio=True, etiqueta="El puesto")
    if rol not in PUESTOS_ASIGNABLES:
        return _error(400, "datos_invalidos", f"El puesto debe ser uno de: {', '.join(PUESTOS_ASIGNABLES)}")
    if sub == g.usuario["sub"].lower():
        return _error(403, "propio_usuario", "No puede cambiar su propio puesto: pídaselo a otra persona de Administración")
    if PuestoAsignado.query.filter_by(usuario_sub=sub, rol=rol).first():
        return _error(409, "ya_existe", "Esa persona ya tiene ese puesto")
    conocido = UsuarioReciente.query.get(sub)
    p = PuestoAsignado(usuario_sub=sub, rol=rol, nota=texto(data, "nota", 255, etiqueta="La nota"),
                       usuario=conocido.usuario if conocido else None, nombre=conocido.nombre if conocido else None,
                       email=conocido.email if conocido else None, asignado_por=_yo(),
                       asignado_por_sub=g.usuario["sub"], fecha=datetime.now())
    db.session.add(p)
    db.session.commit()
    olvidar_puestos(sub)
    quien = p.usuario or p.nombre or sub[:8]
    return jsonify(success=True, data={**_persona(p), "detalle": f"{NOMBRES[rol]} a {quien}"},
                   message=f"Puesto {NOMBRES[rol]} asignado. Lo verá al recargar la página."), 201


@puestos_bp.route("/api/v1/salud/puestos/asignados/<int:id>", methods=["DELETE"])
@validar_token
@requiere_permiso("puestos.asignar")
def quitar_puesto(id):
    """
    Quitar un puesto asignado en Salud
    ---
    tags:
      - Puestos
    security:
      - BearerAuth: []
    parameters:
      - {name: id, in: path, type: integer, required: true}
    responses:
      200:
        description: Quitado
      403:
        description: Es su propio puesto
      404:
        description: No existe
    """
    p = PuestoAsignado.query.get(id)
    if not p:
        return _error(404, "no_encontrado", "Ese puesto asignado no existe")
    if p.usuario_sub == g.usuario["sub"].lower():
        return _error(403, "propio_usuario", "No puede quitarse su propio puesto: pídaselo a otra persona de Administración")
    datos = {**_persona(p), "detalle": f"{NOMBRES.get(p.rol, p.rol)} a {p.usuario or p.nombre or p.usuario_sub[:8]}"}
    db.session.delete(p)
    db.session.commit()
    olvidar_puestos(p.usuario_sub)
    return jsonify(success=True, data=datos, message="Puesto quitado"), 200
