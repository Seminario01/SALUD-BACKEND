from flask import Blueprint, jsonify
from auth import validar_token, requiere_rol, ROL_ADMIN, ROL_MEDICO, ROL_RECEPCION
from routes.externos import calcular_indicadores

panel_bp = Blueprint("panel", __name__)


@panel_bp.route("/api/v1/salud/panel", methods=["GET"])
@validar_token
@requiere_rol(ROL_ADMIN, ROL_MEDICO, ROL_RECEPCION)
def panel():
    """
    Resumen para el Dashboard del frontend (solo personal de Salud)
    ---
    tags:
      - Panel
    description: >
      Mismos datos que GET /indicadores, pero protegido con el token del
      usuario en lugar de la API key. La API key es solo para comunicación
      servidor a servidor entre módulos y nunca debe estar en el navegador.
    security:
      - BearerAuth: []
    responses:
      200:
        description: Indicadores del módulo
      401:
        description: Sin token o token inválido
      403:
        description: El usuario no es personal de Salud
    """
    return jsonify(success=True, data=calcular_indicadores()), 200
