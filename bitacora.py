"""
Bitácora de integraciones: registra cada llamada entre Salud y otro módulo.

- saliente: Salud consulta a Educación, Seguridad o Tributario (services_externos.py)
- entrante: otro módulo consume un servicio de Salud con X-API-Key (routes/externos.py)

Se escribe con una conexión propia (no con db.session), así un error al
registrar nunca afecta la operación del usuario ni su transacción.
"""
import logging
import re
from urllib.parse import unquote

from flask import g, has_request_context

from extensions import db
from models import BitacoraIntegracion

log = logging.getLogger(__name__)
_CUI = re.compile(r"\d{9}(\d{4})")


def enmascarar(texto):
    """2501234560109 -> *********0109 (dato personal: solo los últimos 4 dígitos)."""
    return _CUI.sub(lambda m: "*" * 9 + m.group(1), texto or "")


def resumir(datos):
    """Texto corto con lo más importante de la respuesta (sin datos personales)."""
    if isinstance(datos, list):
        return f"{len(datos)} registro(s)"
    if not isinstance(datos, dict):
        return None
    claves = ("estado", "nivelRiesgo", "requiereCustodia", "esEstudiante", "grado", "pagoConfirmado",
              "numeroAutorizacion", "horasAcumuladas", "disponible", "pacientes_totales", "monto",
              "pago_confirmado", "mensaje", "message")
    def valor(v):
        return "sí" if v is True else "no" if v is False else v
    partes = [f"{c}: {valor(datos[c])}" for c in claves if c in datos and datos[c] not in (None, "")]
    partes += [f"{c}: {len(v)} registro(s)" for c, v in datos.items() if isinstance(v, list)]
    return ", ".join(partes[:3]) or None


def registrar(direccion, modulo, operacion, metodo, ruta, estado_http, resultado,
              duracion_ms=None, simulado=False, detalle=None):
    usuario = None
    if has_request_context() and getattr(g, "usuario", None):
        usuario = g.usuario.get("usuario")
    try:
        with db.engine.begin() as conexion:
            conexion.execute(BitacoraIntegracion.__table__.insert().values(
                direccion=direccion, modulo=modulo, operacion=operacion[:120], metodo=metodo,
                ruta=enmascarar(unquote(ruta))[:255], estado_http=estado_http, resultado=resultado[:30],
                duracion_ms=duracion_ms, simulado=bool(simulado), usuario=usuario,
                detalle=enmascarar(detalle)[:255] if detalle else None,
            ))
    except Exception as error:  # noqa: BLE001 - la bitácora nunca debe romper la operación
        log.warning("No se pudo registrar en la bitácora de integraciones: %s", error)
