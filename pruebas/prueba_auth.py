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
import re
from datetime import datetime, timedelta


def futuro(dias, hora):
    """Fecha de cita a `dias` días, a la `hora` y con el minuto actual: las citas no pueden
    ir en el pasado ni repetirse a la misma hora, así cada corrida usa una hora distinta."""
    momento = datetime.now() + timedelta(days=dias)
    return momento.replace(hour=hora, second=0, microsecond=0).strftime("%Y-%m-%d %H:%M:%S")

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

def dato(nombre, ok):
    resultados.append(ok)
    print(f"{'OK ' if ok else 'FALLA'}      {nombre}")


T = {u: token(u) for u in ["medico1", "admin.salud", "ciudadano1", "ciudadano2", "analista1"]}
try:
    T["recepcion1"] = token("recepcion1")       # puestos de la matriz (agregar_puestos.py)
    T["farmacia1"] = token("farmacia1")
    T["jefatura1"] = token("jefatura1")
    T["enfermera1"] = token("enfermera1")
    T["caja1"] = token("caja1")
except Exception:                              # noqa: BLE001
    sys.exit("Faltan los usuarios de los puestos: corra keycloak-local/agregar_puestos.py")
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

p1 = paciente_de("ciudadano1", "Carlos Perez", "1111111111111")
p2 = paciente_de("ciudadano2", "Maria Garcia", "2222222222222")
if requests.get(f"{API}/vacunacion/{p2}", headers={"Authorization": f"Bearer {T['medico1']}"}).status_code == 200:
    print("OK       p2 ya tenia registro de vacunacion, se reutiliza")
else:
    check("medico1 registra vacunacion p2", "POST", "/vacunacion", T["medico1"], 201, json={"paciente_id": p2})
check("medico1 registra atencion p2", "POST", f"/expedientes/{p2}/atenciones", T["medico1"], 201, json={"diagnostico": "Gripe"})
c2 = check("recepcion1 agenda cita p2", "POST", "/citas", T["recepcion1"], 201,
           json={"paciente_id": p2, "fecha_hora": futuro(1, 10)}).json()["data"]["id"]

print("--- OWASP API1 BOLA: ciudadano1 intentando datos de ciudadano2")
check("ciudadano1 ve SU paciente", "GET", f"/pacientes/{p1}", T["ciudadano1"], 200)
check("ciudadano1 /pacientes/me", "GET", "/pacientes/me", T["ciudadano1"], 200)
check("ciudadano1 ve paciente ajeno", "GET", f"/pacientes/{p2}", T["ciudadano1"], 403)
check("ciudadano1 ve id inexistente (no revela)", "GET", "/pacientes/9999", T["ciudadano1"], 403)
check("ciudadano1 edita paciente ajeno", "PUT", f"/pacientes/{p2}", T["ciudadano1"], 403, json={"telefono": "1"})
check("ciudadano1 edita SU paciente", "PUT", f"/pacientes/{p1}", T["ciudadano1"], 200, json={"telefono": "55551234"})
check("ciudadano1 ve expediente ajeno", "GET", f"/expedientes/{p2}", T["ciudadano1"], 403)
check("ciudadano2 ve SU expediente", "GET", f"/expedientes/{p2}", T["ciudadano2"], 200)
check("ciudadano1 ve vacunacion ajena", "GET", f"/vacunacion/{p2}", T["ciudadano1"], 403)
check("ciudadano2 ve SU vacunacion", "GET", f"/vacunacion/{p2}", T["ciudadano2"], 200)
r = check("ciudadano1 lista citas", "GET", "/citas", T["ciudadano1"], 200)
ok = all(c["paciente_id"] == p1 for c in r.json()["data"]); resultados.append(ok); print(f"{'OK ' if ok else 'FALLA'}      ciudadano1 solo recibe SUS citas ({len(r.json()['data'])} citas, todas del paciente {p1})")
r = check("ciudadano1 lista citas con ?paciente_id ajeno", "GET", f"/citas?paciente_id={p2}", T["ciudadano1"], 200)
ok = all(c["paciente_id"] == p1 for c in r.json()["data"]); resultados.append(ok); print(f"{'OK ' if ok else 'FALLA'}      el filtro ?paciente_id ajeno no se salta la regla")
check("ciudadano1 agenda cita a nombre de otro", "POST", "/citas", T["ciudadano1"], 403, json={"paciente_id": p2, "fecha_hora": futuro(2, 10)})
check("ciudadano1 cancela cita ajena", "DELETE", f"/citas/{c2}", T["ciudadano1"], 403)
check("ciudadano1 agenda SU cita", "POST", "/citas", T["ciudadano1"], 201, json={"paciente_id": p1, "fecha_hora": futuro(3, 9)})
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
cita_p1 = check("cita de p1 para probar", "POST", "/citas", T["recepcion1"], 201,
                json={"paciente_id": p1, "fecha_hora": futuro(18, 8)}).json()["data"]["id"]
check("atencion con cita de OTRO paciente -> 400", "POST", f"/expedientes/{p2}/atenciones", T["medico1"], 400,
      json={"diagnostico": "X", "cita_id": cita_p1})
check("recurso con tipo invalido -> 400", "POST", "/recursos", T["admin.salud"], 400, json={"tipo": "helicoptero", "total": 1})
check("recurso con disponible > total -> 400", "POST", "/recursos", T["admin.salud"], 400,
      json={"tipo": "cama", "disponible": 15, "total": 10})
check("recurso con numeros negativos -> 400", "POST", "/recursos", T["admin.salud"], 400,
      json={"tipo": "ambulancia", "disponible": -1, "total": 2})
check("medico no puede crear recursos -> 403", "POST", "/recursos", T["medico1"], 403, json={"tipo": "cama", "total": 1})

print("--- Auditoría Social (analista1: solo lectura de datos agregados)")
check("analista1 ve el panel de indicadores", "GET", "/panel", T["analista1"], 200)
check("analista1 consulta /indicadores con su token (sin API key)", "GET", "/indicadores", T["analista1"], 200)
check("analista1 consulta /presupuesto/ejecucion con su token", "GET", "/presupuesto/ejecucion", T["analista1"], 200)
check("ciudadano1 NO puede usar /indicadores con su token", "GET", "/indicadores", T["ciudadano1"], 403)
check("analista1 NO ve el listado de pacientes (datos personales)", "GET", "/pacientes", T["analista1"], 403)
check("analista1 NO ve expedientes", "GET", f"/expedientes/{p1}", T["analista1"], 403)
check("/indicadores sin credenciales", "GET", "/indicadores", None, 401)

