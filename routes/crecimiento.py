"""
Control de crecimiento infantil (0 a 5 años) con los patrones de la OMS (crecimiento.py).

  GET    /pacientes/<id>/crecimiento            mediciones con z y clasificación, y las curvas de referencia
  POST   /pacientes/<id>/crecimiento            registrar peso y talla           (crecimiento.registrar)
  DELETE /pacientes/<id>/crecimiento/<mid>      anular una medición por error    (crecimiento.registrar)
"""
from datetime import date, datetime

from flask import Blueprint, g, jsonify, request

import crecimiento
from auth import puede, requiere_permiso, validar_token
from extensions import db
from models import MedicionCrecimiento, Paciente
from validacion import DatoInvalido, texto

crecimiento_bp = Blueprint("crecimiento", __name__)
CURVAS_Z = (-3, -2, 0, 2, 3)


def _error(status, codigo, mensaje):
    return jsonify(success=False, error=codigo, message=mensaje), status


def _numero(data, campo, minimo, maximo, etiqueta):
    valor = data.get(campo)
    if valor is None or valor == "":
        return None
    if isinstance(valor, bool) or not isinstance(valor, (int, float, str)):
        raise DatoInvalido(f"{etiqueta} debe ser un número")
    try:
        numero = float(str(valor).replace(",", "."))
    except ValueError:
        raise DatoInvalido(f"{etiqueta} debe ser un número")
    if not minimo <= numero <= maximo:
        raise DatoInvalido(f"{etiqueta} debe estar entre {minimo} y {maximo} (revise la digitación)")
    return numero


def _puede_ver(paciente):
    return puede("expediente.ver") or (paciente.usuario_sub is not None and paciente.usuario_sub == g.usuario["sub"])


def _medicion(m, paciente):
    dias = (m.fecha - paciente.fecha_nacimiento).days
    peso = float(m.peso_kg) if m.peso_kg is not None else None
    talla = float(m.talla_cm) if m.talla_cm is not None else None
    return {"id": m.id, "fecha": m.fecha.isoformat(), "edad_dias": dias, "edad_meses": round(dias / 30.4375, 1),
            "peso_kg": peso, "talla_cm": talla, "registrado_por": m.registrado_por, "nota": m.nota,
            "indicadores": crecimiento.evaluar(paciente.genero, dias, peso, talla)}


def _curvas(sexo):
    """Líneas de referencia de la OMS (z -3, -2, 0, +2, +3) para las gráficas."""
    edades = list(range(0, crecimiento.DIAS_MAX + 1, 30)) + [crecimiento.DIAS_MAX]
    tallas_l = [round(45 + i * 0.5, 1) for i in range(int((110 - 45) / 0.5) + 1)]
    tallas_t = [round(65 + i * 0.5, 1) for i in range(int((120 - 65) / 0.5) + 1)]
    ejes = {"peso_edad": edades, "talla_edad": edades, "peso_longitud": tallas_l, "peso_talla": tallas_t}
    return {clave: {"nombre": crecimiento.INDICADORES[clave]["nombre"], "eje": crecimiento.INDICADORES[clave]["eje"],
                    "lineas": {str(z): crecimiento.curva(clave, sexo, z, puntos) for z in CURVAS_Z}}
            for clave, puntos in ejes.items()}


@crecimiento_bp.route("/api/v1/salud/pacientes/<int:id>/crecimiento", methods=["GET"])
@validar_token
def ver_crecimiento(id):
    """
    Curvas de crecimiento del niño o niña (OMS, 0 a 5 años)
    ---
    tags:
      - Crecimiento
    security:
      - BearerAuth: []
    description: >
      Personal con expediente.ver o el ciudadano dueño. Cada medición trae la puntuación z de peso
      para la edad, talla para la edad y peso para la longitud/talla, con su clasificación (desnutrición
      crónica, aguda, bajo peso, sobrepeso...). Trae además las líneas de referencia de la OMS.
    parameters:
      - {name: id, in: path, type: integer, required: true}
    responses:
      200:
        description: "paciente (edad, sexo, aplica), mediciones, ultima, curvas, fuente"
      403:
        description: Sin permiso
      404:
        description: El paciente no existe
    """
    paciente = Paciente.query.get(id)
    if not paciente:
        return _error(404, "no_encontrado", "Paciente no existe")
    if not _puede_ver(paciente):
        return _error(403, "permiso_denegado", "Solo puede ver su propio registro")
    hoy = date.today()
    dias = (hoy - paciente.fecha_nacimiento).days if paciente.fecha_nacimiento else None
    motivo = None
    if paciente.genero not in ("M", "F"):
        motivo = "Registre el sexo del paciente (las curvas de la OMS son distintas para niñas y niños)"
    elif dias is None:
        motivo = "Registre la fecha de nacimiento"
    mediciones = []
    if paciente.fecha_nacimiento:
        mediciones = [_medicion(m, paciente) for m in
                      MedicionCrecimiento.query.filter_by(paciente_id=id).order_by(MedicionCrecimiento.fecha).all()]
    return jsonify(success=True, paciente={
        "id": paciente.id, "sexo": paciente.genero, "fecha_nacimiento": str(paciente.fecha_nacimiento) if paciente.fecha_nacimiento else None,
        "edad_dias": dias, "aplica": motivo is None and dias is not None and dias <= crecimiento.DIAS_MAX, "motivo": motivo,
    }, mediciones=mediciones, ultima=mediciones[-1] if mediciones else None,
        curvas=_curvas(paciente.genero) if paciente.genero in ("M", "F") else None, fuente=crecimiento.FUENTE), 200


