"""
Ajustes a la matriz de permisos (Administración, permiso permisos.editar).

  GET    /permisos            matriz original, vigente y los ajustes (quién y cuándo)
  PUT    /permisos            agregar o quitar un permiso a un puesto  {permiso, rol, concedido}
  DELETE /permisos/ajustes    volver a la matriz original

Solo los puestos de Salud (no Auditoría ni el ciudadano). A Administración no se le quitan
permisos.editar ni puestos.asignar (auth.PROTEGIDOS). Cada cambio queda en la bitácora de accesos.
"""
from datetime import datetime

from flask import Blueprint, g, jsonify, request

from auth import PERMISOS, PROTEGIDOS, ROLES_PERSONAL, es_personal, matriz_vigente, requiere_permiso, validar_token
from extensions import db
from models import PermisoAjuste
from routes.puestos import NOMBRES
from validacion import booleano, texto

permisos_bp = Blueprint("permisos", __name__)


def _error(status, codigo, mensaje):
    return jsonify(success=False, error=codigo, message=mensaje), status


@permisos_bp.route("/api/v1/salud/permisos", methods=["GET"])
@validar_token
def ver_permisos():
    """
    Matriz de permisos: la original, la vigente y los ajustes de Administración
    ---
    tags:
      - Permisos
    security:
      - BearerAuth: []
    responses:
      200:
        description: "original, vigente, ajustes [{permiso, rol, concedido, cambiado_por, fecha}], editables y protegidos"
      403:
        description: Solo personal de Salud
    """
    if not es_personal():
        return _error(403, "permiso_denegado", "Solo el personal de Salud ve la matriz de permisos")
    return jsonify(success=True, data={
        "original": {p: list(r) for p, r in PERMISOS.items()},
        "vigente": {p: list(r) for p, r in matriz_vigente().items()},
        "ajustes": [{"permiso": a.permiso, "rol": a.rol, "concedido": a.concedido, "cambiado_por": a.cambiado_por,
                     "fecha": a.fecha.isoformat()} for a in PermisoAjuste.query.order_by(PermisoAjuste.fecha.desc())],
        "editables": list(ROLES_PERSONAL),
        "protegidos": [list(p) for p in sorted(PROTEGIDOS)],
    }), 200


@permisos_bp.route("/api/v1/salud/permisos", methods=["PUT"])
@validar_token
@requiere_permiso("permisos.editar")
def cambiar_permiso():
    """
    Agregar o quitar un permiso a un puesto de Salud
    ---
    tags:
      - Permisos
    security:
      - BearerAuth: []
    description: >
      Vale para todas las personas con ese puesto, al recargar la página. Si el cambio deja el permiso
      como en la matriz original, el ajuste se borra.
    parameters:
      - in: body
        name: body
        required: true
        schema:
          type: object
          required: [permiso, rol, concedido]
          properties:
            permiso: {type: string, example: "pacientes.antecedentes"}
            rol: {type: string, example: "salud:admin"}
            concedido: {type: boolean}
    responses:
      200:
        description: Cambiado
      400:
        description: Permiso o puesto desconocido
      409:
        description: Permiso protegido de Administración
    """
    data = request.get_json(silent=True) or {}
    permiso = texto(data, "permiso", 60, obligatorio=True, etiqueta="El permiso")
    rol = texto(data, "rol", 40, obligatorio=True, etiqueta="El puesto")
    concedido = booleano(data, "concedido")
    if permiso not in PERMISOS:
        return _error(400, "datos_invalidos", "Ese permiso no existe")
    if rol not in ROLES_PERSONAL:
        return _error(400, "datos_invalidos", "Solo se cambian permisos de los puestos de Salud")
    if (permiso, rol) in PROTEGIDOS:
        return _error(409, "protegido", "Administración siempre conserva este permiso, para no quedar sin acceso")
    ajuste = PermisoAjuste.query.filter_by(permiso=permiso, rol=rol).first()
    if concedido == (rol in PERMISOS[permiso]):
        if ajuste:                                   # vuelve a ser como en la matriz original
            db.session.delete(ajuste)
    else:
        ajuste = ajuste or PermisoAjuste(permiso=permiso, rol=rol)
        ajuste.concedido, ajuste.fecha = concedido, datetime.now()
        ajuste.cambiado_por = (g.usuario.get("nombre") or g.usuario.get("usuario") or "")[:150] or None
        db.session.add(ajuste)
    db.session.commit()
    accion = "agregó" if concedido else "quitó"
    return jsonify(success=True, data={"permiso": permiso, "rol": rol, "concedido": concedido,
                                       "detalle": f"{NOMBRES.get(rol, rol)} {accion} {permiso}"},
                   message=f"Permiso {'agregado a' if concedido else 'quitado a'} {NOMBRES.get(rol, rol)}. "
                           "Se aplica al recargar la página."), 200


@permisos_bp.route("/api/v1/salud/permisos/ajustes", methods=["DELETE"])
@validar_token
@requiere_permiso("permisos.editar")
def restablecer_permisos():
    """
    Volver a la matriz de permisos original (borra todos los ajustes)
    ---
    tags:
      - Permisos
    security:
      - BearerAuth: []
    responses:
      200:
        description: Matriz original restablecida
    """
    n = PermisoAjuste.query.delete()
    db.session.commit()
    return jsonify(success=True, data={"borrados": n}, message="Se restableció la matriz original."), 200
