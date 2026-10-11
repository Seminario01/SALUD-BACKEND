"""
Prueba del endpoint de confirmación de pago que Tributario envía a Salud
(POST /api/v1/salud/pagos/confirmacion).

A diferencia de prueba_auth.py y prueba_permisos.py (que requieren el backend
y Keycloak corriendo), esta usa el cliente de pruebas de Flask y una base
SQLite en memoria: no requiere MySQL ni servicios externos.

Uso:  python pruebas/prueba_confirmacion_pago.py
"""
import os
import sys
from datetime import datetime

os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["MODULOS_API_KEY"] = "clave-prueba"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import crear_app  # noqa: E402
from extensions import db  # noqa: E402
from models import CitaMedica, Paciente  # noqa: E402

API_KEY = "clave-prueba"
RUTA = "/api/v1/salud/pagos/confirmacion"
resultados = []

app = crear_app()
cliente = app.test_client()


def check(nombre, esperado, respuesta):
    ok = respuesta.status_code == esperado
    resultados.append(ok)
    print(f"{'OK ' if ok else 'FALLA'} {respuesta.status_code} (esperado {esperado})  {nombre}")
    return respuesta


def verificar(nombre, condicion):
    resultados.append(bool(condicion))
    print(f"{'OK ' if condicion else 'FALLA'}       {nombre}")


def confirmar(headers=None, **body):
    h = {"X-API-Key": API_KEY}
    h.update(headers or {})
    return cliente.post(RUTA, json=body, headers=h)


def crear_cita(numero_referencia, costo=150.00):
    cita = CitaMedica(paciente_id=paciente_id, fecha_hora=datetime(2026, 10, 15, 10, 0, 0),
                      numero_referencia=numero_referencia, costo=costo)
    db.session.add(cita)
    db.session.commit()
    return cita.id


with app.app_context():
    paciente = Paciente(nombre_completo="Paciente de prueba", cui="1234567890101")
    db.session.add(paciente)
    db.session.commit()
    paciente_id = paciente.id
    cita_aprobada = crear_cita("SAL-2026-000001")
    cita_monto = crear_cita("SAL-2026-000002")
    cita_pendiente = crear_cita("SAL-2026-000003")

check("sin API key", 401, cliente.post(RUTA, json={"evento_id": "E1", "data": {"numero_referencia": "SAL-2026-000001"}}))

check("referencia inexistente", 404, confirmar(evento_id="EVT-1", data={"numero_referencia": "NO-EXISTE"}))

check("confirmacion aprobada", 200, confirmar(evento_id="EVT-APROBADO", data={
    "numero_referencia": "SAL-2026-000001", "referencia_tributario": "REF-TRIB-000001",
    "estado": "APROBADO", "numero_autorizacion": "AUT-123", "monto_pagado": "150.00",
    "fecha_pago": "2026-10-15T09:00:00",
}))
with app.app_context():
    verificar("la cita queda marcada como pagada", bool(CitaMedica.query.get(cita_aprobada).pago_confirmado))

check("evento repetido no duplica", 200, confirmar(evento_id="EVT-APROBADO", data={"numero_referencia": "SAL-2026-000001"}))

check("monto distinto no coincide", 409, confirmar(evento_id="EVT-MONTO", data={
    "numero_referencia": "SAL-2026-000002", "estado": "APROBADO", "monto_pagado": "999.00"}))
with app.app_context():
    verificar("la cita con monto distinto sigue sin pagar", not CitaMedica.query.get(cita_monto).pago_confirmado)

check("estado no aprobado", 200, confirmar(evento_id="EVT-PENDIENTE", data={
    "numero_referencia": "SAL-2026-000003", "estado": "PENDIENTE"}))
with app.app_context():
    verificar("la cita con estado no aprobado sigue sin pagar", not CitaMedica.query.get(cita_pendiente).pago_confirmado)

print(f"\n{sum(resultados)}/{len(resultados)} pruebas correctas")
sys.exit(0 if all(resultados) else 1)
