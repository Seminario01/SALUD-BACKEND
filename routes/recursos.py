from flask import Blueprint, request, jsonify
from extensions import db
from models import RecursoHospitalario
from auth import validar_token, requiere_rol

recursos_bp = Blueprint("recursos", __name__)

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
@requiere_rol("admin")
def actualizar_recurso(id):
    recurso = RecursoHospitalario.query.get(id)
    if not recurso:
        return jsonify(success=False, error="no_encontrado", message="Recurso no existe"), 404

    data = request.get_json()
    if "disponible" in data:
        recurso.disponible = data["disponible"]
    if "total" in data:
        recurso.total = data["total"]
    if "descripcion" in data:
        recurso.descripcion = data["descripcion"]

    db.session.commit()
    return jsonify(success=True, data={"id": recurso.id}, message="Recurso actualizado"), 200


@recursos_bp.route("/api/v1/salud/recursos", methods=["POST"])
@validar_token
@requiere_rol("admin")
def crear_recurso():
    data = request.get_json()
    recurso = RecursoHospitalario(
        tipo=data["tipo"],
        descripcion=data.get("descripcion"),
        disponible=data.get("disponible", 0),
        total=data.get("total", 0),
    )
    db.session.add(recurso)
    db.session.commit()
    return jsonify(success=True, data={"id": recurso.id}, message="Recurso creado"), 201