print("--- Validación de datos (pruebas de QA: vacíos, nulos, tipos y formatos incorrectos)")
for nombre, valor in [("Bearer null", "Bearer null"), ("Bearer undefined", "Bearer undefined"),
                      ("Bearer vacío", "Bearer "), ("token alterado", "Bearer " + T["admin.salud"][:-4] + "AAAA")]:
    r = requests.get(API + "/pacientes", headers={"Authorization": valor})
    dato(f"{nombre} -> 401 ({r.status_code})", r.status_code == 401)
A = T["admin.salud"]
for nombre, cuerpo in [("cuerpo null", "null"), ("cuerpo arreglo", "[]"), ("JSON mal escrito", "{malo"), ("texto suelto", "hola")]:
    r = requests.post(API + "/pacientes", data=cuerpo,
                      headers={"Authorization": f"Bearer {A}", "Content-Type": "application/json"})
    dato(f"{nombre} -> 400 en JSON ({r.status_code})", r.status_code == 400 and r.json().get("success") is False)
for nombre, cuerpo in [
        ("sin nombre", {}), ("nombre null", {"nombre_completo": None}), ("nombre solo espacios", {"nombre_completo": "   "}),
        ("nombre número", {"nombre_completo": 123}), ("nombre lista", {"nombre_completo": ["Ana"]}),
        ("nombre de 5000 caracteres", {"nombre_completo": "x" * 5000}),
        ("CUI de 4 dígitos", {"nombre_completo": "Ana López", "cui": "1111"}),
        ("CUI con letras", {"nombre_completo": "Ana López", "cui": "25011234501AB"}),
        ("fecha de nacimiento futura", {"nombre_completo": "Ana López", "fecha_nacimiento": "2999-01-01"}),
        ("fecha imposible", {"nombre_completo": "Ana López", "fecha_nacimiento": "2020-13-45"}),
        ("género fuera de la lista", {"nombre_completo": "Ana López", "genero": "X"}),
        ("teléfono con letras", {"nombre_completo": "Ana López", "telefono": "abcdefgh"}),
        ("seguro fuera de la lista", {"nombre_completo": "Ana López", "tipo_seguro": "Otro"})]:
    check(f"registrar paciente: {nombre}", "POST", "/pacientes", A, 400, json=cuerpo)
check("registrar paciente con CUI repetido", "POST", "/pacientes", A, 409,
      json={"nombre_completo": "Copia", "cui": "2501123450102"})
check("editar paciente: nombre vacío", "PUT", f"/pacientes/{p2}", A, 400, json={"nombre_completo": ""})
check("editar paciente: CUI de otro paciente", "PUT", f"/pacientes/{p2}", A, 409, json={"cui": "2501123450102"})
r = check("SQL en la búsqueda no rompe nada", "GET", "/pacientes?q=' OR 1=1 --", A, 200)
dato("la búsqueda con SQL no devuelve todos los pacientes", r.json()["data"] == [])
check("cita con estado inventado", "PUT", f"/citas/{c2}", T["recepcion1"], 400, json={"estado": "borrada"})
check("servicio con costo NaN", "POST", "/servicios", A, 400,
      json={"codigo": "QA-1", "nombre": "Prueba", "categoria": "IMAGEN", "costo": "NaN"})
check("servicio con costo negativo", "POST", "/servicios", A, 400,
      json={"codigo": "QA-1", "nombre": "Prueba", "categoria": "IMAGEN", "costo": -5})
print("--- Reglas de negocio")
R = T["recepcion1"]
check("cita en el pasado", "POST", "/citas", R, 400, json={"paciente_id": p2, "fecha_hora": "2020-01-01 10:00"})
check("cita a más de un año", "POST", "/citas", R, 400, json={"paciente_id": p2, "fecha_hora": futuro(400, 10)})
check("cita con fecha imposible", "POST", "/citas", R, 400, json={"paciente_id": p2, "fecha_hora": "2026-02-30 10:00"})
check("cita de paciente que no existe", "POST", "/citas", R, 404, json={"paciente_id": 999999, "fecha_hora": futuro(5, 10)})
check("cita con paciente_id de texto", "POST", "/citas", R, 400, json={"paciente_id": "abc", "fecha_hora": futuro(5, 10)})
hora = futuro(6, 11)
check("cita nueva", "POST", "/citas", R, 201, json={"paciente_id": p2, "fecha_hora": hora})
check("misma cita a la misma hora -> 409", "POST", "/citas", R, 409, json={"paciente_id": p2, "fecha_hora": hora})
check("reprogramar cita al pasado", "PUT", f"/citas/{c2}", R, 400, json={"fecha_hora": "2020-01-01 10:00"})
check("turno con prioridad inventada", "POST", "/turnos", R, 400,
      json={"paciente_id": p2, "tipo_atencion": "consulta_general", "prioridad": "vip"})
primero = requests.post(API + "/turnos", headers={"Authorization": f"Bearer {R}"},
                        json={"paciente_id": p2, "tipo_atencion": "consulta_general"}).status_code
dato(f"turno de p2 ({primero}: 201 nuevo o 409 si ya estaba en la fila)", primero in (201, 409))
check("segundo turno activo del mismo paciente hoy -> 409", "POST", "/turnos", R, 409,
      json={"paciente_id": p2, "tipo_atencion": "consulta_general"})
check("presupuesto: ejecutado mayor al asignado", "PUT", "/presupuesto", A, 400,
      json={"periodo": "2026-Q4", "monto_asignado": 100, "monto_ejecutado_servicio_social": 500})
check("presupuesto: periodo inventado", "PUT", "/presupuesto", A, 400,
      json={"periodo": "ayer", "monto_asignado": 100})
check("receta con un medicamento que no es objeto", "POST", "/recetas", T["medico1"], 400,
      json={"paciente_id": p2, "items": [5]})
check("receta con cantidad 0", "POST", "/recetas", T["medico1"], 400,
      json={"paciente_id": p2, "items": [{"medicamento_id": 1, "cantidad": 0}]})
check("vacunación con es_estudiante de texto", "PUT", f"/vacunacion/{p2}", T["medico1"], 400, json={"es_estudiante": "si"})

print("--- Documentos para imprimir: receta y estado de cuenta (GET /recetas/{id}, /cuentas/{id})")
recetas_p2 = requests.get(API + "/recetas", params={"paciente_id": p2},
                          headers={"Authorization": f"Bearer {T['medico1']}"}).json()["data"]
if recetas_p2:
    rid = recetas_p2[0]["id"]
    r = check("médico ve una receta para imprimir", "GET", f"/recetas/{rid}", T["medico1"], 200)
    d = r.json()["data"]
    dato("la receta trae paciente, DPI, médico y medicamentos",
         bool(d.get("paciente")) and "paciente_cui" in d and isinstance(d.get("items"), list))
    check("ciudadano2 ve SU receta", "GET", f"/recetas/{rid}", T["ciudadano2"], 200)
    check("ciudadano1 NO ve la receta de otro (404, no revela)", "GET", f"/recetas/{rid}", T["ciudadano1"], 404)
