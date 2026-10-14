import re
from flask import Blueprint, request, jsonify
from extensions import db
from models import PresupuestoHospitalario
from auth import validar_token, requiere_permiso, validar_api_key, validar_api_key_o_token, PERMISOS
from validacion import monto, texto

presupuesto_bp = Blueprint("presupuesto", __name__)

@presupuesto_bp.route("/api/v1/salud/presupuesto", methods=["PUT"])
@validar_token
@requiere_permiso("presupuesto.editar")
def actualizar_presupuesto():
    data = request.get_json(silent=True) or {}
    periodo = texto(data, "periodo", 20, obligatorio=True, etiqueta="El periodo")
    if not re.fullmatch(r"\d{4}(-(Q[1-4]|0[1-9]|1[0-2]))?", periodo):
        return jsonify(success=False, error="datos_invalidos",
                       message="El periodo debe ser AAAA, AAAA-MM o AAAA-Q1..Q4 (por ejemplo 2026-Q4)"), 400
    asignado = monto(data.get("monto_asignado"), "El monto asignado")
    ejecutado = monto(data.get("monto_ejecutado_servicio_social") or 0, "El monto ejecutado")
    if ejecutado > asignado:
        return jsonify(success=False, error="datos_invalidos",
                       message="El monto ejecutado no puede ser mayor al asignado"), 400
    data["periodo"] = periodo
    presupuesto = PresupuestoHospitalario.query.filter_by(periodo=data["periodo"]).first()
    if not presupuesto:
        presupuesto = PresupuestoHospitalario(periodo=data["periodo"])
        db.session.add(presupuesto)

    presupuesto.monto_asignado = asignado
    presupuesto.monto_ejecutado_servicio_social = ejecutado
    db.session.commit()

    return jsonify(success=True, data={"id": presupuesto.id}, message="Presupuesto actualizado"), 200


@presupuesto_bp.route("/api/v1/salud/presupuesto/ejecucion", methods=["GET"])
@validar_api_key_o_token(*PERMISOS["presupuesto.ver"])
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