"""
Reportes de gestión (cifras agregadas, sin datos de pacientes).

  GET /reportes/diagnosticos  diagnósticos más frecuentes en un período.
"""
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta

from flask import Blueprint, jsonify, request

import cie10
from alertas_clinicas import normalizar
from auth import puede, requiere_permiso, validar_token
from models import ExpedienteClinico

reportes_bp = Blueprint("reportes", __name__)

MINIMO_PACIENTES = 3      # Auditoría: grupos con menos pacientes se suman en "Otros" (no identificar a nadie)
OTROS = "Otros diagnósticos"


def _error(status, codigo, mensaje):
    return jsonify(success=False, error=codigo, message=mensaje), status


def _fecha(nombre, defecto):
    valor = request.args.get(nombre)
    if not valor:
        return defecto
    return datetime.strptime(valor, "%Y-%m-%d").date()   # ValueError -> 400 en la ruta


def clave_diagnostico(texto):
    """Agrupa los diagnósticos escritos a mano: sin tildes ni mayúsculas, solo la primera línea
    y sin el punto final ("Gripe." y "gripe" cuentan juntos)."""
    primera = (texto or "").strip().splitlines()[0] if (texto or "").strip() else ""
    return normalizar(primera)[:80]


@reportes_bp.route("/api/v1/salud/reportes/diagnosticos", methods=["GET"])
@validar_token
@requiere_permiso("reportes.ver")
def diagnosticos_frecuentes():
    """
    Diagnósticos más frecuentes en un período (gestión y Auditoría)
    ---
    tags:
      - Reportes
    security:
      - BearerAuth: []
    description: >
      Cuenta las atenciones del expediente por diagnóstico (se agrupan sin importar tildes,
      mayúsculas ni el punto final). Solo cifras: ningún nombre ni dato de pacientes.
      Para Auditoría, los diagnósticos con menos de 3 pacientes se suman en "Otros diagnósticos".
    parameters:
      - {name: desde, in: query, type: string, required: false, description: "AAAA-MM-DD (por defecto, hace 90 días)"}
      - {name: hasta, in: query, type: string, required: false, description: "AAAA-MM-DD (por defecto, hoy)"}
      - {name: limite, in: query, type: integer, required: false, description: "1 a 50 (por defecto 10)"}
    responses:
      200:
        description: "desde, hasta, total_atenciones, total_pacientes, data [{diagnostico, atenciones, pacientes, porcentaje}]"
      400:
        description: Fechas o límite con formato inválido
    """
    hoy = date.today()
    try:
        hasta = _fecha("hasta", hoy)
        desde = _fecha("desde", hasta - timedelta(days=89))
    except ValueError:
        return _error(400, "datos_invalidos", "Las fechas van con formato AAAA-MM-DD")
    if desde > hasta:
        return _error(400, "datos_invalidos", "La fecha 'desde' es posterior a 'hasta'")
    if (hasta - desde).days > 3 * 366:
        return _error(400, "datos_invalidos", "El período puede ser de hasta 3 años")
    limite = request.args.get("limite", "10")
    if not limite.isdigit() or not 1 <= int(limite) <= 50:
        return _error(400, "datos_invalidos", "limite debe ser un número de 1 a 50")
    limite = int(limite)

    filas = ExpedienteClinico.query.with_entities(ExpedienteClinico.diagnostico, ExpedienteClinico.paciente_id,
                                                  ExpedienteClinico.codigo_cie10) \
        .filter(ExpedienteClinico.fecha_atencion >= datetime.combine(desde, datetime.min.time()),
                ExpedienteClinico.fecha_atencion < datetime.combine(hasta + timedelta(days=1), datetime.min.time())) \
        .all()

    atenciones, pacientes, escrituras, codigos = Counter(), defaultdict(set), defaultdict(Counter), {}
    for diagnostico, paciente_id, codigo in filas:
        # Con código CIE-10 se agrupa por el código (aunque cada médico lo escriba distinto)
        if codigo and cie10.descripcion(codigo):
            clave = f"cie10:{codigo}"
            codigos[clave] = codigo
            nombre = f"{codigo} · {cie10.descripcion(codigo)}"
        else:
            clave = clave_diagnostico(diagnostico)
            nombre = (diagnostico or "").strip().splitlines()[0].rstrip(" .")[:80] if clave else ""
        if not clave:
            continue
        atenciones[clave] += 1
        pacientes[clave].add(paciente_id)
        escrituras[clave][nombre] += 1

    # Para Auditoría (sin acceso al expediente), los grupos pequeños se suman en "Otros"
    if not puede("expediente.ver"):
        for clave in [c for c in atenciones if len(pacientes[c]) < MINIMO_PACIENTES]:
            atenciones[OTROS] += atenciones.pop(clave)
            pacientes[OTROS] |= pacientes.pop(clave)
            escrituras[OTROS][OTROS] += 1

    total = sum(atenciones.values())
    principales = [c for c, _ in atenciones.most_common() if c != OTROS][:limite]
    datos = [{
        # Se muestra como lo escribieron más veces ("Gripe común" y no "gripe comun")
        "diagnostico": escrituras[c].most_common(1)[0][0] or c,
        "codigo_cie10": codigos.get(c),
        "atenciones": atenciones[c],
        "pacientes": len(pacientes[c]),
        "porcentaje": round(100 * atenciones[c] / total, 1) if total else 0,
    } for c in principales]
    resto = total - sum(d["atenciones"] for d in datos)
    if resto:
        datos.append({"diagnostico": OTROS, "atenciones": resto, "otros": True,
                      "pacientes": None, "porcentaje": round(100 * resto / total, 1)})
    return jsonify(success=True, desde=str(desde), hasta=str(hasta), total_atenciones=total,
                   total_pacientes=len({p for _, p, _ in filas}), data=datos), 200