check("receta que no existe", "GET", "/recetas/999999", T["medico1"], 404)
r = requests.get(API + "/recetas", headers={"Authorization": f"Bearer {T['medico1']}"}).json()["data"]
dato("la lista de recetas trae el DPI para buscar", bool(r) and "paciente_cui" in r[0])

print("--- Tablero de Auditoría: GET /auditoria/indicadores?desde=&hasta= (rol auditoria:lectura)")
try:
    T["auditor1"] = token("auditor1")
except Exception:                              # noqa: BLE001
    sys.exit("Falta el usuario auditor1 (rol auditoria:lectura): corra keycloak-local/agregar_puestos.py")
AUD = "/auditoria/indicadores"
RANGO = "?desde=2026-01-01&hasta=2026-12-31"
check("tablero sin token", "GET", AUD + RANGO, None, 401)
check("tablero con token alterado", "GET", AUD + RANGO, T["auditor1"][:-4] + "AAAA", 401)
check("ciudadano1 en el tablero -> sin el rol", "GET", AUD + RANGO, T["ciudadano1"], 403)
r = check("analista1 en el tablero -> sin el rol auditoria:lectura", "GET", AUD + RANGO, T["analista1"], 403)
dato("cuerpo de error uniforme (error, mensaje)", set(r.json()) == {"error", "mensaje"})
check("tablero sin desde ni hasta", "GET", AUD, T["auditor1"], 400)
check("tablero sin hasta", "GET", AUD + "?desde=2026-01-01", T["auditor1"], 400)
check("tablero con fecha en otro formato", "GET", AUD + "?desde=01/01/2026&hasta=2026-12-31", T["auditor1"], 400)
check("tablero con fecha que no existe", "GET", AUD + "?desde=2026-02-30&hasta=2026-12-31", T["auditor1"], 400)
r = check("tablero con hasta anterior a desde", "GET", AUD + "?desde=2026-12-31&hasta=2026-01-01", T["auditor1"], 400)
dato("error rango_invalido", r.json().get("error") == "rango_invalido")
t = check("auditor1 consulta el tablero", "GET", AUD + RANGO, T["auditor1"], 200).json()
UNIDADES = {"citas", "personas", "casos", "dias", "porcentaje", "quetzales"}
dato("indicadores: clave en minúsculas con guiones bajos, sin repetir",
     all(re.fullmatch(r"[a-z][a-z0-9_]*", i["clave"]) for i in t["indicadores"])
     and len({i["clave"] for i in t["indicadores"]}) == len(t["indicadores"]) > 0)
dato("indicadores: valor numérico y unidad de la lista",
     all(type(i["valor"]) in (int, float) and i["unidad"] in UNIDADES and i["etiqueta"] for i in t["indicadores"]))
dato("series: 12 puntos con x = YYYY-MM y valor numérico",
     all(len(s["puntos"]) == 12 and s["unidad"] in UNIDADES
         and all(re.fullmatch(r"\d{4}-\d{2}", p["x"]) and type(p["valor"]) in (int, float) for p in s["puntos"])
         for s in t["series"]) and len(t["series"]) > 0)
atendidas = next(i["valor"] for i in t["indicadores"] if i["clave"] == "citas_atendidas")
dato("la serie mensual de citas atendidas suma lo mismo que el indicador",
     sum(p["valor"] for s in t["series"] if s["clave"] == "citas_atendidas" for p in s["puntos"]) == atendidas)
dato("tablero sin datos personales", not re.search(r"cui|nombre_completo|telefono", json.dumps(t)))
check("auditor1 NO ve pacientes", "GET", "/pacientes", T["auditor1"], 403)
check("auditor1 NO ve el panel del personal", "GET", "/panel", T["auditor1"], 403)

print("--- Tablero de Auditoría: rutas alternas /api/indicadores y /api/v1/indicadores")
RAIZ = API.split("/api/")[0]
H_AUD = {"Authorization": f"Bearer {T['auditor1']}"}
principal = requests.get(API + AUD + RANGO, headers=H_AUD).json()
for alias in ("/api/indicadores", "/api/v1/indicadores"):
    r = requests.get(RAIZ + alias + RANGO)
    dato(f"{alias} sin token -> 401 ({r.status_code})", r.status_code == 401)
    r = requests.get(RAIZ + alias + RANGO, headers={"Authorization": f"Bearer {T['ciudadano1']}"})
    dato(f"{alias} sin el rol -> 403 ({r.status_code})", r.status_code == 403 and set(r.json()) == {"error", "mensaje"})
    r = requests.get(RAIZ + alias + "?desde=2026-12-31&hasta=2026-01-01", headers=H_AUD)
    dato(f"{alias} rango al revés -> 400 rango_invalido ({r.status_code})",
         r.status_code == 400 and r.json().get("error") == "rango_invalido")
    r = requests.get(RAIZ + alias + RANGO, headers=H_AUD)
    dato(f"{alias} con auditor1 -> 200 y lo mismo que la ruta principal ({r.status_code})",
         r.status_code == 200 and r.json() == principal)

