"""
Bitácora de integraciones: registra cada llamada entre Salud y otro módulo.

- saliente: Salud consulta a Educación, Seguridad o Tributario (services_externos.py)
- entrante: otro módulo consume un servicio de Salud con X-API-Key (routes/externos.py)

Se escribe con una conexión propia (no con db.session), así un error al
registrar nunca afecta la operación del usuario ni su transacción.
"""
import json
import logging
import re
import unicodedata
from urllib.parse import unquote

from flask import g, has_request_context, request

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


# Claves con datos personales (en minúsculas, sin tildes ni "_"): el DPI queda con sus últimos 4
# dígitos y los nombres como iniciales. "nombre" solo se enmascara si está junto a un DPI/CUI
# (un estudiante sí; un establecimiento no).
_DOCUMENTOS = {"cui", "dpi", "dpipersona", "cuipaciente", "numerodpi", "documento", "cuiestudiante"}
_PERSONALES = {"nombrecompleto", "nombres", "apellidos", "paciente", "estudiante", "cuidador", "contribuyente",
               "nombrecontribuyente", "nombrepaciente", "nombreestudiante", "telefono", "correo", "email",
               "direccion", "responsable", "encargado"}
_MAX_LISTA = 10
_MAX_TEXTO = 8000


def _clave(texto):
    t = unicodedata.normalize("NFD", str(texto)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]", "", t)


def _iniciales(valor):
    palabras = str(valor).split()
    return " ".join(f"{p[0]}." for p in palabras if p) if palabras else valor


def _documento(valor):
    texto = str(valor)
    return "*" * max(len(texto) - 4, 0) + texto[-4:] if len(texto) > 4 else "****"


def limpiar(datos, _con_documento=False):
    """Copia de un JSON para la bitácora: misma estructura, sin datos personales legibles."""
    if isinstance(datos, dict):
        con_documento = any(_clave(k) in _DOCUMENTOS for k in datos)
        limpio = {}
        for k, v in datos.items():
            c = _clave(k)
            if c in _DOCUMENTOS and isinstance(v, (str, int)) and v != "":
                limpio[k] = _documento(v)
            elif (c in _PERSONALES or (c == "nombre" and con_documento)) and isinstance(v, str) and v:
                limpio[k] = _iniciales(v) if "nombre" in c or c in ("paciente", "estudiante", "cuidador",
                                                                    "contribuyente", "responsable", "encargado") else "***"
            else:
                limpio[k] = limpiar(v)
        return limpio
    if isinstance(datos, list):
        lista = [limpiar(v) for v in datos[:_MAX_LISTA]]
        if len(datos) > _MAX_LISTA:
            lista.append(f"… y {len(datos) - _MAX_LISTA} más")
        return lista
    if isinstance(datos, str):
        return enmascarar(datos)
    return datos


def a_texto(datos):
    """JSON limpio y recortado para guardar (None si no hay nada)."""
    if datos in (None, "", {}, []):
        return None
    try:
        texto = json.dumps(limpiar(datos), ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        texto = json.dumps(enmascarar(str(datos)), ensure_ascii=False)
    return texto if len(texto) <= _MAX_TEXTO else texto[:_MAX_TEXTO] + " …(recortado)"


def registrar(direccion, modulo, operacion, metodo, ruta, estado_http, resultado,
              duracion_ms=None, simulado=False, detalle=None, url=None, solicitud=None, respuesta=None):
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
                url=enmascarar(unquote(url))[:500] if url else None,
                solicitud=a_texto(solicitud), respuesta=a_texto(respuesta),
            ))
    except Exception as error:  # noqa: BLE001 - la bitácora nunca debe romper la operación
        log.warning("No se pudo registrar en la bitácora de integraciones: %s", error)


def solicitud_entrante():
    """Para las llamadas que recibe Salud: a dónde llegaron y qué mandaron (la clave no se guarda)."""
    proto = request.headers.get("X-Forwarded-Proto") or request.scheme
    host = request.headers.get("X-Forwarded-Host") or request.host
    encabezados = {"X-API-Key": "(enviada, no se guarda)" if request.headers.get("X-API-Key") else None,
                   "Authorization": "Bearer (token, no se guarda)" if request.headers.get("Authorization") else None,
                   "X-Modulo-Origen": request.headers.get("X-Modulo-Origen")}
    return (f"{proto}://{host}{request.full_path.rstrip('?')}",
            {"encabezados": {k: v for k, v in encabezados.items() if v},
             "parametros": request.args.to_dict() or None,
             "cuerpo": request.get_json(silent=True) if request.method in ("POST", "PUT", "PATCH") else None})
