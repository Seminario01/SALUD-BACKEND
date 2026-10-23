"""
Sedes del sistema (sedes.py) y la sede de cada persona del personal.

  GET /sedes                     sedes, la del usuario y la que está viendo
  GET /sedes/personal            personal que ha entrado y su sede (puestos.asignar)
  PUT /sedes/personal/<sub>      cambiar la sede de una persona {sede_id} (puestos.asignar)
"""
from datetime import datetime

from flask import Blueprint, g, jsonify, request

from auth import PUESTOS_ASIGNABLES, puede, requiere_permiso, validar_token
from extensions import db
from models import Establecimiento, PuestoAsignado, SedeUsuario, UsuarioReciente
from routes.puestos import NOMBRES, SUB
from sedes import principal_id, sede_actual, sede_propia
from validacion import entero

sedes_bp = Blueprint("sedes", __name__)


def _error(status, codigo, mensaje):
    return jsonify(success=False, error=codigo, message=mensaje), status


def _sedes():
    principal = principal_id()
    return [{"id": e.id_establecimiento, "nombre": e.nombre, "municipio": e.municipio, "departamento": e.departamento,
             "principal": e.id_establecimiento == principal}
            for e in Establecimiento.query.filter_by(es_sede=True).order_by(Establecimiento.nombre)]


@sedes_bp.route("/api/v1/salud/sedes", methods=["GET"])
@validar_token
def listar_sedes():
    """
    Sedes del sistema y la sede del usuario
    ---
    tags:
      - Sedes
    security:
      - BearerAuth: []
    description: >
      Turnos, camas, hospitalizaciones y recursos son de cada sede. Jefatura y Administración pueden ver
      otra sede o todas con el encabezado X-Sede (id o "todas"); "actual" es null cuando ven todas.
    responses:
      200:
        description: "sedes, mi_sede, actual y puede_cambiar"
    """
    return jsonify(success=True, data={"sedes": _sedes(), "mi_sede": sede_propia(), "actual": sede_actual(),
                                       "puede_cambiar": puede("sedes.cambiar")}), 200


@sedes_bp.route("/api/v1/salud/sedes/personal", methods=["GET"])
@validar_token
@requiere_permiso("puestos.asignar")
def personal_por_sede():
    """
    Personal de Salud que ha entrado al sistema y su sede
    ---
    tags:
      - Sedes
    security:
      - BearerAuth: []
    responses:
      200:
        description: "personal [{usuario_sub, usuario, nombre, puestos, sede_id, asignada}] y sedes"
    """
    asignados = {}
    for p in PuestoAsignado.query.all():
        asignados.setdefault(p.usuario_sub, []).append(p.rol)
    sedes = {s.usuario_sub: s.sede_id for s in SedeUsuario.query.all()}
    principal = principal_id()
    personal = []
    for u in UsuarioReciente.query.order_by(UsuarioReciente.nombre, UsuarioReciente.usuario):
        roles = {r for r in (u.roles or "").split(",") if r in PUESTOS_ASIGNABLES} | set(asignados.get(u.sub, []))
        if not roles:
            continue
        personal.append({"usuario_sub": u.sub, "usuario": u.usuario, "nombre": u.nombre, "email": u.email,
                         "puestos": sorted(NOMBRES.get(r, r) for r in roles),
                         "sede_id": sedes.get(u.sub, principal), "asignada": u.sub in sedes})
    return jsonify(success=True, data={"personal": personal, "sedes": _sedes()}), 200


@sedes_bp.route("/api/v1/salud/sedes/personal/<sub>", methods=["PUT"])
@validar_token
@requiere_permiso("puestos.asignar")
def cambiar_sede(sub):
    """
    Cambiar la sede donde trabaja una persona
    ---
    tags:
      - Sedes
    security:
      - BearerAuth: []
    parameters:
      - {name: sub, in: path, type: string, required: true}
      - in: body
        name: body
        required: true
        schema:
          type: object
          required: [sede_id]
          properties:
            sede_id: {type: integer}
    responses:
      200:
        description: Sede cambiada
      400:
        description: Código o sede inválidos
    """
    sub = sub.lower()
    if not SUB.fullmatch(sub):
        return _error(400, "datos_invalidos", "El código del usuario no es válido")
    sede_id = entero(request.get_json(silent=True) or {}, "sede_id", 1, 2_147_483_647, obligatorio=True, etiqueta="La sede")
    sede = Establecimiento.query.get(sede_id)
    if not sede or not sede.es_sede:
        return _error(400, "datos_invalidos", "Elija una de las sedes del sistema")
    fila = SedeUsuario.query.get(sub) or SedeUsuario(usuario_sub=sub)
    fila.sede_id, fila.fecha = sede.id_establecimiento, datetime.now()
    fila.asignado_por = (g.usuario.get("nombre") or g.usuario.get("usuario") or "")[:150] or None
    db.session.add(fila)
    db.session.commit()
    conocido = UsuarioReciente.query.get(sub)
    quien = (conocido.usuario or conocido.nombre) if conocido else sub[:8]
    return jsonify(success=True, data={"usuario_sub": sub, "sede_id": sede.id_establecimiento,
                                       "detalle": f"{sede.nombre} a {quien}"},
                   message=f"{quien} trabaja ahora en {sede.nombre}. Lo verá al recargar la página."), 200