print("--- Integración con otros módulos (Salud consume sus servicios)")
r = check("estado de integraciones (admin)", "GET", "/integraciones/estado", T["admin.salud"], 200)
estado = r.json()["data"]
print("         " + ", ".join(f"{m}: {e['estado']}{' (simulador)' if e['simulado'] else ''}" for m, e in estado.items()))
check("ciudadano1 NO consulta integraciones", "GET", "/integraciones/estado", T["ciudadano1"], 403)
check("ciudadano1 NO consulta antecedentes", "GET", f"/pacientes/{p1}/antecedentes", T["ciudadano1"], 403)
if all(e["estado"] == "conectado" and e["simulado"] for e in estado.values()):
    # El CUI es único: se reutiliza el paciente si ya existe (script repetible)
    previo = requests.get(API + "/pacientes", params={"q": "3000000000009"},
                          headers={"Authorization": f"Bearer {T['admin.salud']}"}).json()["data"]
    riesgo = previo[0]["id"] if previo else check(
        "admin registra paciente con CUI que termina en 9", "POST", "/pacientes", T["admin.salud"], 201,
        json={"nombre_completo": "Paciente Riesgo Prueba", "cui": "3000000000009"}).json()["data"]["id"]
    d = check("Seguridad: antecedentes de riesgo ALTO", "GET", f"/pacientes/{riesgo}/antecedentes", T["medico1"], 200).json()["data"]
    ok = d.get("tieneAntecedentes") is True and d.get("nivelRiesgo") == "ALTO" and d.get("requiereCustodia") is True
    resultados.append(ok); print(f"{'OK ' if ok else 'FALLA'}      requiereCustodia=True, nivelRiesgo=ALTO")
    pacientes = requests.get(API + "/pacientes", headers={"Authorization": f"Bearer {T['medico1']}"}).json()["data"]
    sin_antecedentes = next(x["id"] for x in pacientes if x.get("cui") == "2501123450102")   # demo, termina en 2
    d = check("Seguridad: paciente sin antecedentes", "GET", f"/pacientes/{sin_antecedentes}/antecedentes", T["medico1"], 200).json()["data"]
    ok = d.get("tieneAntecedentes") is False; resultados.append(ok); print(f"{'OK ' if ok else 'FALLA'}      tieneAntecedentes=False")
    d = check("Educación: CUI par es estudiante", "GET", "/educacion/estudiantes/2222", T["medico1"], 200).json()["data"]
    ok = d.get("esEstudiante") is True and bool(d.get("establecimiento")); resultados.append(ok)
    print(f"{'OK ' if ok else 'FALLA'}      esEstudiante=True, establecimiento={d.get('establecimiento')}")
    d = check("Educación: CUI impar no es estudiante", "GET", "/educacion/estudiantes/1111", T["medico1"], 200).json()["data"]
    ok = d.get("esEstudiante") is False; resultados.append(ok); print(f"{'OK ' if ok else 'FALLA'}      esEstudiante=False")
    d = check("Tributario: verificar pago de una cita", "POST", f"/citas/{cita_p1}/verificar-pago", T["admin.salud"], 200).json()["data"]
    ok = d.get("pagoConfirmado") is True; resultados.append(ok); print(f"{'OK ' if ok else 'FALLA'}      pagoConfirmado=True, referencia {d.get('numeroReferencia')}")
    citas = requests.get(API + "/citas", headers={"Authorization": f"Bearer {T['admin.salud']}"}).json()["data"]
    ok = any(c["id"] == cita_p1 and c["pago_confirmado"] for c in citas); resultados.append(ok)
    print(f"{'OK ' if ok else 'FALLA'}      la cita queda marcada como pagada")
    ok = bool(re.fullmatch(r"SAL-\d{4}-\d{6}", d.get("numeroReferencia") or "")); resultados.append(ok)
    print(f"{'OK ' if ok else 'FALLA'}      obligación registrada con referencia {d.get('numeroReferencia')}")

    print("--- Tributario: obligaciones de pago")
    cita_cobro = check("cita nueva para cobrar", "POST", "/citas", T["recepcion1"], 201,
                       json={"paciente_id": p1, "fecha_hora": futuro(19, 8)}).json()["data"]["id"]
    d = check("recepcion1 envía el cobro a Tributario", "POST", f"/citas/{cita_cobro}/cobro", T["recepcion1"], 200).json()["data"]
    ok = d.get("estadoCobro") == "PENDIENTE" and bool(d.get("fechaVencimiento")); resultados.append(ok)
    print(f"{'OK ' if ok else 'FALLA'}      estado PENDIENTE, vence {d.get('fechaVencimiento')}, referencia {d.get('numeroReferencia')}")
    d2 = check("reenviar el cobro no lo duplica", "POST", f"/citas/{cita_cobro}/cobro", T["recepcion1"], 200).json()["data"]
    ok = d2.get("numeroReferencia") == d.get("numeroReferencia"); resultados.append(ok)
    print(f"{'OK ' if ok else 'FALLA'}      misma referencia")
    check("medico1 NO envía cobros", "POST", f"/citas/{cita_cobro}/cobro", T["medico1"], 403)
    clave = {"X-API-Key": os.getenv("MODULOS_API_KEY", "clave-temporal-cambiar")}
    check("aviso de pago sin API key", "POST", "/pagos/notificacion", None, 401, json={})
    check("aviso de pago con datos incompletos", "POST", "/pagos/notificacion", None, 400, headers=clave, json={"estado": "PAGADO"})
    check("aviso de pago de referencia desconocida", "POST", "/pagos/notificacion", None, 404, headers=clave,
          json={"numero_referencia": "SAL-1999-000001", "estado": "PAGADO"})
    dato("el registro guarda la referencia de Tributario (REF-TRIB-…)", bool(d.get("referenciaTributario")))
    # Confirmación de pago con el formato del documento de Tributario
    import time as _t
    clave_trib = {"X-API-Key": os.getenv("CLAVE_ENTRADA_TRIBUTARIO") or clave["X-API-Key"], "X-Modulo-Origen": "tributario"}
    evento = f"pago-aprobado-prueba-{int(_t.time() * 1000)}"
    pago = {"numero_referencia": d["numeroReferencia"], "referencia_tributario": d.get("referenciaTributario"),
            "estado": "APROBADO", "estado_pago": "PAGADO", "numero_autorizacion": "AUT-PRUEBA",
            "monto_pagado": d["monto"], "fecha_pago": "2026-10-10T11:30:00"}
    check("confirmación sin API key", "POST", "/pagos/confirmacion", None, 401, json={})
    if os.getenv("CLAVE_ENTRADA_SEGURIDAD") and os.getenv("CLAVE_ENTRADA_TRIBUTARIO"):
        check("confirmación con la clave de OTRO módulo", "POST", "/pagos/confirmacion", None, 403,
              headers={"X-API-Key": os.getenv("CLAVE_ENTRADA_SEGURIDAD")}, json={"evento_id": evento, "data": pago})
    check("confirmación con monto distinto", "POST", "/pagos/confirmacion", None, 409,
          headers={**clave_trib, "Idempotency-Key": evento + "-m"}, json={"evento_id": evento + "-m", "data": {**pago, "monto_pagado": d["monto"] + 1}})
    check("Idempotency-Key distinto de evento_id", "POST", "/pagos/confirmacion", None, 400,
          headers={**clave_trib, "Idempotency-Key": "otro"}, json={"evento_id": evento, "data": pago})
    check("Tributario confirma el pago", "POST", "/pagos/confirmacion", None, 200,
          headers={**clave_trib, "Idempotency-Key": evento}, json={"evento_id": evento, "data": pago})
    r = check("el mismo evento otra vez (idempotente)", "POST", "/pagos/confirmacion", None, 200,
              headers={**clave_trib, "Idempotency-Key": evento}, json={"evento_id": evento, "data": pago}).json()
    dato("el reenvío responde lo mismo, marcado como duplicado", r.get("duplicado") is True and r["data"]["estado"] == "PAGADO")
    citas = requests.get(API + "/citas", headers={"Authorization": f"Bearer {T['admin.salud']}"}).json()["data"]
    ok = any(c["id"] == cita_cobro and c["pago_confirmado"] and c["numero_autorizacion"] == "AUT-PRUEBA" for c in citas)
    resultados.append(ok); print(f"{'OK ' if ok else 'FALLA'}      la cita queda pagada con la autorización de Tributario")

    print("--- Demostracion: un modulo simulado consume a Salud, y bitacora")
    d = check("Seguridad (simulada) consulta establecimientos", "POST", "/integraciones/simular/seguridad-establecimientos",
              T["admin.salud"], 200).json()["data"]
    ok = d.get("origen") == "Seguridad" and d["respuesta"]["status"] == 200; resultados.append(ok)
    print(f"{'OK ' if ok else 'FALLA'}      Salud respondio {d['respuesta']['status']} a Seguridad (simulada)")
    check("ciudadano1 NO dispara la demostracion", "POST", "/integraciones/simular/seguridad-establecimientos", T["ciudadano1"], 403)
    check("caso de demostracion inexistente", "POST", "/integraciones/simular/no-existe", T["admin.salud"], 404)
    b = check("bitacora (admin)", "GET", "/integraciones/bitacora?limite=20", T["admin.salud"], 200).json()["data"]
    ok = any(r["direccion"] == "entrante" and r["modulo"] == "Seguridad" for r in b) and \
        any(r["direccion"] == "saliente" for r in b) and not any(re.search(r"\d{13}", r["ruta"]) for r in b)
    resultados.append(ok); print(f"{'OK ' if ok else 'FALLA'}      registra entrantes y salientes, CUI enmascarados")
    check("ciudadano1 NO ve la bitacora", "GET", "/integraciones/bitacora", T["ciudadano1"], 403)
    check("analista1 (auditoria) NO ve la bitacora", "GET", "/integraciones/bitacora", T["analista1"], 403)
