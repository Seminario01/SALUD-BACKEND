"""
Sedes: establecimientos de la red donde trabaja el personal de este sistema (Establecimiento.es_sede).

Turnos, camas, hospitalizaciones y recursos son de una sede; farmacia, caja y expedientes son compartidos.
Cada persona trabaja en la sede que le asigna Administración (tabla sedes_usuario); sin asignar, en la principal
(Config.SEDE_PRINCIPAL). Jefatura y Administración (permiso sedes.cambiar) pueden ver otra sede o todas con el
encabezado X-Sede (un id o "todas").

  preparar_sedes(db)   al arrancar: marca la principal como sede y le pasa lo que todavía no tiene sede.
  sede_actual()        sede de esta petición (None = todas).
  sede_para_crear()    sede donde queda lo que se crea (nunca None).
  filtrar(query, M)    la consulta solo con lo de la sede actual.

Lo que no tiene sede (por ejemplo, datos cargados por SQL después de arrancar) cuenta como de la principal.
"""
import logging

from flask import g, request
from sqlalchemy import inspect, or_, text

from config import Config

log = logging.getLogger(__name__)
TABLAS = ("turnos", "camas", "hospitalizaciones", "recursos_hospitalarios")
_principal = None


def principal_id():
    global _principal
    if _principal is None:
        from establecimientos import RED, _clave
        from models import Establecimiento
        claves = {_clave(Config.SEDE_PRINCIPAL)}
        for h in RED["hospitales"]:
            nombres = {_clave(n) for n in [h["nombre"], *h["otros_nombres"]]}
            if claves & nombres:
                claves |= nombres
        e = next((e for e in Establecimiento.query.order_by(Establecimiento.id_establecimiento) if _clave(e.nombre) in claves), None)
        if e is None:
            return None                      # todavía no está cargada: se vuelve a buscar la próxima vez
        _principal = e.id_establecimiento
    return _principal


def preparar_sedes(db):
    from models import Establecimiento
    try:
        sede = principal_id()
        if sede is None:
            log.warning("Sedes: no está la sede principal (%s) en la red de establecimientos", Config.SEDE_PRINCIPAL)
            return
        e = db.session.get(Establecimiento, sede)
        if not e.es_sede:
            e.es_sede = True
            db.session.commit()
        tablas = set(inspect(db.engine).get_table_names())
        with db.engine.begin() as conexion:
            for tabla in TABLAS:
                if tabla in tablas:
                    n = conexion.execute(text(f"UPDATE {tabla} SET sede_id = :s WHERE sede_id IS NULL"), {"s": sede}).rowcount
                    if n:
                        log.warning("Sedes: %s filas de %s pasaron a la sede principal", n, tabla)
    except Exception as error:  # noqa: BLE001 - el arranque no debe caerse por esto
        db.session.rollback()
        log.warning("No se pudieron preparar las sedes: %s", error)


def sede_propia(sub=None):
    """La sede asignada a la persona (o la principal)."""
    from models import SedeUsuario
    sub = sub or (g.usuario["sub"] if g.get("usuario") else None)
    asignada = SedeUsuario.query.get(sub) if sub else None
    return asignada.sede_id if asignada else principal_id()


def sede_actual():
    if "sede_actual" in g:
        return g.sede_actual
    from auth import puede
    from models import Establecimiento
    sede = sede_propia()
    pedida = (request.headers.get("X-Sede") or "").strip().lower()
    if pedida and puede("sedes.cambiar"):
        if pedida == "todas":
            sede = None
        elif pedida.isdigit():
            e = Establecimiento.query.get(int(pedida))
            if e and e.es_sede:
                sede = e.id_establecimiento
    g.sede_actual = sede
    return sede


def sede_para_crear():
    return sede_actual() or sede_propia()


def de_la_sede(columna, sede):
    """Condición: la fila es de esa sede (en la principal, también las que no tienen sede)."""
    return or_(columna == sede, columna.is_(None)) if sede == principal_id() else columna == sede


def misma_sede(a, b):
    principal = principal_id()
    return (a or principal) == (b or principal)


def filtrar(query, modelo):
    sede = sede_actual()
    return query if sede is None else query.filter(de_la_sede(modelo.sede_id, sede))


def nombres():
    from models import Establecimiento
    return {e.id_establecimiento: e.nombre for e in Establecimiento.query.filter_by(es_sede=True)}
