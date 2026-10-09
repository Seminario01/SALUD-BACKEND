"""
Prueba de la MATRIZ DE PERMISOS: cada puesto contra cada permiso.

La matriz esperada está escrita AQUÍ, copiada del documento "Matriz de
permisos — Módulo Salud" (no se importa del backend): si el código se aparta
del documento, esta prueba lo detecta.

Para no cambiar datos, cada permiso se prueba con una petición que, si el
puesto SÍ tiene permiso, falla por validación (400) o por "no existe" (404);
y si NO lo tiene, responde 403. Solo las lecturas devuelven 200.

Requisitos: backend en 127.0.0.1:5050, simuladores y los usuarios de
keycloak-local/agregar_puestos.py.

Uso:  AUTH_ISSUER=http://localhost:8081/realms/rsd python pruebas/prueba_permisos.py
"""
import os
import sys

import requests

AUTH = os.getenv("AUTH_ISSUER", "http://localhost:8081/realms/rsd").rstrip("/")
API = "http://127.0.0.1:5050/api/v1/salud"

# usuario de prueba -> puestos (jefatura1 también es médico)
USUARIOS = {
    "medico1": {"MED"}, "enfermera1": {"ENF"}, "recepcion1": {"REC"}, "farmacia1": {"FAR"},
    "caja1": {"CAJA"}, "jefatura1": {"JEF", "MED"}, "admin.salud": {"ADM"},
    "ciudadano1": {"CIU"}, "analista1": {"AUD"},
}

# Matriz del documento: permiso -> puestos que lo tienen
MATRIZ = {
    "pacientes.ver":          {"MED", "ENF", "REC", "FAR", "CAJA", "JEF", "ADM"},
    "pacientes.registrar":    {"REC", "ADM"},
    "pacientes.antecedentes": {"MED", "ENF", "REC", "JEF"},
    "citas.ver":              {"MED", "ENF", "REC", "CAJA", "JEF", "ADM"},
    "citas.gestionar":        {"MED", "REC"},
    "turnos.generar":         {"ENF", "REC"},
    "turnos.atender":         {"MED", "ENF"},
    "turnos.ver_cola":        {"MED", "ENF", "REC", "JEF", "ADM"},
    "expediente.ver":         {"MED", "ENF", "JEF", "ADM"},
    "expediente.registrar":   {"MED"},
    "vacunacion.ver":         {"MED", "ENF", "JEF", "ADM"},
    "vacunacion.registrar":   {"MED", "ENF"},
    "vacunacion.anular":      {"JEF"},
    "recursos.ver":           {"MED", "ENF", "REC", "JEF", "ADM"},
    "recursos.gestionar":     {"ADM"},
    "recursos.camas":         {"ENF", "ADM"},
    "pagos.verificar":        {"CAJA", "REC", "ADM"},
    "hospitalizacion.ver":    {"MED", "ENF", "REC", "CAJA", "JEF", "ADM"},
    "hospitalizacion.ordenar": {"MED"},
    "hospitalizacion.camas":  {"ENF"},
    "hospitalizacion.notas":  {"MED", "ENF"},
    "recetas.ver":            {"MED", "ENF", "FAR", "CAJA", "JEF", "ADM"},
    "recetas.crear":          {"MED"},
    "recetas.anular":         {"MED", "JEF"},
    "recetas.despachar":      {"FAR"},
    "inventario.ver":         {"MED", "ENF", "FAR", "JEF", "ADM"},
    "inventario.gestionar":   {"FAR"},
    "panel.ver":              {"MED", "ENF", "REC", "FAR", "CAJA", "JEF", "ADM", "AUD"},
    "presupuesto.ver":        {"JEF", "ADM", "AUD"},
    "presupuesto.editar":     {"ADM"},
    "integraciones.ver":      {"JEF", "ADM"},
    "integraciones.demo":     {"JEF", "ADM"},
}


def token(usuario):
    r = requests.post(f"{AUTH}/protocol/openid-connect/token", data={
        "client_id": "rsd-test-cli", "grant_type": "password", "username": usuario, "password": "Demo2026*"})
    if r.status_code != 200:
        sys.exit(f"No se pudo obtener token de {usuario}: ¿corrió keycloak-local/agregar_puestos.py?")
    return r.json()["access_token"]


T = {u: token(u) for u in USUARIOS}


def pedir(usuario, metodo, ruta, **kw):
    return requests.request(metodo, API + ruta, headers={"Authorization": f"Bearer {T[usuario]}"}, timeout=15, **kw)


# Datos de referencia (los lee admin, que puede ver todo lo necesario)
paciente = pedir("admin.salud", "GET", "/pacientes").json()["data"][0]["id"]
medicamento = pedir("admin.salud", "GET", "/medicamentos").json()["data"][0]["id"]
cama = next(r["id"] for r in pedir("admin.salud", "GET", "/recursos").json()["data"] if r["tipo"] == "cama")


def denegado(r):
    return r.status_code == 403