else:
    print("         (se omiten las pruebas de datos: los simuladores no están corriendo)")

print("--- Recetas y Farmacia")
codigo = "PRB-001"      # siempre el mismo: no se acumulan medicamentos de prueba en el catálogo
r = requests.post(API + "/medicamentos", headers={"Authorization": f"Bearer {T['farmacia1']}"},
                  json={"codigo": codigo, "nombre": "Medicamento de prueba", "presentacion": "Tableta", "existencia": 20, "stock_minimo": 5})
dato("farmacia1 agrega el medicamento de prueba (o ya existía)", r.status_code in (201, 409))
m = requests.get(API + f"/medicamentos?q={codigo}", headers={"Authorization": f"Bearer {T['farmacia1']}"}).json()["data"][0]
if m["existencia"] != 20:   # deja la existencia en 20 para que la prueba sea repetible
    requests.post(API + f"/medicamentos/{m['id']}/movimientos", headers={"Authorization": f"Bearer {T['farmacia1']}"},
                  json={"tipo": "AJUSTE", "cantidad": 20 - m["existencia"], "observacion": "Inicio de la prueba"})
check("código repetido", "POST", "/medicamentos", T["farmacia1"], 409, json={"codigo": codigo, "nombre": "Otro"})
check("medico1 NO agrega medicamentos", "POST", "/medicamentos", T["medico1"], 403, json={"codigo": "X", "nombre": "X"})
check("medicamento sin nombre", "POST", "/medicamentos", T["farmacia1"], 400, json={"codigo": codigo + "B"})
r = check("medico1 receta 8 unidades a p2", "POST", "/recetas", T["medico1"], 201,
          json={"paciente_id": p2, "indicaciones": "Prueba", "items": [{"medicamento_id": m["id"], "cantidad": 8, "dosis": "1 diaria"}]})
receta = r.json()["data"]
dato("la receta queda PENDIENTE y firmada por el médico", receta["estado"] == "PENDIENTE" and bool(receta["medico"]))
check("receta sin medicamentos", "POST", "/recetas", T["medico1"], 400, json={"paciente_id": p2, "items": []})
check("receta con medicamento inexistente", "POST", "/recetas", T["medico1"], 404,
      json={"paciente_id": p2, "items": [{"medicamento_id": 999999, "cantidad": 1}]})
check("receta para paciente inexistente", "POST", "/recetas", T["medico1"], 404,
      json={"paciente_id": 999999, "items": [{"medicamento_id": m["id"], "cantidad": 1}]})
check("farmacia1 NO receta", "POST", "/recetas", T["farmacia1"], 403, json={})
check("medico1 NO despacha", "POST", f"/recetas/{receta['id']}/despachar", T["medico1"], 403)
mias = check("ciudadano2 ve SUS recetas", "GET", "/recetas", T["ciudadano2"], 200).json()["data"]
dato("la receta nueva aparece entre las del ciudadano2", any(x["id"] == receta["id"] for x in mias))
ajenas = check("ciudadano1 lista recetas", "GET", f"/recetas?paciente_id={p2}", T["ciudadano1"], 200).json()["data"]
dato("ciudadano1 no ve recetas de ciudadano2 (aunque pida su paciente_id)", not any(x["paciente_id"] == p2 for x in ajenas))
check("ciudadano1 NO despacha", "POST", f"/recetas/{receta['id']}/despachar", T["ciudadano1"], 403)
check("farmacia1 despacha", "POST", f"/recetas/{receta['id']}/despachar", T["farmacia1"], 200)
check("despachar dos veces", "POST", f"/recetas/{receta['id']}/despachar", T["farmacia1"], 409)
check("anular una receta despachada", "POST", f"/recetas/{receta['id']}/anular", T["medico1"], 409)
inv = check("inventario después del despacho", "GET", f"/medicamentos?q={codigo}", T["farmacia1"], 200).json()["data"]
dato("la existencia bajó de 20 a 12", inv and inv[0]["existencia"] == 12)
r = check("receta de 50 (más de lo que hay)", "POST", "/recetas", T["medico1"], 201,
          json={"paciente_id": p2, "items": [{"medicamento_id": m["id"], "cantidad": 50}]})
grande = r.json()["data"]["id"]
check("despachar sin existencia suficiente", "POST", f"/recetas/{grande}/despachar", T["farmacia1"], 409)
check("ajuste que deja existencia negativa", "POST", f"/medicamentos/{m['id']}/movimientos", T["farmacia1"], 400,
      json={"tipo": "AJUSTE", "cantidad": -100})
