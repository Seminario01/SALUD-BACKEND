"""
Bitácora de accesos: quién vio o modificó datos de pacientes, y cuándo.

Se registra al terminar cada petición con token del Login Único (after_request):
  - ver:       consultas a datos de UN paciente (ficha, expediente, vacunación,
               antecedentes, receta, cuenta, hospitalización). Las listas no se
               registran, y si la misma persona vuelve a ver lo mismo en menos de
               5 minutos tampoco (la ficha pide varias cosas a la vez).
  - crear / modificar / anular: todo POST, PUT o DELETE que terminó bien.
Las peticiones rechazadas (401, 403, 404, 400...) no se registran como acceso.

Igual que bitacora.py, escribe con una conexión propia: un error al registrar
nunca afecta la operación del usuario.
"""
import logging
from datetime import datetime, timedelta

from flask import g, request
from sqlalchemy import select

from bitacora import enmascarar
from extensions import db
from models import (BitacoraAcceso, CitaMedica, ConstanciaMedica, CuentaPaciente, Hospitalizacion, ListaEspera,
                    OrdenLaboratorio, PersonalSalud, Receta, Turno, UsuarioReciente)

log = logging.getLogger(__name__)
PREFIJO = "/api/v1/salud"
REPETIDO = timedelta(minutes=5)

# Ruta (como está declarada en Flask, sin el prefijo) -> descripción. {id} es el número del recurso.
VER = {
    "/pacientes/<int:id>": "Vio la ficha del paciente",
    "/expedientes/<int:paciente_id>": "Vio el expediente clínico",
    "/vacunacion/<int:paciente_id>": "Vio el registro de vacunación",
    "/pacientes/<int:id>/antecedentes": "Consultó antecedentes en Seguridad",
    "/pacientes/<int:id>/signos": "Vio el historial de signos vitales",
    "/recetas/<int:id>": "Vio la receta No. {id}",
    "/cuentas/<int:id>": "Vio la cuenta No. {id}",
    "/hospitalizaciones/<int:id>": "Vio la hospitalización No. {id}",
    "/citas/<int:id>": "Vio la cita No. {id}",
    "/constancias/<int:id>": "Vio la constancia No. {id}",
    "/laboratorio/ordenes/<int:id>": "Vio la orden de laboratorio No. {id}",
    "/vigilancia/pacientes": "Consultó la lista de casos de vigilancia epidemiológica",
    "/pacientes/<int:id>/crecimiento": "Vio las curvas de crecimiento",
}

