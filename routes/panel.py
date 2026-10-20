import json
import logging
from datetime import date, datetime, timedelta

from flask import Blueprint, jsonify, g
from sqlalchemy import text

import laboratorio

from auth import validar_token, requiere_permiso, permisos_de, puede, PERMISOS
from extensions import db
from routes.externos import calcular_indicadores

panel_bp = Blueprint("panel", __name__)
log = logging.getLogger(__name__)


@panel_bp.route("/api/v1/salud/estado", methods=["GET"])
def estado_del_servicio():
    """
    ¿Está funcionando el módulo? (público, para el monitor externo)
    ---
    tags:
      - Panel
    description: >
      Sin token. Responde 200 solo si el backend funciona Y la base de datos contesta.
      Lo consulta un monitor externo (UptimeRobot) cada 5 minutos para avisar si el sitio se cae.
      No da ningún dato del sistema ni de pacientes.
    responses:
      200:
        description: '{"estado": "ok"}'
      503:
        description: La base de datos no responde
    """
    try:
        db.session.execute(text("SELECT 1"))
    except Exception as error:  # noqa: BLE001
        log.error("Estado: la base de datos no responde: %s", error)
        db.session.rollback()
        respuesta = jsonify(success=False, estado="sin_base_de_datos", message="La base de datos no responde")
        respuesta.headers["Cache-Control"] = "no-store"
        return respuesta, 503
    respuesta = jsonify(success=True, estado="ok")
    respuesta.headers["Cache-Control"] = "no-store"
    return respuesta, 200


@panel_bp.route("/api/v1/salud/panel", methods=["GET"])
@validar_token
@requiere_permiso("panel.ver")
def panel():
    """
    Resumen para el Dashboard (personal de Salud y Auditoría Social, solo lectura)
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
        description: El usuario no es personal de Salud ni de Auditoría
    """
    datos = calcular_indicadores()
    if not puede("presupuesto.ver"):          # matriz: solo Jefatura, Administración y Auditoría
        datos.pop("presupuesto_servicio_social", None)
    # Solo para la pantalla de inicio (no va en /indicadores, el contrato con Auditoría no cambia)
    datos["atencion_hoy"] = _atencion_hoy()
    return jsonify(success=True, data=datos), 200


def _atencion_hoy():
    """Lo que hay que atender ya: urgencias en la cola, laboratorio, resultados fuera de rango y
    lista de espera. Cada parte solo para quien puede ver esa pantalla."""
    from models import ListaEspera, OrdenLaboratorio, Turno
    from routes.turnos import TRIAGE
    hoy = datetime.combine(date.today(), datetime.min.time())
    ahora = datetime.now()
    resumen = {}
    if puede("turnos.ver_cola"):
        espera = Turno.query.filter(Turno.estado == "en_espera", Turno.fecha_hora_ingreso >= hoy).all()
        urgentes = [t for t in espera if t.triage in ("ROJO", "NARANJA")]
        resumen["triage"] = {
            "urgentes_en_espera": len(urgentes),
            "rojos_en_espera": sum(1 for t in urgentes if t.triage == "ROJO"),
            "sin_clasificar": sum(1 for t in espera if not t.triage),
            # esperando más de lo recomendado para su nivel
            "excedidos": sum(1 for t in espera if t.triage in TRIAGE and t.fecha_hora_ingreso
                             and (ahora - t.fecha_hora_ingreso).total_seconds() / 60 > TRIAGE[t.triage]["minutos"]),
        }
    if puede("laboratorio.ver"):
        activas = OrdenLaboratorio.query.filter(OrdenLaboratorio.estado.in_(("PENDIENTE", "EN_PROCESO"))).all()
        semana = OrdenLaboratorio.query.filter(OrdenLaboratorio.estado == "COMPLETADA",
                                               OrdenLaboratorio.fecha_resultado >= ahora - timedelta(days=7)).all()

        def fuera(o):
            return any(r["nivel"] in ("alto", "bajo", "anormal")
                       for e in o.examenes
                       for r in laboratorio.resultados_interpretados(e.codigo, json.loads(e.resultados) if e.resultados else {}))
        resumen["laboratorio"] = {
            "por_atender": len(activas),
            "urgentes": sum(1 for o in activas if o.prioridad == "URGENTE"),
            "muestras_tomadas": sum(1 for o in activas if o.estado == "EN_PROCESO"),
            "completadas_7_dias": len(semana),
            "con_valores_fuera_de_rango_7_dias": sum(1 for o in semana if fuera(o)),
        }
    if puede("citas.ver"):
        activos = ListaEspera.query.filter(ListaEspera.estado.in_(("ESPERANDO", "AVISADO"))).all()
        resumen["lista_espera"] = {
            "esperando": len(activos),
            "dias_el_mas_antiguo": max([max(0, (ahora - e.fecha_registro).days) for e in activos], default=0),
        }
    return resumen


@panel_bp.route("/api/v1/salud/mis-permisos", methods=["GET"])
@validar_token
def mis_permisos():
    """
    Permisos del usuario según la matriz de permisos
    ---
    tags:
      - Panel
    security:
      - BearerAuth: []
    description: >
      Devuelve los roles del token y los permisos que le dan, según la matriz
      (auth.PERMISOS). El ciudadano no tiene permisos de la matriz: solo accede
      a lo propio.
    responses:
      200:
        description: "roles, permisos y la matriz completa"
    """
    roles = g.usuario["roles"]
    return jsonify(success=True, data={
        "usuario": g.usuario.get("usuario"),
        "roles": [r for r in roles if ":" in r or r == "ciudadano"],
        "permisos": permisos_de(roles),
        "matriz": {p: list(r) for p, r in PERMISOS.items()},
    }), 200