check("entrada con cantidad 0", "POST", f"/medicamentos/{m['id']}/movimientos", T["farmacia1"], 400, json={"tipo": "ENTRADA", "cantidad": 0})
check("entrada de 40", "POST", f"/medicamentos/{m['id']}/movimientos", T["farmacia1"], 201, json={"tipo": "ENTRADA", "cantidad": 40})
check("ahora sí se despacha", "POST", f"/recetas/{grande}/despachar", T["farmacia1"], 200)
kardex = check("kardex", "GET", f"/medicamentos/{m['id']}/movimientos", T["farmacia1"], 200).json()["data"]
final = requests.get(API + f"/medicamentos?q={codigo}", headers={"Authorization": f"Bearer {T['farmacia1']}"}).json()["data"][0]
dato("kardex: salida por receta, entrada y salida (existencia 2)",
     [k["tipo"] for k in kardex[:3]] == ["SALIDA", "ENTRADA", "SALIDA"] and final["existencia"] == 2)
bajo = check("bajo mínimo", "GET", "/medicamentos?bajo_minimo=1", T["farmacia1"], 200).json()["data"]
dato("el medicamento aparece bajo el mínimo (2 de 5)", any(x["id"] == m["id"] for x in bajo))
otra = check("medico1 receta otra", "POST", "/recetas", T["medico1"], 201,
             json={"paciente_id": p2, "items": [{"medicamento_id": m["id"], "cantidad": 1}]}).json()["data"]["id"]
check("ciudadano1 NO anula", "POST", f"/recetas/{otra}/anular", T["ciudadano1"], 403)
check("jefatura1 anula (no la recetó, pero es Jefatura)", "POST", f"/recetas/{otra}/anular", T["jefatura1"], 200, json={"motivo": "Prueba"})
check("anular dos veces", "POST", f"/recetas/{otra}/anular", T["medico1"], 409)
check("ajuste para dejar la existencia en 0", "POST", f"/medicamentos/{m['id']}/movimientos", T["farmacia1"], 201,
      json={"tipo": "AJUSTE", "cantidad": -2, "observacion": "Fin de la prueba"})

print("--- Hospitalización y camas")
camas = check("enfermera1 ve el censo de camas", "GET", "/camas?area=Medicina general&estado=DISPONIBLE", T["enfermera1"], 200).json()["data"]
check("ciudadano1 NO ve el censo", "GET", "/camas", T["ciudadano1"], 403)
check("cama con código repetido", "POST", "/camas", T["admin.salud"], 409, json={"codigo": camas[0]["codigo"], "area": "Medicina general"})
check("cama de un área que no existe", "POST", "/camas", T["admin.salud"], 400, json={"codigo": "X-1", "area": "Quirófano"})
check("medico1 NO agrega camas", "POST", "/camas", T["medico1"], 403, json={"codigo": "X-1", "area": "Medicina general"})
abiertas = requests.get(API + f"/hospitalizaciones?paciente_id={p2}", headers={"Authorization": f"Bearer {T['medico1']}"}).json()["data"]
for h in abiertas:          # deja a p2 sin ingresos abiertos (repetible)
    if h["estado"] == "PENDIENTE":
        requests.post(API + f"/hospitalizaciones/{h['id']}/anular", headers={"Authorization": f"Bearer {T['medico1']}"}, json={})
    if h["estado"] == "ACTIVO":
        requests.post(API + f"/hospitalizaciones/{h['id']}/egreso", headers={"Authorization": f"Bearer {T['medico1']}"}, json={"tipo_egreso": "ALTA", "resumen": "Prueba"})
check("ingreso sin diagnóstico", "POST", "/hospitalizaciones", T["medico1"], 400, json={"paciente_id": p2, "area": "Medicina general"})
check("ingreso de paciente inexistente", "POST", "/hospitalizaciones", T["medico1"], 404, json={"paciente_id": 999999, "area": "Medicina general", "diagnostico": "X"})
check("enfermera1 NO ordena ingresos", "POST", "/hospitalizaciones", T["enfermera1"], 403, json={"paciente_id": p2, "area": "Medicina general", "diagnostico": "X"})
h = check("medico1 ordena el ingreso de p2", "POST", "/hospitalizaciones", T["medico1"], 201,
          json={"paciente_id": p2, "area": "Medicina general", "diagnostico": "Neumonía", "indicaciones": "Antibiótico IV"}).json()["data"]
dato("la orden queda PENDIENTE de cama", h["estado"] == "PENDIENTE")
check("segundo ingreso abierto del mismo paciente", "POST", "/hospitalizaciones", T["medico1"], 409,
      json={"paciente_id": p2, "area": "Medicina general", "diagnostico": "X"})
uci = requests.get(API + "/camas?area=Cuidados intensivos&estado=DISPONIBLE", headers={"Authorization": f"Bearer {T['enfermera1']}"}).json()["data"]
check("cama de otra área", "POST", f"/hospitalizaciones/{h['id']}/asignar-cama", T["enfermera1"], 400, json={"cama_id": uci[0]["id"]})
check("medico1 NO asigna camas", "POST", f"/hospitalizaciones/{h['id']}/asignar-cama", T["medico1"], 403, json={"cama_id": camas[0]["id"]})
check("egreso sin cama asignada", "POST", f"/hospitalizaciones/{h['id']}/egreso", T["medico1"], 409, json={"tipo_egreso": "ALTA", "resumen": "X"})
check("enfermera1 asigna la cama", "POST", f"/hospitalizaciones/{h['id']}/asignar-cama", T["enfermera1"], 200, json={"cama_id": camas[0]["id"]})
check("la misma cama ya está ocupada", "POST", f"/hospitalizaciones/{h['id']}/asignar-cama", T["enfermera1"], 409, json={"cama_id": camas[0]["id"]})
check("cama ocupada no cambia de estado a mano", "PUT", f"/camas/{camas[0]['id']}", T["enfermera1"], 409, json={"estado": "LIMPIEZA"})
check("enfermera1 registra nota con signos", "POST", f"/hospitalizaciones/{h['id']}/notas", T["enfermera1"], 201,
      json={"nota": "Estable", "presion": "120/80", "temperatura": 37.1, "frecuencia_cardiaca": 82, "saturacion": 96})
check("saturación fuera de rango", "POST", f"/hospitalizaciones/{h['id']}/notas", T["enfermera1"], 400, json={"nota": "X", "saturacion": 120})
check("caja1 NO registra notas", "POST", f"/hospitalizaciones/{h['id']}/notas", T["caja1"], 403, json={"nota": "X"})
lista = check("recepcion1 ve hospitalizados", "GET", "/hospitalizaciones?estado=ACTIVO", T["recepcion1"], 200).json()["data"]
dato("Recepción ve la cama pero no el diagnóstico", any(x["id"] == h["id"] and x["cama"] for x in lista) and not any("diagnostico" in x for x in lista))
check("ciudadano2 ve SU hospitalización", "GET", f"/hospitalizaciones/{h['id']}", T["ciudadano2"], 200)
check("ciudadano1 ve hospitalización ajena", "GET", f"/hospitalizaciones/{h['id']}", T["ciudadano1"], 403)
propias = check("ciudadano1 lista hospitalizaciones", "GET", f"/hospitalizaciones?paciente_id={p2}", T["ciudadano1"], 200).json()["data"]
dato("ciudadano1 no ve las de ciudadano2", not any(x["paciente_id"] == p2 for x in propias))
d = check("enfermera1 traslada a cuidados intensivos", "POST", f"/hospitalizaciones/{h['id']}/asignar-cama", T["enfermera1"], 200,
          json={"cama_id": uci[0]["id"]}).json()["data"]
