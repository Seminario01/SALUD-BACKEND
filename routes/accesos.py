from datetime import datetime, timedelta

from flask import Blueprint, jsonify, request

from auth import requiere_permiso, validar_token
from extensions import db
from models import BitacoraAcceso, Paciente

accesos_bp = Blueprint("accesos", __name__)
ACCIONES = ("ver", "crear", "modificar", "anular")


def _fecha(nombre):
    valor = request.args.get(nombre)
    if not valor:
        return None
    try:
        return datetime.strptime(valor, "%Y-%m-%d")
    except ValueError:
        return False


@accesos_bp.route("/api/v1/salud/bitacora/accesos", methods=["GET"])
@validar_token
@requiere_permiso("bitacora.ver")
def bitacora_accesos():
    """
    Bitácora de accesos: quién vio o modificó datos de pacientes, y cuándo
    ---
    tags:
      - Bitácora
    security:
      - BearerAuth: []
    description: >
      Solo Administración. Se registra cada consulta a los datos de un paciente
      (ficha, expediente, vacunación, antecedentes, receta, cuenta, hospitalización)
      y todo cambio que terminó bien. Del más reciente al más antiguo.
    parameters:
      - {name: paciente_id, in: query, type: integer}
      - {name: usuario, in: query, type: string, description: "Parte del usuario o del nombre"}
      - {name: accion, in: query, type: string, enum: [ver, crear, modificar, anular]}
      - {name: desde, in: query, type: string, format: date}
      - {name: hasta, in: query, type: string, format: date}
      - {name: limite, in: query, type: integer, default: 200, description: "Máximo 1000"}
    responses:
      200:
        description: Registros, totales por acción y total que coincide con el filtro
      400:
        description: Fecha o acción inválida
    """
    q = BitacoraAcceso.query
    paciente = request.args.get("paciente_id", "")
    if paciente:
        if not paciente.isdigit():
            return jsonify(success=False, error="datos_invalidos", message="paciente_id debe ser un número"), 400
        q = q.filter(BitacoraAcceso.paciente_id == int(paciente))
    usuario = request.args.get("usuario", "").strip()[:100]
    if usuario:
        patron = f"%{usuario}%"
        q = q.filter(db.or_(BitacoraAcceso.usuario.like(patron), BitacoraAcceso.nombre.like(patron)))
    desde, hasta = _fecha("desde"), _fecha("hasta")
    if desde is False or hasta is False:
        return jsonify(success=False, error="datos_invalidos", message="Las fechas van como AAAA-MM-DD"), 400
    if desde:
        q = q.filter(BitacoraAcceso.fecha >= desde)
    if hasta:
        q = q.filter(BitacoraAcceso.fecha < hasta + timedelta(days=1))

    totales = dict(q.with_entities(BitacoraAcceso.accion, db.func.count()).group_by(BitacoraAcceso.accion).all())
    accion = request.args.get("accion", "")
    if accion:
        if accion not in ACCIONES:
            return jsonify(success=False, error="datos_invalidos",
                           message=f"accion debe ser una de: {', '.join(ACCIONES)}"), 400
        q = q.filter(BitacoraAcceso.accion == accion)
    try:
        limite = max(1, min(int(request.args.get("limite", 200)), 1000))
    except ValueError:
        limite = 200

    total = q.count()
    registros = q.order_by(BitacoraAcceso.id.desc()).limit(limite).all()
    ids = {r.paciente_id for r in registros if r.paciente_id}
    nombres = dict(db.session.query(Paciente.id, Paciente.nombre_completo).filter(Paciente.id.in_(ids)).all()) if ids else {}
    return jsonify(success=True, total=total, totales={a: totales.get(a, 0) for a in ACCIONES}, data=[{
        "id": r.id, "fecha": r.fecha.isoformat(timespec="seconds"), "usuario": r.usuario, "nombre": r.nombre,
        "puesto": r.puesto, "accion": r.accion, "descripcion": r.descripcion, "paciente_id": r.paciente_id,
        "paciente": nombres.get(r.paciente_id), "metodo": r.metodo, "ruta": r.ruta, "ip": r.ip,
    } for r in registros]), 200
