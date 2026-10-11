"""
Confirmación de pago que Tributario envía a Salud (documento "Flujo de pagos
entre Salud y Tributario").

    POST /api/v1/salud/pagos/confirmacion
    X-API-Key, X-Modulo-Origen: tributario, Idempotency-Key: <evento_id>
    {"evento_id": "pago-aprobado-123",
     "data": {"numero_referencia": "SAL-2026-000120", "referencia_tributario": "REF-TRIB-000123",
              "estado": "APROBADO", "estado_pago": "PAGADO", "numero_autorizacion": "123456",
              "monto_pagado": 150.00, "fecha_pago": "2026-10-10T11:30:00"}}

Respuestas: 200 procesado (también si el evento ya se procesó), 400 datos
incompletos, 401/403 clave, 404 referencia inexistente, 409 el monto pagado no
coincide con lo cobrado.

La referencia puede ser de una CITA o de una CUENTA del paciente (Caja).
"""
import json
from datetime import datetime
from decimal import Decimal, InvalidOperation

from extensions import db
from models import CitaMedica, CuentaPaciente, EventoPago

PAGADO = ("PAGADO", "PAGADA", "APROBADO", "APROBADA", "CONFIRMADO", "CANCELADO_PAGO")
ANULADO = ("ANULADO", "ANULADA", "CANCELADO", "CANCELADA")
RECHAZADO = ("RECHAZADO", "RECHAZADA", "FALLIDO", "DENEGADO")


def _fecha(valor):
    try:
        return datetime.fromisoformat(str(valor).replace("Z", "")) if valor else None
    except ValueError:
        return None


def _decimal(valor):
    try:
        return Decimal(str(valor)).quantize(Decimal("0.01")) if valor not in (None, "") else None
    except (InvalidOperation, TypeError):
        return None


def clasificar(estado, estado_pago):
    """PAGADO, PARCIAL, RECHAZADO, ANULADO o PENDIENTE según los dos campos de Tributario."""
    valores = (estado_pago, estado)
    if any(v and "PARCIAL" in v for v in valores):
        return "PARCIAL"
    if estado_pago in PAGADO or (not estado_pago and estado in PAGADO):
        return "PAGADO"
    if estado_pago in ANULADO or estado in ANULADO:
        return "ANULADO"
    if estado_pago in RECHAZADO or estado in RECHAZADO:
        return "RECHAZADO"
    return "PENDIENTE"


def procesar(cuerpo, idempotency_key=None):
    """Devuelve (status_http, respuesta_dict)."""
    cuerpo = cuerpo if isinstance(cuerpo, dict) else {}
    datos = cuerpo.get("data") if isinstance(cuerpo.get("data"), dict) else cuerpo
    evento_id = str(cuerpo.get("evento_id") or idempotency_key or "").strip()[:100] or None
    if idempotency_key and cuerpo.get("evento_id") and str(cuerpo["evento_id"]) != str(idempotency_key):
        return 400, {"success": False, "error": "datos_invalidos",
                     "message": "Idempotency-Key debe ser igual a evento_id"}

    # Evento ya procesado: misma respuesta, sin volver a aplicar nada
    if evento_id:
        previo = EventoPago.query.filter_by(evento_id=evento_id).first()
        if previo:
            respuesta = json.loads(previo.respuesta or "{}")
            respuesta["duplicado"] = True
            return 200, respuesta

    referencia = str(datos.get("numero_referencia") or "").strip()
    estado = str(datos.get("estado") or "").strip().upper()
    estado_pago = str(datos.get("estado_pago") or "").strip().upper()
    if not referencia or not (estado or estado_pago):
        return 400, {"success": False, "error": "datos_incompletos",
                     "message": "numero_referencia y estado (o estado_pago) son requeridos"}

    cita = CitaMedica.query.filter_by(numero_referencia=referencia).first()
    cuenta = None if cita else CuentaPaciente.query.filter_by(numero_referencia=referencia).first()
    if not cita and not cuenta:
        return 404, {"success": False, "error": "no_encontrado", "message": "Salud no tiene ese numero_referencia"}

    resultado = clasificar(estado, estado_pago)
    autorizacion = datos.get("numero_autorizacion")
    fecha_pago = _fecha(datos.get("fecha_pago"))
    ref_trib = datos.get("referencia_tributario")
    monto_pagado = _decimal(datos.get("monto_pagado"))

    if cita:
        ya_pagada = bool(cita.pago_confirmado)
        esperado = Decimal(cita.costo or 0).quantize(Decimal("0.01"))
    else:
        ya_pagada = cuenta.estado == "PAGADA"
        esperado = Decimal(cuenta.saldo or 0).quantize(Decimal("0.01"))

    if resultado == "PAGADO" and not ya_pagada and monto_pagado is not None and monto_pagado != esperado:
        return 409, {"success": False, "error": "monto_no_coincide",
                     "message": f"El monto pagado (Q{monto_pagado}) no coincide con lo cobrado (Q{esperado})",
                     "monto_esperado": float(esperado)}

    if cita:
        from routes.integraciones import marcar_pagada
        cita.referencia_tributario = ref_trib or cita.referencia_tributario
        if resultado == "PAGADO":
            marcar_pagada(cita, autorizacion, fecha_pago)
        elif not ya_pagada and resultado in ("ANULADO", "PARCIAL"):
            cita.estado_cobro = resultado
        estado_salud, tipo, ident = cita.estado_cobro or "PENDIENTE", "cita", cita.id
    else:
        from routes.caja import aviso_de_pago
        cuenta.referencia_tributario = ref_trib or cuenta.referencia_tributario
        if resultado in ("PAGADO", "ANULADO"):
            aviso_de_pago(referencia, resultado, autorizacion, fecha_pago)
        elif resultado == "PARCIAL" and not ya_pagada:
            cuenta.estado_cobro = "PARCIAL"
        estado_salud, tipo, ident = (cuenta.estado_cobro or ("ANULADO" if resultado == "ANULADO" else "PENDIENTE")), "cuenta", cuenta.id

    mensajes = {
        "PAGADO": "Pago confirmado" if not ya_pagada else "El pago ya estaba confirmado",
        "ANULADO": "Obligación anulada", "RECHAZADO": "Pago rechazado registrado; la obligación sigue pendiente",
        "PARCIAL": "Pago parcial registrado; la obligación sigue pendiente", "PENDIENTE": "Aviso registrado",
    }
    respuesta = {"success": True, "message": mensajes[resultado],
                 "data": {"numero_referencia": referencia, "estado": estado_salud, "tipo": tipo, "id": ident,
                          "evento_id": evento_id}}
    if evento_id:
        db.session.add(EventoPago(evento_id=evento_id, numero_referencia=referencia,
                                  respuesta=json.dumps(respuesta, ensure_ascii=False)))
    db.session.commit()
    return 200, respuesta
