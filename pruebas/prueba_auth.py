"""
Pruebas de autenticación y autorización del Módulo de Salud contra el Login Único.

Requiere: el Login Único (keycloak-local o URL del día) y el backend corriendo.
Uso (desde la carpeta SALUD-BACKEND):
    venv/Scripts/python.exe pruebas/prueba_auth.py        (Windows)
    python pruebas/prueba_auth.py                         (Linux)

Variables opcionales: AUTH_ISSUER (por defecto la réplica local) y MODULOS_API_KEY.
Es repetible: si los pacientes de prueba ya existen, los reutiliza.
"""
import json, os, sys, base64, tempfile, requests

TMP = tempfile.gettempdir()

AUTH = os.getenv("AUTH_ISSUER", "http://localhost:8081/realms/rsd").rstrip("/")
API = "http://127.0.0.1:5050/api/v1/salud"
resultados = []

def token(u):
    r = requests.post(f"{AUTH}/protocol/openid-connect/token", data={
        "client_id": "rsd-test-cli", "grant_type": "password", "username": u, "password": "Demo2026*"})
    return r.json()["access_token"]

def sub(t):
    p = t.split(".")[1]; p += "=" * (-len(p) % 4)
    return json.loads(base64.urlsafe_b64decode(p))["sub"]

def check(nombre, metodo, ruta, tok, esperado, **kw):
    h = {"Authorization": f"Bearer {tok}"} if tok else {}
    h.update(kw.pop("headers", {}))
    r = requests.request(metodo, API + ruta, headers=h, **kw)
    ok = r.status_code == esperado
    resultados.append(ok)
    print(f"{'OK ' if ok else 'FALLA'} {r.status_code} (esperado {esperado})  {nombre}")
    return r

T = {u: token(u) for u in ["medico1", "admin.salud", "ciudadano1", "ciudadano2"]}
modo = sys.argv[1] if len(sys.argv) > 1 else "completo"

if modo == "idp_apagado":
    tok = open(os.path.join(TMP, "tok_medico")).read()
    check("Keycloak apagado: medico1 con token ya emitido", "GET", "/pacientes", tok, 200)
    sys.exit(0 if all(resultados) else 1)

open(os.path.join(TMP, "tok_medico"), "w").write(T["medico1"])
open(os.path.join(TMP, "tok_ciu"), "w").write(T["ciudadano1"])

print("--- 401 / 200 / 403 (checklist del PDF)")
check("sin token", "GET", "/pacientes", None, 401)
check("token basura", "GET", "/pacientes", "abc.def.ghi", 401)
check("token con firma alterada", "GET", "/pacientes", T["medico1"][:-4] + "AAAA", 401)
check("medico1 lista pacientes", "GET", "/pacientes", T["medico1"], 200)
check("ciudadano1 lista pacientes -> rol insuficiente", "GET", "/pacientes", T["ciudadano1"], 403)
check("medico1 crea paciente -> solo admin/recepcion", "POST", "/pacientes", T["medico1"], 403, json={"nombre_completo": "X"})

print("--- datos de prueba (admin.salud)")
def paciente_de(usuario, nombre, cui):
    """Reutiliza el paciente vinculado al usuario si ya existe (script repetible)."""
    r = requests.get(API + "/pacientes/me", headers={"Authorization": f"Bearer {T[usuario]}"})
    if r.status_code == 200:
        print(f"OK       {usuario} ya tenia paciente vinculado (id {r.json()['data']['id']}), se reutiliza")
        return r.json()["data"]["id"]
    return check(f"admin crea paciente vinculado a {usuario}", "POST", "/pacientes", T["admin.salud"], 201,
                 json={"nombre_completo": nombre, "cui": cui, "usuario_sub": sub(T[usuario])}).json()["data"]["id"]

p1 = paciente_de("ciudadano1", "Carlos Perez", "1111")
p2 = paciente_de("ciudadano2", "Maria Garcia", "2222")
if requests.get(f"{API}/vacunacion/{p2}", headers={"Authorization": f"Bearer {T['medico1']}"}).status_code == 200:
    print("OK       p2 ya tenia registro de vacunacion, se reutiliza")
else:
    check("medico1 registra vacunacion p2", "POST", "/vacunacion", T["medico1"], 201, json={"paciente_id": p2})
check("medico1 registra atencion p2", "POST", f"/expedientes/{p2}/atenciones", T["medico1"], 201, json={"diagnostico": "Gripe"})
c2 = check("admin agenda cita p2", "POST", "/citas", T["admin.salud"], 201,
           json={"paciente_id": p2, "fecha_hora": "2026-10-01 10:00:00"}).json()["data"]["id"]