CAMBIOS = {
    ("POST", "/pacientes"): ("crear", "Registró al paciente"),
    ("PUT", "/pacientes/<int:id>"): ("modificar", "Modificó los datos del paciente"),
    ("PUT", "/pacientes/<int:id>/alergias"): ("modificar", "Actualizó las alergias del paciente"),
    ("POST", "/citas"): ("crear", "Agendó la cita No. {nuevo}"),
    ("PUT", "/citas/<int:id>"): ("modificar", "Modificó la cita No. {id}"),
    ("DELETE", "/citas/<int:id>"): ("anular", "Canceló la cita No. {id}"),
    ("POST", "/citas/lista-espera"): ("crear", "Agregó al paciente a la lista de espera"),
    ("POST", "/pacientes/<int:id>/crecimiento"): ("crear", "Registró una medición de crecimiento"),
    ("POST", "/puestos/asignados"): ("crear", "Asignó el puesto {detalle}"),
    ("DELETE", "/puestos/asignados/<int:id>"): ("anular", "Quitó el puesto {detalle}"),
    ("DELETE", "/pacientes/<int:id>/crecimiento/<int:mid>"): ("anular", "Anuló una medición de crecimiento"),
    ("PUT", "/citas/lista-espera/<int:id>"): ("modificar", "Actualizó la lista de espera No. {id}"),
    ("POST", "/citas/<int:id>/cobro"): ("modificar", "Generó el cobro de la cita No. {id}"),
    ("POST", "/citas/<int:id>/verificar-pago"): ("modificar", "Verificó el pago de la cita No. {id}"),
    ("POST", "/expedientes/<int:paciente_id>/atenciones"): ("crear", "Registró una atención en el expediente"),
    ("POST", "/vacunacion"): ("crear", "Creó el registro de vacunación"),
    ("PUT", "/vacunacion/<int:paciente_id>"): ("modificar", "Modificó el registro de vacunación"),
    ("DELETE", "/vacunacion/<int:paciente_id>"): ("anular", "Anuló el registro de vacunación"),
    ("POST", "/turnos"): ("crear", "Generó el turno No. {nuevo}"),
    ("PUT", "/turnos/<int:id>/llamar"): ("modificar", "Llamó al turno No. {id}"),
    ("PUT", "/turnos/<int:id>/atender"): ("modificar", "Atendió el turno No. {id}"),
    ("PUT", "/turnos/<int:id>/finalizar"): ("modificar", "Finalizó el turno No. {id}"),
    ("PUT", "/turnos/<int:id>/triage"): ("modificar", "Clasificó (triage) el turno No. {id}"),
    ("POST", "/recetas"): ("crear", "Emitió la receta No. {nuevo}"),
    ("POST", "/recetas/<int:id>/despachar"): ("modificar", "Despachó la receta No. {id}"),
    ("POST", "/recetas/<int:id>/anular"): ("anular", "Anuló la receta No. {id}"),
    ("POST", "/constancias"): ("crear", "Emitió la constancia No. {nuevo}"),
    ("POST", "/constancias/<int:id>/anular"): ("anular", "Anuló la constancia No. {id}"),
    ("POST", "/laboratorio/ordenes"): ("crear", "Ordenó los exámenes de laboratorio No. {nuevo}"),
    ("POST", "/laboratorio/ordenes/<int:id>/muestra"): ("modificar", "Tomó la muestra de la orden de laboratorio No. {id}"),
    ("PUT", "/laboratorio/ordenes/<int:id>/resultados"): ("modificar", "Registró resultados de la orden de laboratorio No. {id}"),
    ("POST", "/laboratorio/ordenes/<int:id>/anular"): ("anular", "Anuló la orden de laboratorio No. {id}"),
    ("POST", "/hospitalizaciones"): ("crear", "Ordenó el ingreso No. {nuevo}"),
    ("POST", "/hospitalizaciones/<int:id>/asignar-cama"): ("modificar", "Asignó cama en la hospitalización No. {id}"),
    ("POST", "/hospitalizaciones/<int:id>/egreso"): ("modificar", "Dio egreso en la hospitalización No. {id}"),
    ("POST", "/hospitalizaciones/<int:id>/anular"): ("anular", "Anuló la hospitalización No. {id}"),
    ("POST", "/hospitalizaciones/<int:id>/notas"): ("crear", "Agregó una nota en la hospitalización No. {id}"),
    ("POST", "/cuentas"): ("crear", "Abrió la cuenta No. {nuevo}"),
    ("POST", "/cuentas/<int:id>/cargos"): ("modificar", "Agregó un cargo a la cuenta No. {id}"),
    ("POST", "/cuentas/<int:id>/descuentos"): ("modificar", "Aplicó un descuento a la cuenta No. {id}"),
    ("POST", "/cuentas/<int:id>/movimientos/<int:mid>/anular"): ("anular", "Anuló un movimiento de la cuenta No. {id}"),
    ("POST", "/cuentas/<int:id>/cerrar"): ("modificar", "Cerró la cuenta No. {id}"),
    ("POST", "/cuentas/<int:id>/verificar-pago"): ("modificar", "Verificó el pago de la cuenta No. {id}"),
    ("POST", "/medicamentos"): ("crear", "Agregó el medicamento No. {nuevo}"),
    ("POST", "/medicamentos/<int:id>/movimientos"): ("modificar", "Registró un movimiento del medicamento No. {id}"),
    ("POST", "/medicamentos/<int:id>/lotes/<int:lote_id>/baja"): ("anular", "Dio de baja un lote del medicamento No. {id}"),
}

# Para las rutas cuyo número no es el del paciente: de qué tabla se saca el paciente
DUENO = {"/citas/lista-espera": ListaEspera, "/citas": CitaMedica, "/turnos": Turno, "/recetas": Receta, "/constancias": ConstanciaMedica,
         "/laboratorio/ordenes": OrdenLaboratorio,
         "/hospitalizaciones": Hospitalizacion, "/cuentas": CuentaPaciente}

PUESTOS = [("salud:jefatura", "Jefatura médica"), ("salud:admin", "Administración"), ("salud:medico", "Médico"),
           ("salud:enfermeria", "Enfermería"), ("salud:recepcion", "Recepción"), ("salud:farmacia", "Farmacia"),
           ("salud:caja", "Caja"), ("ciudadano", "Ciudadano")]


def _puesto(roles):
    return next((nombre for rol, nombre in PUESTOS if rol in roles), None)