det = check("detalle con notas", "GET", f"/hospitalizaciones/{h['id']}", T["medico1"], 200).json()["data"]
dato("el traslado deja una nota y la cama anterior en limpieza",
     d["cama"] == uci[0]["codigo"] and any("Traslado" in n["nota"] for n in det["notas"]))
check("enfermera1 NO da egresos", "POST", f"/hospitalizaciones/{h['id']}/egreso", T["enfermera1"], 403, json={"tipo_egreso": "ALTA", "resumen": "X"})
check("tipo de egreso inválido", "POST", f"/hospitalizaciones/{h['id']}/egreso", T["medico1"], 400, json={"tipo_egreso": "FUGA", "resumen": "X"})
check("medico1 da el egreso", "POST", f"/hospitalizaciones/{h['id']}/egreso", T["medico1"], 200,
      json={"tipo_egreso": "ALTA", "resumen": "Evolución favorable"})
check("nota después del egreso", "POST", f"/hospitalizaciones/{h['id']}/notas", T["enfermera1"], 409, json={"nota": "X"})
for c in (camas[0], uci[0]):          # Enfermería deja las camas listas otra vez
    check(f"enfermera1 marca {c['codigo']} disponible", "PUT", f"/camas/{c['id']}", T["enfermera1"], 200, json={"estado": "DISPONIBLE"})
recursos = requests.get(API + "/recursos", headers={"Authorization": f"Bearer {T['admin.salud']}"}).json()["data"]
censo = [r for r in recursos if r["por_censo"]]
check("recurso de camas por censo no se edita a mano", "PUT", f"/recursos/{censo[0]['id']}", T["admin.salud"], 409, json={"disponible": 1})
otra = check("medico1 ordena otro ingreso", "POST", "/hospitalizaciones", T["medico1"], 201,
             json={"paciente_id": p2, "area": "Pediatría", "diagnostico": "X"}).json()["data"]["id"]
check("medico1 anula la orden sin cama", "POST", f"/hospitalizaciones/{otra}/anular", T["medico1"], 200, json={"motivo": "Prueba"})
ind = check("indicadores con hospitalización", "GET", "/indicadores", None, 200,
            headers={"X-API-Key": os.getenv("MODULOS_API_KEY", "clave-temporal-cambiar")}).json()["data"]
dato("indicadores: camas y ocupación, sin datos personales",
     {"camas_total", "camas_disponibles", "ocupacion_porcentaje", "hospitalizados"} <= set(ind["hospitalizacion"]) and "farmacia" in ind)

print("--- Caja y cuentas")
H = lambda u: {"Authorization": f"Bearer {T[u]}"}
for h in requests.get(API + f"/hospitalizaciones?paciente_id={p2}", headers=H("medico1")).json()["data"]:
    if h["estado"] == "PENDIENTE":
        requests.post(API + f"/hospitalizaciones/{h['id']}/anular", headers=H("medico1"), json={})
    if h["estado"] == "ACTIVO":
        requests.post(API + f"/hospitalizaciones/{h['id']}/egreso", headers=H("medico1"), json={"tipo_egreso": "ALTA", "resumen": "Prueba"})
for c in requests.get(API + f"/cuentas?paciente_id={p2}&estado=ABIERTA", headers=H("caja1")).json()["data"]:
    if c["tipo"] == "AMBULATORIA":          # repetible: cierra la ambulatoria que haya quedado abierta
        requests.post(API + f"/cuentas/{c['id']}/cerrar", headers=H("caja1"))
