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


# ------------------------------------------------------------------------------------------
# Accesos inusuales: patrones que conviene que Administración revise (no bloquean a nadie)
NOCHE = (22, 6)                                       # de 22:00 a 5:59
PUESTOS_DE_DIA = ("Recepción", "Caja", "Administración", "Jefatura médica")   # enfermería y médicos hacen turnos de noche


def _umbral(nombre, defecto, minimo, maximo):
    valor = request.args.get(nombre, "")
    if not valor:
        return defecto
    if not valor.isdigit() or not minimo <= int(valor) <= maximo:
        raise ValueError(f"{nombre} debe ser un número entre {minimo} y {maximo}")
    return int(valor)


@accesos_bp.route("/api/v1/salud/bitacora/inusuales", methods=["GET"])
@validar_token
@requiere_permiso("bitacora.ver")
def accesos_inusuales():
    """
    Accesos inusuales en la bitácora (para revisar)
    ---
    tags:
      - Bitácora
    security:
      - BearerAuth: []
    description: >
      Solo Administración. Busca en los últimos `dias` (sin contar a los ciudadanos):
      muchos pacientes distintos vistos por una persona en una misma hora (posible consulta masiva),
      muchas anulaciones de una persona en un día, accesos de noche (22:00 a 5:59) de puestos
      que trabajan de día (Recepción, Caja, Administración, Jefatura) y una persona entrando desde
      muchas direcciones IP en un día. Solo avisa: no bloquea a nadie.
    parameters:
      - {name: dias, in: query, type: integer, default: 7, description: "1 a 31"}
      - {name: pacientes_por_hora, in: query, type: integer, default: 25, description: "2 a 500"}
      - {name: anulaciones_por_dia, in: query, type: integer, default: 5, description: "2 a 200"}
      - {name: ips_por_dia, in: query, type: integer, default: 4, description: "2 a 50"}
    responses:
      200:
        description: "[{tipo, nivel alto|medio, usuario, nombre, puesto, desde, hasta, cantidad, texto}], primero los de nivel alto"
      400:
        description: Algún número fuera de rango
    """
    try:
        dias = _umbral("dias", 7, 1, 31)
        por_hora = _umbral("pacientes_por_hora", 25, 2, 500)
        por_dia = _umbral("anulaciones_por_dia", 5, 2, 200)
        ips_dia = _umbral("ips_por_dia", 4, 2, 50)
    except ValueError as error:
        return jsonify(success=False, error="datos_invalidos", message=str(error)), 400

    B = BitacoraAcceso
    inicio = datetime.combine(datetime.now().date() - timedelta(days=dias - 1), datetime.min.time())
    personal = db.and_(B.fecha >= inicio, db.or_(B.puesto.is_(None), B.puesto != "Ciudadano"))
    dia, hora = db.func.date(B.fecha), db.func.hour(B.fecha)
    alertas = []

    def agregar(tipo, nivel, fila, desde, hasta, texto):
        alertas.append({"tipo": tipo, "nivel": nivel, "usuario": fila.usuario, "nombre": fila.nombre,
                        "puesto": fila.puesto, "desde": desde.isoformat(timespec="minutes"),
                        "hasta": hasta.isoformat(timespec="minutes"), "cantidad": int(fila.cantidad), "texto": texto})

    def columnas(*extra, contar):
        return [B.usuario, db.func.max(B.nombre).label("nombre"), db.func.max(B.puesto).label("puesto"),
                *extra, contar.label("cantidad")]

    # 1) Muchos pacientes distintos en una misma hora
    filas = (db.session.query(*columnas(dia.label("dia"), hora.label("hora"), contar=db.func.count(db.distinct(B.paciente_id))))
             .filter(personal, B.accion == "ver", B.paciente_id.isnot(None))
             .group_by(B.usuario, dia, hora).having(db.func.count(db.distinct(B.paciente_id)) >= por_hora).all())
    for f in filas:
        desde = datetime.combine(f.dia, datetime.min.time()) + timedelta(hours=int(f.hora))
        agregar("muchos_pacientes", "alto", f, desde, desde + timedelta(minutes=59),
                f"Vio los datos de {f.cantidad} pacientes distintos en una hora")

    # 2) Muchas anulaciones en un día
    filas = (db.session.query(*columnas(dia.label("dia"), contar=db.func.count()))
             .filter(personal, B.accion == "anular").group_by(B.usuario, dia).having(db.func.count() >= por_dia).all())
    for f in filas:
        desde = datetime.combine(f.dia, datetime.min.time())
        agregar("muchas_anulaciones", "alto", f, desde, desde + timedelta(hours=23, minutes=59),
                f"Anuló {f.cantidad} registros en un día (recetas, cobros, citas...)")

    # 3) De noche, solo puestos que trabajan de día
    filas = (db.session.query(*columnas(dia.label("dia"), db.func.min(B.fecha).label("primero"),
                                        db.func.max(B.fecha).label("ultimo"), contar=db.func.count()))
             .filter(personal, B.puesto.in_(PUESTOS_DE_DIA), db.or_(hora >= NOCHE[0], hora < NOCHE[1]))
             .group_by(B.usuario, dia).all())
    for f in filas:
        agregar("noche", "medio", f, f.primero, f.ultimo,
                f"{f.cantidad} acceso(s) de noche, entre las 22:00 y las 6:00 ({f.puesto} normalmente trabaja de día)")

    # 4) Muchas direcciones IP en un día
    filas = (db.session.query(*columnas(dia.label("dia"), contar=db.func.count(db.distinct(B.ip))))
             .filter(personal, B.ip.isnot(None)).group_by(B.usuario, dia)
             .having(db.func.count(db.distinct(B.ip)) >= ips_dia).all())
    for f in filas:
        desde = datetime.combine(f.dia, datetime.min.time())
        agregar("muchas_ips", "medio", f, desde, desde + timedelta(hours=23, minutes=59),
                f"Entró desde {f.cantidad} direcciones IP distintas en un día (¿cuenta compartida?)")

    alertas.sort(key=lambda a: a["desde"], reverse=True)       # lo más reciente primero...
    alertas.sort(key=lambda a: a["nivel"] != "alto")          # ...y los de nivel alto arriba
    return jsonify(success=True, desde=inicio.date().isoformat(), data=alertas,
                   umbrales={"dias": dias, "pacientes_por_hora": por_hora, "anulaciones_por_dia": por_dia,
                             "ips_por_dia": ips_dia}), 200