def _datos_respuesta(respuesta):
    try:
        cuerpo = respuesta.get_json(silent=True) or {}
        datos = cuerpo.get("data")
        return datos if isinstance(datos, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _paciente(regla, args, datos):
    if "paciente_id" in args:
        return args["paciente_id"]
    if regla.startswith("/pacientes/") and "id" in args:
        return args["id"]
    if isinstance(datos.get("paciente_id"), int):
        return datos["paciente_id"]
    if regla == "/pacientes" and isinstance(datos.get("id"), int):
        return datos["id"]
    cuerpo = request.get_json(silent=True) if request.is_json else None
    if isinstance(cuerpo, dict) and isinstance(cuerpo.get("paciente_id"), int):
        return cuerpo["paciente_id"]
    modelo = next((m for prefijo, m in DUENO.items() if regla.startswith(prefijo + "/")), None)
    if modelo is not None and "id" in args:
        fila = db.session.get(modelo, args["id"])
        return getattr(fila, "paciente_id", None)
    return None


_VISTOS = {}   # sub -> última vez que se actualizó personal_salud (en este proceso)
_RECIENTES = {}  # sub -> última vez que se actualizó usuarios_recientes (en este proceso)


def _anotar_reciente(usuario, ahora):
    """Guarda a quien entró (cualquier cuenta), a lo más una vez cada 10 minutos: así Administración
    encuentra a un compañero sin puesto para asignárselo (routes/puestos.py)."""
    sub = usuario.get("sub")
    if not sub or ahora - _RECIENTES.get(sub, datetime.min) < timedelta(minutes=10):
        return
    _RECIENTES[sub] = ahora
    datos = {"usuario": (usuario.get("usuario") or "")[:100] or None, "nombre": (usuario.get("nombre") or "")[:150] or None,
             "email": (usuario.get("email") or "")[:150] or None,
             "roles": ",".join(usuario.get("roles_token") or usuario.get("roles") or [])[:500], "ultimo_acceso": ahora}
    tabla = UsuarioReciente.__table__
    with db.engine.begin() as conexion:
        if conexion.execute(select(tabla.c.sub).where(tabla.c.sub == sub)).first():
            conexion.execute(tabla.update().where(tabla.c.sub == sub).values(**datos))
        else:
            conexion.execute(tabla.insert().values(sub=sub, **datos))


def _anotar_personal(usuario, ahora):
    """Guarda al personal de Salud que usa el módulo (a lo más una vez cada 10 minutos)."""
    roles = usuario.get("roles", [])
    if not any(r.startswith("salud:") for r in roles):
        return
    sub = usuario.get("sub")
    if not sub or ahora - _VISTOS.get(sub, datetime.min) < timedelta(minutes=10):
        return
    _VISTOS[sub] = ahora
    datos = {"usuario": (usuario.get("usuario") or "")[:100] or None, "nombre": (usuario.get("nombre") or "")[:150] or None,
             "es_medico": "salud:medico" in roles, "puesto": _puesto(roles), "ultimo_acceso": ahora}
    tabla = PersonalSalud.__table__
    with db.engine.begin() as conexion:
        existe = conexion.execute(select(tabla.c.sub).where(tabla.c.sub == sub)).first()
        if existe:
            conexion.execute(tabla.update().where(tabla.c.sub == sub).values(**datos))
        else:
            conexion.execute(tabla.insert().values(sub=sub, **datos))


def registrar_acceso(respuesta):
    """after_request: anota la petición si fue de un usuario con token y terminó bien."""
    try:
        usuario = getattr(g, "usuario", None)
        if (not usuario or respuesta.status_code >= 400 or request.url_rule is None
                or not request.path.startswith(PREFIJO)):
            return respuesta
        try:
            _anotar_personal(usuario, datetime.now())
            _anotar_reciente(usuario, datetime.now())
        except Exception as error:  # noqa: BLE001
            log.warning("No se pudo anotar al personal: %s", error)
        regla = request.url_rule.rule[len(PREFIJO):]
        args = request.view_args or {}
        datos = _datos_respuesta(respuesta)
        formato = {"id": args.get("id", ""), "nuevo": datos.get("numero_turno") or datos.get("id", ""),
                   "detalle": datos.get("detalle", "")}

        if request.method == "GET":
            if regla not in VER:
                return respuesta
            accion, descripcion = "ver", VER[regla].format(**formato)
        elif request.method in ("POST", "PUT", "PATCH", "DELETE"):
            if regla.startswith(("/integraciones/simular", "/auditoria")):
                return respuesta
            accion, descripcion = CAMBIOS.get((request.method, regla),
                                              ("modificar", f"{request.method} {regla}"))
            descripcion = descripcion.format(**formato)
        else:
            return respuesta

        paciente_id = _paciente(regla, args, datos)
        ahora = datetime.now()
        if accion == "ver":
            reciente = BitacoraAcceso.query.filter(
                BitacoraAcceso.usuario == usuario.get("usuario"), BitacoraAcceso.descripcion == descripcion,
                BitacoraAcceso.paciente_id == paciente_id, BitacoraAcceso.fecha >= ahora - REPETIDO).first()
            if reciente:
                return respuesta

        ip = (request.headers.get("CF-Connecting-IP") or request.headers.get("X-Real-IP")
              or request.remote_addr or "")[:45]
        with db.engine.begin() as conexion:
            conexion.execute(BitacoraAcceso.__table__.insert().values(
                fecha=ahora, usuario=(usuario.get("usuario") or usuario.get("sub"))[:100],
                nombre=(usuario.get("nombre") or "")[:150] or None, puesto=_puesto(usuario.get("roles", [])),
                accion=accion, descripcion=descripcion[:255], paciente_id=paciente_id,
                metodo=request.method, ruta=enmascarar(request.path)[:255],
                estado_http=respuesta.status_code, ip=ip or None,
            ))
    except Exception as error:  # noqa: BLE001 - la bitácora nunca debe romper la operación
        log.warning("No se pudo registrar en la bitácora de accesos: %s", error)
    return respuesta