# permiso -> función(usuario) que devuelve True si el sistema le CONCEDIÓ el permiso
PRUEBAS = {
    "pacientes.ver":          lambda u: not denegado(pedir(u, "GET", "/pacientes")),
    "pacientes.registrar":    lambda u: not denegado(pedir(u, "POST", "/pacientes", json={})),
    "pacientes.antecedentes": lambda u: not denegado(pedir(u, "GET", f"/pacientes/{paciente}/antecedentes")),
    # Sin el permiso, un usuario solo ve SUS citas (las de un solo paciente, o ninguna).
    "citas.ver":              lambda u: len({c["paciente_id"] for c in pedir(u, "GET", "/citas").json().get("data") or []}) > 1,
    "citas.gestionar":        lambda u: not denegado(pedir(u, "POST", "/citas", json={"paciente_id": paciente, "fecha_hora": "no-es-fecha"})),
    "turnos.generar":         lambda u: not denegado(pedir(u, "POST", "/turnos", json={})),
    "turnos.atender":         lambda u: not denegado(pedir(u, "PUT", "/turnos/999999/llamar")),
    # Sin el permiso, la cola se ve sin nombres de pacientes.
    "turnos.ver_cola":        lambda u: any("paciente" in t for t in pedir(u, "GET", "/turnos/activos").json()["data"]),
    "expediente.ver":         lambda u: not denegado(pedir(u, "GET", f"/expedientes/{paciente}")),
    "expediente.registrar":   lambda u: not denegado(pedir(u, "POST", f"/expedientes/{paciente}/atenciones", json={})),
    "vacunacion.ver":         lambda u: not denegado(pedir(u, "GET", "/vacunacion")),
    "vacunacion.registrar":   lambda u: not denegado(pedir(u, "POST", "/vacunacion", json={})),
    "vacunacion.anular":      lambda u: not denegado(pedir(u, "DELETE", "/vacunacion/999999")),
    "recursos.ver":           lambda u: not denegado(pedir(u, "GET", "/recursos")),
    "recursos.gestionar":     lambda u: not denegado(pedir(u, "POST", "/recursos", json={"tipo": "no-existe"})),
    "recursos.camas":         lambda u: not denegado(pedir(u, "PUT", f"/recursos/{cama}", json={"disponible": -1})),
    "pagos.verificar":        lambda u: not denegado(pedir(u, "POST", "/citas/999999/verificar-pago")),
    "hospitalizacion.ver":    lambda u: not denegado(pedir(u, "GET", "/camas")),
    "hospitalizacion.ordenar": lambda u: not denegado(pedir(u, "POST", "/hospitalizaciones", json={})),
    "hospitalizacion.camas":  lambda u: not denegado(pedir(u, "POST", "/hospitalizaciones/999999/asignar-cama", json={})),
    "hospitalizacion.notas":  lambda u: not denegado(pedir(u, "POST", "/hospitalizaciones/999999/notas", json={})),
    # Sin el permiso, un ciudadano solo ve SUS recetas.
    "recetas.ver":            lambda u: len({r["paciente_id"] for r in pedir(u, "GET", "/recetas").json().get("data") or []}) > 1,
    "recetas.crear":          lambda u: not denegado(pedir(u, "POST", "/recetas", json={})),
    "recetas.anular":         lambda u: not denegado(pedir(u, "POST", "/recetas/999999/anular")),
    "recetas.despachar":      lambda u: not denegado(pedir(u, "POST", "/recetas/999999/despachar")),
    "inventario.ver":         lambda u: not denegado(pedir(u, "GET", f"/medicamentos/{medicamento}/movimientos")),
    "inventario.gestionar":   lambda u: not denegado(pedir(u, "POST", "/medicamentos", json={})),
    "panel.ver":              lambda u: not denegado(pedir(u, "GET", "/panel")),
    "presupuesto.ver":        lambda u: not denegado(pedir(u, "GET", "/presupuesto/ejecucion")),
    "presupuesto.editar":     lambda u: not denegado(pedir(u, "PUT", "/presupuesto", json={})),
    "integraciones.ver":      lambda u: not denegado(pedir(u, "GET", "/integraciones/bitacora")),
    "integraciones.demo":     lambda u: not denegado(pedir(u, "POST", "/integraciones/simular/no-existe")),
}

assert set(PRUEBAS) == set(MATRIZ), "La prueba debe cubrir todos los permisos de la matriz"

fallas = []
usuarios = list(USUARIOS)
print(f"{'permiso':24}" + "".join(f"{u.split('.')[0][:9]:>10}" for u in usuarios))
for permiso, probar in PRUEBAS.items():
    fila = f"{permiso:24}"
    for u in usuarios:
        esperado = bool(USUARIOS[u] & MATRIZ[permiso])
        obtenido = probar(u)
        marca = ("si" if obtenido else "-") if obtenido == esperado else ("SI!" if obtenido else "NO!")
        if obtenido != esperado:
            fallas.append(f"{permiso} / {u}: esperado {'permitido' if esperado else 'denegado'}")
        fila += f"{marca:>10}"
    print(fila)

total = len(PRUEBAS) * len(usuarios)
print(f"\n{total - len(fallas)}/{total} celdas de la matriz correctas")
for f in fallas:
    print("FALLA", f)
sys.exit(1 if fallas else 0)
