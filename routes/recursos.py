from flask import Blueprint, request, jsonify
from extensions import db
from models import RecursoHospitalario
from auth import validar_token, requiere_rol, ROL_ADMIN

recursos_bp = Blueprint("recursos", __name__)

TIPOS_RECURSO = ("cama", "ambulancia", "cupo_consulta")


def _validar_cantidades(disponible, total):
    """Devuelve un mensaje de error o None."""
    try:
        disponible, total = int(disponible), int(total)
    except (TypeError, ValueError):
        return "disponible y total deben ser números enteros"
    if disponible < 0 or total < 0:
        return "Las cantidades no pueden ser negativas"
    if disponible > total:
        return "No puede haber más disponibles que el total"
    return None



@recursos_bp.route("/api/v1/salud/recursos", methods=["GET"])
@validar_token
def listar_recursos():
    recursos = RecursoHospitalario.query.all()
    return jsonify(success=True, data=[{
        "id": r.id,
        "tipo": r.tipo,
        "descripcion": r.descripcion,
        "disponible": r.disponible,
        "total": r.total,
    } for r in recursos]), 200


@recursos_bp.route("/api/v1/salud/recursos/<int:id>", methods=["PUT"])
@validar_token
@requiere_rol(ROL_ADMIN)
def actualizar_recurso(id):
    recurso = RecursoHospitalario.query.get(id)
    if not recurso:
        return jsonify(success=False, error="no_encontrado", message="Recurso no existe"), 404

    data = request.get_json() or {}
    error = _validar_cantidades(data.get("disponible", recurso.disponible), data.get("total", recurso.total))
    if error:
        return jsonify(success=False, error="datos_invalidos", message=error), 400
    if "disponible" in data:
        recurso.disponible = int(data["disponible"])
    if "total" in data:
        recurso.total = int(data["total"])
    if "descripcion" in data:
        recurso.descripcion = data["descripcion"]

    db.session.commit()
    return jsonify(success=True, data={"id": recurso.id}, message="Recurso actualizado"), 200


@recursos_bp.route("/api/v1/salud/recursos", methods=["POST"])
@validar_token
@requiere_rol(ROL_ADMIN)
def crear_recurso():
    data = request.get_json() or {}
    if data.get("tipo") not in TIPOS_RECURSO:
        return jsonify(success=False, error="datos_invalidos",
                       message=f"tipo debe ser uno de: {', '.join(TIPOS_RECURSO)}"), 400
    error = _validar_cantidades(data.get("disponible", 0), data.get("total", 0))
    if error:
        return jsonify(success=False, error="datos_invalidos", message=error), 400
    recurso = RecursoHospitalario(
        tipo=data["tipo"],
        descripcion=data.get("descripcion"),
        disponible=int(data.get("disponible", 0)),
        total=int(data.get("total", 0)),
    )
    db.session.add(recurso)
    db.session.commit()
    return jsonify(success=True, data={"id": recurso.id}, message="Recurso creado"), 201