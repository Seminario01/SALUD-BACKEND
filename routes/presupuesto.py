from flask import Blueprint, request, jsonify
from extensions import db
from models import PresupuestoHospitalario
from auth import validar_token, requiere_rol, validar_api_key

presupuesto_bp = Blueprint("presupuesto", __name__)

@presupuesto_bp.route("/api/v1/salud/presupuesto", methods=["PUT"])
@validar_token
@requiere_rol("admin")
def actualizar_presupuesto():
    data = request.get_json()
    presupuesto = PresupuestoHospitalario.query.filter_by(periodo=data["periodo"]).first()
    if not presupuesto:
        presupuesto = PresupuestoHospitalario(periodo=data["periodo"])
        db.session.add(presupuesto)

    presupuesto.monto_asignado = data["monto_asignado"]
    presupuesto.monto_ejecutado_servicio_social = data.get("monto_ejecutado_servicio_social", 0)
    db.session.commit()

    return jsonify(success=True, data={"id": presupuesto.id}, message="Presupuesto actualizado"), 200


@presupuesto_bp.route("/api/v1/salud/presupuesto/ejecucion", methods=["GET"])
@validar_api_key
def ejecucion_presupuesto():
    periodo = request.args.get("periodo")
    query = PresupuestoHospitalario.query
    if periodo:
        query = query.filter_by(periodo=periodo)
    presupuesto = query.order_by(PresupuestoHospitalario.id.desc()).first()

    if not presupuesto:
        return jsonify(success=False, error="no_encontrado", message="No hay datos de presupuesto"), 404

    porcentaje = 0
    if presupuesto.monto_asignado:
        porcentaje = round(float(presupuesto.monto_ejecutado_servicio_social) / float(presupuesto.monto_asignado) * 100, 2)

    return jsonify(success=True, data={
        "periodo": presupuesto.periodo,
        "monto_asignado": float(presupuesto.monto_asignado),
        "monto_ejecutado_servicio_social": float(presupuesto.monto_ejecutado_servicio_social),
        "porcentaje_ejecutado": porcentaje,
    }), 200