servicios = check("caja1 ve el catálogo de servicios", "GET", "/servicios", T["caja1"], 200).json()["data"]
check("medico1 NO ve el catálogo de Caja", "GET", "/servicios", T["medico1"], 403)
lab = next(x for x in servicios if x["categoria"] == "LABORATORIO")
dia_cama = next(x for x in servicios if x["categoria"] == "DIA_CAMA")
h = requests.post(API + "/hospitalizaciones", headers=H("medico1"), json={"paciente_id": p2, "area": "Medicina general", "diagnostico": "Prueba de caja"}).json()["data"]
cama = requests.get(API + "/camas?area=Medicina general&estado=DISPONIBLE", headers=H("enfermera1")).json()["data"][0]
requests.post(API + f"/hospitalizaciones/{h['id']}/asignar-cama", headers=H("enfermera1"), json={"cama_id": cama["id"]})
cuentas_p2 = check("al ingresar a cama se abre la cuenta", "GET", f"/cuentas?paciente_id={p2}&estado=ABIERTA", T["caja1"], 200).json()["data"]
cuenta = next((c for c in cuentas_p2 if c["hospitalizacion_id"] == h["id"]), None)
dato("cuenta de hospitalización ABIERTA con día cama en curso", cuenta is not None and cuenta["estancia_en_curso"] is not None)
check("no se cierra con el paciente ingresado", "POST", f"/cuentas/{cuenta['id']}/cerrar", T["caja1"], 409)
check("caja1 carga un laboratorio", "POST", f"/cuentas/{cuenta['id']}/cargos", T["caja1"], 201, json={"servicio_id": lab["id"], "cantidad": 2})
check("el día cama no se carga a mano", "POST", f"/cuentas/{cuenta['id']}/cargos", T["caja1"], 400, json={"servicio_id": dia_cama["id"]})
check("recepcion1 NO carga", "POST", f"/cuentas/{cuenta['id']}/cargos", T["recepcion1"], 403, json={"servicio_id": lab["id"]})
check("admin.salud NO carga (solo lectura)", "POST", f"/cuentas/{cuenta['id']}/cargos", T["admin.salud"], 403, json={"servicio_id": lab["id"]})
check("recepcion1 ve la cuenta", "GET", f"/cuentas/{cuenta['id']}", T["recepcion1"], 200)
med = requests.get(API + "/medicamentos", headers=H("farmacia1")).json()["data"]
med = next(m for m in med if m["existencia"] > 10 and m["precio"])
receta = requests.post(API + "/recetas", headers=H("medico1"), json={"paciente_id": p2, "items": [{"medicamento_id": med["id"], "cantidad": 2}]}).json()["data"]
check("farmacia1 despacha la receta del paciente ingresado", "POST", f"/recetas/{receta['id']}/despachar", T["farmacia1"], 200)
det = requests.get(API + f"/cuentas/{cuenta['id']}", headers=H("caja1")).json()["data"]
dato("el medicamento despachado se cargó a la cuenta", any(m["categoria"] == "MEDICAMENTO" and f"receta No. {receta['id']}" in m["descripcion"] for m in det["movimientos"]))
mov = next(m for m in det["movimientos"] if m["categoria"] == "LABORATORIO")
check("anular sin motivo", "POST", f"/cuentas/{cuenta['id']}/movimientos/{mov['id']}/anular", T["caja1"], 400, json={})
check("caja1 anula un cargo con motivo", "POST", f"/cuentas/{cuenta['id']}/movimientos/{mov['id']}/anular", T["caja1"], 200, json={"motivo": "Prueba"})
check("descuento mayor al saldo", "POST", f"/cuentas/{cuenta['id']}/descuentos", T["caja1"], 400, json={"monto": 999999, "motivo": "X"})
requests.post(API + f"/hospitalizaciones/{h['id']}/egreso", headers=H("medico1"), json={"tipo_egreso": "ALTA", "resumen": "Prueba"})
requests.put(API + f"/camas/{cama['id']}", headers=H("enfermera1"), json={"estado": "DISPONIBLE"})
det = requests.get(API + f"/cuentas/{cuenta['id']}", headers=H("caja1")).json()["data"]
dato("al egreso se cargó al menos un día cama", any(m["categoria"] == "DIA_CAMA" and m["cantidad"] >= 1 for m in det["movimientos"]))
cerrada = check("caja1 cierra y envía el cobro a Tributario", "POST", f"/cuentas/{cuenta['id']}/cerrar", T["caja1"], 200).json()["data"]
dato("queda POR_COBRAR con referencia SAL-AAAA-NNNNNN", cerrada["estado"] == "POR_COBRAR" and bool(re.match(r"^SAL-\d{4}-\d{6}$", cerrada["numero_referencia"] or "")))
check("ya no se le pueden cargar servicios", "POST", f"/cuentas/{cuenta['id']}/cargos", T["caja1"], 409, json={"servicio_id": lab["id"]})
mias = check("ciudadano2 ve SUS cuentas", "GET", "/cuentas", T["ciudadano2"], 200).json()["data"]
dato("ciudadano2 ve la referencia de pago", any(c["numero_referencia"] == cerrada["numero_referencia"] for c in mias))
check("ciudadano1 ve cuenta ajena", "GET", f"/cuentas/{cuenta['id']}", T["ciudadano1"], 403)
clave = {"X-API-Key": os.getenv("MODULOS_API_KEY", "clave-temporal-cambiar")}
check("Tributario avisa el pago de la cuenta", "POST", "/pagos/notificacion", None, 200, headers=clave,
      json={"numero_referencia": cerrada["numero_referencia"], "estado": "PAGADO", "numero_autorizacion": "AUT-CUENTA"})
pagada = requests.get(API + f"/cuentas/{cuenta['id']}", headers=H("caja1")).json()["data"]
dato("la cuenta queda PAGADA, saldo 0 y con autorización", pagada["estado"] == "PAGADA" and pagada["saldo"] == 0 and pagada["numero_autorizacion"] == "AUT-CUENTA")
amb = check("caja1 abre una cuenta ambulatoria", "POST", "/cuentas", T["caja1"], 201, json={"paciente_id": p2}).json()["data"]
check("segunda ambulatoria abierta", "POST", "/cuentas", T["caja1"], 409, json={"paciente_id": p2})
check("cerrar sin cargos", "POST", f"/cuentas/{amb['id']}/cerrar", T["caja1"], 400)
r = check("cargo ambulatorio (2 unidades)", "POST", f"/cuentas/{amb['id']}/cargos", T["caja1"], 201, json={"servicio_id": lab["id"], "cantidad": 2}).json()["data"]
dato("saldo = 2 × tarifa", r["saldo"] == round(2 * lab["costo"], 2))
r = check("descuento parcial", "POST", f"/cuentas/{amb['id']}/descuentos", T["caja1"], 201, json={"monto": lab["costo"], "motivo": "Parcial"}).json()["data"]
dato("saldo = 2 × tarifa − descuento", r["saldo"] == round(lab["costo"], 2) and r["cargos"] == round(2 * lab["costo"], 2))
check("exoneración total", "POST", f"/cuentas/{amb['id']}/descuentos", T["caja1"], 201, json={"monto": lab["costo"], "motivo": "Estudio socioeconómico"})
ex = check("cerrar con saldo 0", "POST", f"/cuentas/{amb['id']}/cerrar", T["caja1"], 200).json()["data"]
dato("queda EXONERADA sin enviar cobro", ex["estado"] == "EXONERADA" and not ex["numero_referencia"])
check("verificar pago sin cobro", "POST", f"/cuentas/{amb['id']}/verificar-pago", T["caja1"], 409)
check("admin.salud cambia una tarifa", "PUT", f"/servicios/{lab['id']}", T["admin.salud"], 200, json={"costo": lab["costo"]})
check("caja1 NO cambia tarifas", "PUT", f"/servicios/{lab['id']}", T["caja1"], 403, json={"costo": 1})

print("--- API key (entre modulos) sigue igual")
check("indicadores sin api key", "GET", "/indicadores", None, 401)
check("indicadores con api key", "GET", "/indicadores", None, 200, headers={"X-API-Key": os.getenv("MODULOS_API_KEY", "clave-temporal-cambiar")})
check("WS-SALUD-02 con tipoAtencion inválido", "GET", "/establecimientos/disponibilidad?tipoAtencion=CARDIOLOGIA", None, 400,
      headers={"X-API-Key": os.getenv("MODULOS_API_KEY", "clave-temporal-cambiar")})
if os.getenv("CLAVE_ENTRADA_SEGURIDAD"):     # clave propia de Seguridad (la misma que tiene el backend)
    r = check("WS-SALUD-02 con la clave de Seguridad", "GET", "/establecimientos/disponibilidad?departamento=SACATEPEQUEZ&tipoAtencion=emergencia",
              None, 200, headers={"X-API-Key": os.getenv("CLAVE_ENTRADA_SEGURIDAD")})
    dato("acepta mayúsculas sin tilde y encuentra establecimientos", r.json().get("disponible") is True)

print(f"\n{sum(resultados)}/{len(resultados)} pruebas OK")
sys.exit(0 if all(resultados) else 1)