@crecimiento_bp.route("/api/v1/salud/pacientes/<int:id>/crecimiento", methods=["POST"])
@validar_token
@requiere_permiso("crecimiento.registrar")
def registrar_crecimiento(id):
    """
    Registrar una medición de peso y talla (niños de 0 a 5 años)
    ---
    tags:
      - Crecimiento
    security:
      - BearerAuth: []
    parameters:
      - {name: id, in: path, type: integer, required: true}
      - in: body
        name: body
        required: true
        schema:
          type: object
          properties:
            fecha: {type: string, format: date, description: "Por defecto, hoy"}
            peso_kg: {type: number, example: 11.4}
            talla_cm: {type: number, example: 84.5, description: "Acostado antes de 2 años; de pie después"}
            nota: {type: string}
    responses:
      201:
        description: Medición con sus puntuaciones z y clasificación
      400:
        description: Datos inválidos, sin sexo o fecha de nacimiento, o mayor de 5 años
      404:
        description: El paciente no existe
    """
    paciente = Paciente.query.get(id)
    if not paciente:
        return _error(404, "no_encontrado", "Paciente no existe")
    if paciente.genero not in ("M", "F") or not paciente.fecha_nacimiento:
        return _error(400, "datos_incompletos", "Registre primero el sexo y la fecha de nacimiento del paciente")
    data = request.get_json(silent=True) or {}
    fecha_txt = texto(data, "fecha", 10, etiqueta="La fecha")
    try:
        fecha = date.fromisoformat(fecha_txt) if fecha_txt else date.today()
    except ValueError:
        return _error(400, "datos_invalidos", "La fecha va como AAAA-MM-DD")
    if fecha > date.today() or fecha < paciente.fecha_nacimiento:
        return _error(400, "datos_invalidos", "La fecha debe estar entre el nacimiento y hoy")
    dias = (fecha - paciente.fecha_nacimiento).days
    if dias > crecimiento.DIAS_MAX:
        return _error(400, "fuera_de_rango", "Las curvas de la OMS de este control son de 0 a 5 años")
    peso = _numero(data, "peso_kg", 0.5, 60, "El peso (kg)")
    talla = _numero(data, "talla_cm", 35, 130, "La talla (cm)")
    if peso is None and talla is None:
        return _error(400, "datos_incompletos", "Escriba el peso, la talla o los dos")
    m = MedicionCrecimiento(paciente_id=id, fecha=fecha, peso_kg=round(peso, 2) if peso else None,
                            talla_cm=round(talla, 1) if talla else None, nota=texto(data, "nota", 255, etiqueta="La nota"),
                            registrado_por=(g.usuario.get("nombre") or g.usuario.get("usuario") or "")[:150] or None,
                            fecha_registro=datetime.now())
    db.session.add(m)
    db.session.commit()
    datos = _medicion(m, paciente)
    graves = [i["texto"] for i in datos["indicadores"].values() if i["nivel"] in ("grave", "alerta")]
    mensaje = "Medición registrada" + (f". ⚠ {'; '.join(graves)}" if graves else "")
    return jsonify(success=True, data=datos, message=mensaje), 201


@crecimiento_bp.route("/api/v1/salud/pacientes/<int:id>/crecimiento/<int:mid>", methods=["DELETE"])
@validar_token
@requiere_permiso("crecimiento.registrar")
def anular_crecimiento(id, mid):
    """
    Anular una medición registrada por error
    ---
    tags:
      - Crecimiento
    security:
      - BearerAuth: []
    parameters:
      - {name: id, in: path, type: integer, required: true}
      - {name: mid, in: path, type: integer, required: true}
    responses:
      200:
        description: Anulada
      404:
        description: No existe (o no es de este paciente)
    """
    m = MedicionCrecimiento.query.get(mid)
    if not m or m.paciente_id != id:
        return _error(404, "no_encontrado", "La medición no existe")
    db.session.delete(m)
    db.session.commit()
    return jsonify(success=True, data={"id": mid, "paciente_id": id}, message="Medición anulada"), 200
