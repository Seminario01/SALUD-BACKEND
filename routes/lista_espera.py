"""
Lista de espera de citas: pacientes que quieren cita pero no hay espacio. Cuando alguien cancela,
Recepción ve quién sigue (primero el que lleva más tiempo esperando), le avisa y le agenda.

  GET  /citas/lista-espera        activos (ESPERANDO y AVISADO) o por estado     (citas.ver)
  POST /citas/lista-espera        agregar a un paciente (uno activo por paciente) (citas.gestionar)
  PUT  /citas/lista-espera/<id>   AVISADO, AGENDADO (con su cita) o CANCELADA     (citas.gestionar)
"""
from datetime import datetime

from flask import Blueprint, g, jsonify, request

from auth import requiere_permiso, validar_token
from extensions import db
from models import CitaMedica, ListaEspera, Paciente
from validacion import entero, opcion, texto

lista_espera_bp = Blueprint("lista_espera", __name__)
ACTIVOS = ("ESPERANDO", "AVISADO")
ESTADOS = ("ESPERANDO", "AVISADO", "AGENDADO", "CANCELADA")


def _error(status, codigo, mensaje):
    return jsonify(success=False, error=codigo, message=mensaje), status


def en_espera():
    """Cuántos pacientes siguen esperando un espacio (lo usa la cancelación de citas)."""
    return ListaEspera.query.filter(ListaEspera.estado.in_(ACTIVOS)).count()


def _dato(e, paciente=None):
    ahora = datetime.now()
    return {
        "id": e.id, "paciente_id": e.paciente_id,
        "paciente": paciente.nombre_completo if paciente else None,
        "telefono": paciente.telefono if paciente else None,
        "motivo": e.motivo, "preferencia": e.preferencia, "estado": e.estado, "nota": e.nota,
        "fecha_registro": e.fecha_registro.isoformat(timespec="minutes"),
        "dias_esperando": (ahora - e.fecha_registro).days,
        "registrado_por": e.registrado_por,
        "fecha_aviso": e.fecha_aviso.isoformat(timespec="minutes") if e.fecha_aviso else None,
        "cita_id": e.cita_id,
    }


@lista_espera_bp.route("/api/v1/salud/citas/lista-espera", methods=["GET"])
@validar_token
@requiere_permiso("citas.ver")
def listar_lista_espera():
    """
    Lista de espera de citas
    ---
    tags:
      - Citas
    security:
      - BearerAuth: []
    parameters:
      - {name: estado, in: query, type: string, enum: [ESPERANDO, AVISADO, AGENDADO, CANCELADA],
         description: "Sin estado: los que siguen esperando (ESPERANDO y AVISADO)"}
    responses:
      200:
        description: Primero el que lleva más tiempo esperando
      400:
        description: Estado inválido
    """
    estado = (request.args.get("estado") or "").upper()
    q = ListaEspera.query
    if estado:
        if estado not in ESTADOS:
            return _error(400, "datos_invalidos", f"estado debe ser uno de: {', '.join(ESTADOS)}")
        q = q.filter_by(estado=estado)
    else:
        q = q.filter(ListaEspera.estado.in_(ACTIVOS))
    lista = q.order_by(ListaEspera.fecha_registro.asc(), ListaEspera.id.asc()).limit(300).all()
    ids = {e.paciente_id for e in lista}
    pacientes = {p.id: p for p in Paciente.query.filter(Paciente.id.in_(ids)).all()} if ids else {}
    return jsonify(success=True, data=[_dato(e, pacientes.get(e.paciente_id)) for e in lista]), 200