print("--- OWASP API1 BOLA: ciudadano1 intentando datos de ciudadano2")
check("ciudadano1 ve SU paciente", "GET", f"/pacientes/{p1}", T["ciudadano1"], 200)
check("ciudadano1 /pacientes/me", "GET", "/pacientes/me", T["ciudadano1"], 200)
check("ciudadano1 ve paciente ajeno", "GET", f"/pacientes/{p2}", T["ciudadano1"], 403)
check("ciudadano1 ve id inexistente (no revela)", "GET", "/pacientes/9999", T["ciudadano1"], 403)
check("ciudadano1 edita paciente ajeno", "PUT", f"/pacientes/{p2}", T["ciudadano1"], 403, json={"telefono": "1"})
check("ciudadano1 edita SU paciente", "PUT", f"/pacientes/{p1}", T["ciudadano1"], 200, json={"telefono": "5555"})
check("ciudadano1 ve expediente ajeno", "GET", f"/expedientes/{p2}", T["ciudadano1"], 403)
check("ciudadano2 ve SU expediente", "GET", f"/expedientes/{p2}", T["ciudadano2"], 200)
check("ciudadano1 ve vacunacion ajena", "GET", f"/vacunacion/{p2}", T["ciudadano1"], 403)
check("ciudadano2 ve SU vacunacion", "GET", f"/vacunacion/{p2}", T["ciudadano2"], 200)
r = check("ciudadano1 lista citas", "GET", "/citas", T["ciudadano1"], 200)
ok = all(c["paciente_id"] == p1 for c in r.json()["data"]); resultados.append(ok); print(f"{'OK ' if ok else 'FALLA'}      ciudadano1 solo recibe SUS citas ({len(r.json()['data'])} citas, todas del paciente {p1})")
r = check("ciudadano1 lista citas con ?paciente_id ajeno", "GET", f"/citas?paciente_id={p2}", T["ciudadano1"], 200)
ok = all(c["paciente_id"] == p1 for c in r.json()["data"]); resultados.append(ok); print(f"{'OK ' if ok else 'FALLA'}      el filtro ?paciente_id ajeno no se salta la regla")
check("ciudadano1 agenda cita a nombre de otro", "POST", "/citas", T["ciudadano1"], 403, json={"paciente_id": p2, "fecha_hora": "2026-10-02 10:00:00"})
check("ciudadano1 cancela cita ajena", "DELETE", f"/citas/{c2}", T["ciudadano1"], 403)
check("ciudadano1 agenda SU cita", "POST", "/citas", T["ciudadano1"], 201, json={"paciente_id": p1, "fecha_hora": "2026-10-03 09:00:00"})
check("ciudadano2 cancela SU cita", "DELETE", f"/citas/{c2}", T["ciudadano2"], 200)
check("medico1 ve expediente de cualquiera", "GET", f"/expedientes/{p2}", T["medico1"], 200)
check("medico1 lista citas", "GET", "/citas", T["medico1"], 200)

print("--- Panel del frontend (token, sin API key)")
check("panel sin token", "GET", "/panel", None, 401)
check("ciudadano1 en panel -> solo personal", "GET", "/panel", T["ciudadano1"], 403)
r = check("medico1 en panel", "GET", "/panel", T["medico1"], 200)
ok = "citas" in r.json()["data"] and "recursos_hospitalarios" in r.json()["data"]; resultados.append(ok)
print(f"{'OK ' if ok else 'FALLA'}      panel trae el mismo formato que /indicadores")

print("--- Validaciones de datos (formularios)")
check("vacunacion duplicada -> 409", "POST", "/vacunacion", T["medico1"], 409, json={"paciente_id": p2})
check("vacunacion de paciente inexistente -> 404", "POST", "/vacunacion", T["medico1"], 404, json={"paciente_id": 999999})
check("atencion sin diagnostico -> 400", "POST", f"/expedientes/{p2}/atenciones", T["medico1"], 400, json={"notas": "x"})
cita_p1 = check("cita de p1 para probar", "POST", "/citas", T["admin.salud"], 201,
                json={"paciente_id": p1, "fecha_hora": "2026-11-01 08:00:00"}).json()["data"]["id"]
check("atencion con cita de OTRO paciente -> 400", "POST", f"/expedientes/{p2}/atenciones", T["medico1"], 400,
      json={"diagnostico": "X", "cita_id": cita_p1})
check("recurso con tipo invalido -> 400", "POST", "/recursos", T["admin.salud"], 400, json={"tipo": "helicoptero", "total": 1})
check("recurso con disponible > total -> 400", "POST", "/recursos", T["admin.salud"], 400,
      json={"tipo": "cama", "disponible": 15, "total": 10})
check("recurso con numeros negativos -> 400", "POST", "/recursos", T["admin.salud"], 400,
      json={"tipo": "ambulancia", "disponible": -1, "total": 2})
check("medico no puede crear recursos -> 403", "POST", "/recursos", T["medico1"], 403, json={"tipo": "cama", "total": 1})

print("--- API key (entre modulos) sigue igual")
check("indicadores sin api key", "GET", "/indicadores", None, 401)
check("indicadores con api key", "GET", "/indicadores", None, 200, headers={"X-API-Key": os.getenv("MODULOS_API_KEY", "clave-temporal-cambiar")})

print(f"\n{sum(resultados)}/{len(resultados)} pruebas OK")
sys.exit(0 if all(resultados) else 1)
