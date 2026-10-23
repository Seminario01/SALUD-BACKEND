"""
Registro de las consultas de Auditoría Social a Salud (también las RECHAZADAS).

Los servicios para Auditoría (indicadores, ejecución del presupuesto y el tablero de la ingeniera)
se pueden pedir con X-API-Key o con el token del Login Único. Antes solo quedaban en la bitácora de
integraciones las llamadas con clave; ahora cada intento queda ahí (módulo "Auditoría", entrante),
con quién lo hizo (qué credencial mandó) y, si se rechazó, el motivo. Así se puede demostrar que el
servicio está listo y, si el tablero no recibe datos, ver qué le falta.

Las llamadas con X-API-Key a routes/externos.py ya las registra ese archivo: aquí no se repiten.
"""
import time

from flask import g, request

from auth import _sin_verificar, modulo_de_la_clave
from bitacora import registrar, resumir

RUTAS = {
    "/api/v1/salud/indicadores": "Indicadores agregados",
    "/api/v1/salud/presupuesto/ejecucion": "Ejecución presupuestaria",
    "/api/v1/salud/auditoria/indicadores": "Tablero de Auditoría (indicadores por rango)",
    "/api/indicadores": "Tablero de Auditoría (indicadores por rango)",
    "/api/v1/indicadores": "Tablero de Auditoría (indicadores por rango)",
}
CABECERA_PRUEBA = "X-Prueba-Panel"      # la manda el botón "Probar ahora" del panel


def es_ruta_auditoria():
    return request.path in RUTAS


def credencial():
    """Qué credencial mandó (para mostrarla; nunca se usa para dar acceso)."""
    clave = request.headers.get("X-API-Key")
    if clave:
        modulo = modulo_de_la_clave(clave)
        return "Auditoría" if modulo == "Auditoría" else (modulo or "Otro"), \
            (f"clave de {modulo}" if modulo and modulo != "Común" else "clave común" if modulo else "clave que no es de Salud")
    autorizacion = request.headers.get("Authorization", "")
    if autorizacion.startswith("Bearer "):
        datos = _sin_verificar(autorizacion.split(" ", 1)[1].strip())
        quien = datos.get("preferred_username") or datos.get("azp") or "desconocido"
        return "Auditoría", f"token de {quien}"
    return "Auditoría", "sin clave ni token"


def inicio():
    if es_ruta_auditoria():
        g._inicio_auditoria = time.perf_counter()


def registrar_consulta(respuesta):
    """after_request: anota la consulta a un servicio de Auditoría (aunque se haya rechazado)."""
    try:
        if not es_ruta_auditoria() or request.method != "GET":
            return respuesta
        if request.headers.get("X-API-Key") and request.blueprint == "externos":
            return respuesta                      # ya la anota routes/externos.py
        modulo, quien = credencial()
        try:
            cuerpo = respuesta.get_json(silent=True) or {}
        except Exception:  # noqa: BLE001
            cuerpo = {}
        if respuesta.status_code < 400:
            resultado = "ok"
            datos = cuerpo.get("data", cuerpo) if isinstance(cuerpo, dict) else cuerpo
            motivo = resumir(datos) or (f"{len(cuerpo.get('indicadores', []))} indicadores" if isinstance(cuerpo, dict) else None)
        else:
            resultado = (cuerpo.get("error") if isinstance(cuerpo, dict) else None) or f"error_{respuesta.status_code}"
            motivo = (cuerpo.get("message") or cuerpo.get("mensaje")) if isinstance(cuerpo, dict) else None
        prueba = request.headers.get(CABECERA_PRUEBA) == "1"
        agente = (request.headers.get("User-Agent") or "")[:40]
        partes = ["Prueba desde el panel" if prueba else None, quien, motivo, agente]
        inicio_ms = getattr(g, "_inicio_auditoria", None)
        registrar("entrante", modulo, RUTAS[request.path], "GET", request.full_path.rstrip("?"), respuesta.status_code,
                  resultado, round((time.perf_counter() - inicio_ms) * 1000) if inicio_ms else None, prueba,
                  " · ".join(p for p in partes if p))
    except Exception:  # noqa: BLE001 - registrar nunca debe romper la respuesta
        pass
    return respuesta