@lista_espera_bp.route("/api/v1/salud/citas/lista-espera", methods=["POST"])
@validar_token
@requiere_permiso("citas.gestionar")
def agregar_lista_espera():
    """
    Agregar a un paciente a la lista de espera
    ---
    tags:
      - Citas
    security:
      - BearerAuth: []
    parameters:
      - in: body
        name: body
        required: true
        schema:
          type: object
          required: [paciente_id, motivo]
          properties:
            paciente_id: {type: integer}
            motivo: {type: string, example: "Control de presión"}
            preferencia: {type: string, example: "Por las mañanas, cualquier día"}
    responses:
      201:
        description: Agregado
      404:
        description: El paciente no existe
      409:
        description: El paciente ya está en la lista de espera
    """
    data = request.get_json(silent=True) or {}
    paciente = Paciente.query.get(entero(data, "paciente_id", 1, 2**31 - 1, obligatorio=True, etiqueta="paciente_id"))
    if not paciente:
        return _error(404, "no_encontrado", "Paciente no existe")
    motivo = texto(data, "motivo", 255, obligatorio=True, minimo=3, etiqueta="El motivo")
    if ListaEspera.query.filter(ListaEspera.paciente_id == paciente.id, ListaEspera.estado.in_(ACTIVOS)).first():
        return _error(409, "ya_existe", "El paciente ya está en la lista de espera")
    e = ListaEspera(paciente_id=paciente.id, motivo=motivo,
                    preferencia=texto(data, "preferencia", 150, etiqueta="La preferencia"),
                    estado="ESPERANDO", fecha_registro=datetime.now(),
                    registrado_por=(g.usuario.get("nombre") or g.usuario.get("usuario") or "")[:150] or None)
    db.session.add(e)
    db.session.commit()
    posicion = ListaEspera.query.filter(ListaEspera.estado.in_(ACTIVOS), ListaEspera.id <= e.id).count()
    return jsonify(success=True, data={**_dato(e, paciente), "posicion": posicion},
                   message=f"{paciente.nombre_completo} quedó en la lista de espera (posición {posicion})"), 201


@lista_espera_bp.route("/api/v1/salud/citas/lista-espera/<int:id>", methods=["PUT"])
@validar_token
@requiere_permiso("citas.gestionar")
def actualizar_lista_espera(id):
    """
    Avisar, agendar o sacar de la lista de espera
    ---
    tags:
      - Citas
    security:
      - BearerAuth: []
    parameters:
      - {name: id, in: path, type: integer, required: true}
      - in: body
        name: body
        required: true
        schema:
          type: object
          required: [estado]
          properties:
            estado: {type: string, enum: [AVISADO, AGENDADO, CANCELADA]}
            cita_id: {type: integer, description: "AGENDADO: la cita que se le dio (del mismo paciente)"}
            nota: {type: string, example: "No contestó; se dejó mensaje"}
    responses:
      200:
        description: Actualizado
      400:
        description: Datos inválidos (falta la cita al agendar o no es del paciente)
      404:
        description: No existe
      409:
        description: Ya salió de la lista (agendado o cancelado)
    """
    e = ListaEspera.query.get(id)
    if not e:
        return _error(404, "no_encontrado", "No está en la lista de espera")
    if e.estado not in ACTIVOS:
        return _error(409, "estado_invalido", "Este paciente ya salió de la lista de espera")
    data = request.get_json(silent=True) or {}
    estado = opcion(data, "estado", ("AVISADO", "AGENDADO", "CANCELADA"), obligatorio=True, etiqueta="El estado")
    nota = texto(data, "nota", 255, etiqueta="La nota")
    if estado == "AGENDADO":
        cita = CitaMedica.query.get(entero(data, "cita_id", 1, 2**31 - 1, obligatorio=True, etiqueta="cita_id") or 0)
        if not cita or cita.paciente_id != e.paciente_id or cita.estado == "cancelada":
            return _error(400, "datos_invalidos", "La cita no existe, está cancelada o no es de este paciente")
        e.cita_id = cita.id
    if estado == "AVISADO":
        e.fecha_aviso = datetime.now()
    e.estado = estado
    if nota is not None:
        e.nota = nota
    db.session.commit()
    textos = {"AVISADO": "avisado", "AGENDADO": "agendado: sale de la lista", "CANCELADA": "sacado de la lista de espera"}
    return jsonify(success=True, data=_dato(e, Paciente.query.get(e.paciente_id)),
                   message=f"Paciente {textos[estado]}"), 200
