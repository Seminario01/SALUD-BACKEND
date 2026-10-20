"""
Pruebas de autenticación y autorización del Módulo de Salud contra el Login Único.

Requiere: el Login Único (keycloak-local o URL del día) y el backend corriendo.
Uso (desde la carpeta SALUD-BACKEND):
    venv/Scripts/python.exe pruebas/prueba_auth.py        (Windows)
    python pruebas/prueba_auth.py                         (Linux)

Variables opcionales: AUTH_ISSUER (por defecto la réplica local) y MODULOS_API_KEY.
Es repetible: si los pacientes de prueba ya existen, los reutiliza.
"""
import json, os, sys, base64, random, tempfile, requests
import re
from datetime import date, datetime, timedelta


# Cada corrida agenda sus citas corridas un número de días al azar (el backend guarda la hora
# sin segundos, así que dos corridas al mismo minuto de distintos días podían chocar).
DESFASE = random.randint(0, 300)


def futuro(dias, hora):
    """Fecha de cita a unos `dias` días (más el desfase de esta corrida), a la `hora` y con el
    minuto actual: las citas no pueden ir en el pasado ni repetirse. A partir de 366 días
    (para probar el límite de un año) no se agrega el desfase."""
    ahora = datetime.now()
    momento = ahora + timedelta(days=dias + (DESFASE if dias < 366 else 0))
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
    resultados.append(bool(ok))
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
print("--- Detalle de una cita: GET /citas/{id}")
r = check("recepcion1 ve el detalle de la cita de p2", "GET", f"/citas/{c2}", T["recepcion1"], 200).json()["data"]
dato("trae paciente, DPI, quién la agendó y datos del pago",
     r["paciente_id"] == p2 and "paciente_cui" in r and "Recepción" in (r["agendada_por"] or "")
     and {"estado_cobro", "numero_referencia", "fecha_pago", "historial"} <= set(r))
dato("recepción NO recibe la atención clínica (no ve expedientes)", "atenciones" not in r)
check("ciudadano2 ve SU cita", "GET", f"/citas/{c2}", T["ciudadano2"], 200)
r = requests.get(API + f"/citas/{c2}", headers={"Authorization": f"Bearer {T['ciudadano2']}"}).json()["data"]
dato("el ciudadano no recibe el historial interno", "historial" not in r)
check("ciudadano1 NO ve la cita de otro (404, no revela)", "GET", f"/citas/{c2}", T["ciudadano1"], 404)
check("cita que no existe", "GET", "/citas/999999", T["medico1"], 404)
check("detalle de cita sin token", "GET", f"/citas/{c2}", None, 401)
check("medico1 registra la atención de la cita de p1", "POST", f"/expedientes/{p1}/atenciones", T["medico1"], 201,
      json={"diagnostico": "Control", "cita_id": cita_p1})
r = check("medico1 ve el detalle con la atención", "GET", f"/citas/{cita_p1}", T["medico1"], 200).json()["data"]
dato("la cita queda a nombre del médico que la atendió y muestra el diagnóstico",
     bool(r["medico_nombre"]) and any(a["diagnostico"] == "Control" for a in r["atenciones"]))
dato("el historial muestra quién agendó la cita",
     any(h["descripcion"] == f"Agendó la cita No. {cita_p1}" and h["puesto"] == "Recepción" for h in r["historial"]))
print("--- Médicos para asignar a una cita: GET /medicos")
SUB_MED = sub(T["medico1"])
r = check("recepcion1 lista los médicos", "GET", "/medicos", T["recepcion1"], 200).json()["data"]
dato("medico1 aparece en la lista (se anotó solo al usar el módulo)", any(m["sub"] == SUB_MED and m["nombre"] for m in r))
dato("la lista no incluye a quien no es médico", sub(T["recepcion1"]) not in {m["sub"] for m in r})
check("ciudadano1 NO lista médicos", "GET", "/medicos", T["ciudadano1"], 403)
cm = check("recepcion1 agenda con médico", "POST", "/citas", T["recepcion1"], 201,
           json={"paciente_id": p2, "fecha_hora": futuro(19, 8), "medico_sub": SUB_MED}).json()["data"]["id"]
r = requests.get(API + f"/citas/{cm}", headers={"Authorization": f"Bearer {T['recepcion1']}"}).json()["data"]
dato("la cita queda con el nombre del médico elegido", r["medico_sub"] == SUB_MED and bool(r["medico_nombre"]))
check("agendar con un médico que no existe", "POST", "/citas", T["recepcion1"], 400,
      json={"paciente_id": p2, "fecha_hora": futuro(19, 9), "medico_sub": "00000000-0000-0000-0000-000000000000"})
check("quitar el médico de la cita", "PUT", f"/citas/{cm}", T["recepcion1"], 200, json={"medico_sub": None})
r = requests.get(API + f"/citas/{cm}", headers={"Authorization": f"Bearer {T['recepcion1']}"}).json()["data"]
dato("la cita queda sin médico", r["medico_sub"] is None and r["medico_nombre"] is None)
check("volver a asignar el médico", "PUT", f"/citas/{cm}", T["recepcion1"], 200, json={"medico_sub": SUB_MED})
check("ciudadano2 NO cambia el médico de su cita", "PUT", f"/citas/{cm}", T["ciudadano2"], 403, json={"medico_sub": None})
check("asignar un médico que no existe", "PUT", f"/citas/{cm}", T["recepcion1"], 400, json={"medico_sub": "x" * 36})
check("recepcion1 cancela la cita de prueba", "DELETE", f"/citas/{cm}", T["recepcion1"], 200)
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

print("--- Bitácora de accesos: quién vio o modificó cada expediente (solo Administración)")
BIT = "/bitacora/accesos"
check("bitácora sin token", "GET", BIT, None, 401)
check("recepcion1 NO ve la bitácora", "GET", BIT, T["recepcion1"], 403)
check("medico1 NO ve la bitácora", "GET", BIT, T["medico1"], 403)
check("ciudadano1 NO ve la bitácora", "GET", BIT, T["ciudadano1"], 403)
requests.get(API + f"/expedientes/{p2}", headers={"Authorization": f"Bearer {T['medico1']}"})
r = check("admin.salud ve la bitácora del paciente", "GET", f"{BIT}?paciente_id={p2}", T["admin.salud"], 200).json()
dato("queda que medico1 vio el expediente clínico",
     any(x["usuario"] == "medico1" and x["accion"] == "ver" and x["descripcion"] == "Vio el expediente clínico"
         and x["paciente_id"] == p2 and x["puesto"] == "Médico" for x in r["data"]))
r = check("bitácora filtrada por acción", "GET", f"{BIT}?accion=ver&limite=5", T["admin.salud"], 200).json()
dato("el filtro por acción devuelve solo 'ver' y máximo 5", len(r["data"]) <= 5 and all(x["accion"] == "ver" for x in r["data"]))
requests.get(API + "/pacientes/999999", headers={"Authorization": f"Bearer {T['medico1']}"})
r = requests.get(API + f"{BIT}?paciente_id=999999", headers={"Authorization": f"Bearer {T['admin.salud']}"}).json()
dato("un 404 no queda como acceso", r["total"] == 0)
check("bitácora con fecha inválida", "GET", f"{BIT}?desde=2026-13-01", T["admin.salud"], 400)
check("bitácora con acción inválida", "GET", f"{BIT}?accion=borrar", T["admin.salud"], 400)
check("bitácora con paciente_id no numérico", "GET", f"{BIT}?paciente_id=1%20OR%201=1", T["admin.salud"], 400)

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

print("--- Lotes y vencimientos de medicamentos")
HF = {"Authorization": f"Bearer {T['farmacia1']}"}
CL = "PRB-LOTE"
requests.post(API + "/medicamentos", headers=HF, json={"codigo": CL, "nombre": "Medicamento con lotes", "presentacion": "Tableta"})
ml = requests.get(API + f"/medicamentos?q={CL}", headers=HF).json()["data"][0]
for l in requests.get(API + f"/medicamentos/{ml['id']}/lotes", headers=HF).json()["data"]:      # repetible: vacía los lotes
    requests.post(API + f"/medicamentos/{ml['id']}/lotes/{l['id']}/baja", headers=HF, json={"motivo": "Inicio de la prueba"})
ml = requests.get(API + f"/medicamentos?q={CL}", headers=HF).json()["data"][0]
if ml["existencia"]:
    requests.post(API + f"/medicamentos/{ml['id']}/movimientos", headers=HF, json={"tipo": "AJUSTE", "cantidad": -ml["existencia"]})
MOV = f"/medicamentos/{ml['id']}/movimientos"
pronto = (datetime.now() + timedelta(days=20)).strftime("%Y-%m-%d")
tarde = (datetime.now() + timedelta(days=400)).strftime("%Y-%m-%d")
check("entrada con lote que vence en 400 días", "POST", MOV, T["farmacia1"], 201,
      json={"tipo": "ENTRADA", "cantidad": 10, "numero_lote": "TARDE", "fecha_vencimiento": tarde})
r = check("entrada con lote que vence en 20 días", "POST", MOV, T["farmacia1"], 201,
          json={"tipo": "ENTRADA", "cantidad": 5, "numero_lote": "PRONTO", "fecha_vencimiento": pronto}).json()["data"]
dato("existencia 15, 5 por vencer, próximo vencimiento el del lote PRONTO",
     r["existencia"] == 15 and r["por_vencer"] == 5 and r["vencidas"] == 0 and r["proximo_vencimiento"] == pronto)
check("entrada sin lote (como antes)", "POST", MOV, T["farmacia1"], 201, json={"tipo": "ENTRADA", "cantidad": 3})
check("lote ya vencido", "POST", MOV, T["farmacia1"], 400,
      json={"tipo": "ENTRADA", "cantidad": 1, "fecha_vencimiento": "2020-01-01"})
check("fecha de vencimiento con otro formato", "POST", MOV, T["farmacia1"], 400,
      json={"tipo": "ENTRADA", "cantidad": 1, "fecha_vencimiento": "31/12/2027"})
check("número de lote sin fecha de vencimiento", "POST", MOV, T["farmacia1"], 400,
      json={"tipo": "ENTRADA", "cantidad": 1, "numero_lote": "X"})
pv = check("lista de por vencer", "GET", "/medicamentos?por_vencer=1", T["farmacia1"], 200).json()["data"]
dato("el medicamento aparece en por vencer", any(x["id"] == ml["id"] for x in pv))
rl = check("medico1 receta 7 del medicamento con lotes", "POST", "/recetas", T["medico1"], 201,
           json={"paciente_id": p2, "items": [{"medicamento_id": ml["id"], "cantidad": 7}]}).json()["data"]["id"]
check("farmacia1 despacha la receta", "POST", f"/recetas/{rl}/despachar", T["farmacia1"], 200)
lt = {l["numero_lote"]: l["cantidad"] for l in requests.get(API + f"/medicamentos/{ml['id']}/lotes", headers=HF).json()["data"]}
dato("se despachó primero el lote que vence antes (PRONTO 5 -> 0, TARDE 10 -> 8)", lt.get("PRONTO") is None and lt.get("TARDE") == 8)
kx = requests.get(API + MOV, headers=HF).json()["data"]
dato("el kardex dice de qué lotes salió", any(x["receta_id"] == rl and "PRONTO" in (x["observacion"] or "") and "TARDE" in x["observacion"] for x in kx))
check("medico1 ve los lotes (inventario.ver)", "GET", f"/medicamentos/{ml['id']}/lotes", T["medico1"], 200)
check("recepcion1 NO ve lotes", "GET", f"/medicamentos/{ml['id']}/lotes", T["recepcion1"], 403)
tarde_id = next(l["id"] for l in requests.get(API + f"/medicamentos/{ml['id']}/lotes", headers=HF).json()["data"] if l["numero_lote"] == "TARDE")
check("medico1 NO da de baja un lote", "POST", f"/medicamentos/{ml['id']}/lotes/{tarde_id}/baja", T["medico1"], 403, json={})
r = check("farmacia1 da de baja el lote TARDE", "POST", f"/medicamentos/{ml['id']}/lotes/{tarde_id}/baja", T["farmacia1"], 201,
          json={"motivo": "Dañado"}).json()["data"]
dato("queda solo lo sin lote (11 - 8 = 3)", r["existencia"] == 3 and r["sin_lote"] == 3)
check("dar de baja otra vez el mismo lote", "POST", f"/medicamentos/{ml['id']}/lotes/{tarde_id}/baja", T["farmacia1"], 409, json={})
check("lote de otro medicamento", "POST", f"/medicamentos/{m['id']}/lotes/{tarde_id}/baja", T["farmacia1"], 404, json={})

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
check("medico1 registra nota con peso", "POST", f"/hospitalizaciones/{h['id']}/notas", T["medico1"], 201,
      json={"nota": "Evolución favorable", "presion": "118/76", "peso": 64.3})
check("peso fuera de rango", "POST", f"/hospitalizaciones/{h['id']}/notas", T["enfermera1"], 400, json={"nota": "X", "peso": 900})
check("peso que no es número", "POST", f"/hospitalizaciones/{h['id']}/notas", T["enfermera1"], 400, json={"nota": "X", "peso": "mucho"})
check("nota sin signos (solo texto)", "POST", f"/hospitalizaciones/{h['id']}/notas", T["enfermera1"], 201, json={"nota": "Duerme tranquilo"})
sv = check("medico1 ve el historial de signos de p2", "GET", f"/pacientes/{p2}/signos", T["medico1"], 200).json()["data"]
ultimos = [x for x in sv if x["hospitalizacion_id"] == h["id"]]
dato("trae las 2 mediciones (la nota sin signos no cuenta), en orden",
     len(ultimos) == 2 and ultimos[0]["temperatura"] == 37.1 and ultimos[1]["peso"] == 64.3)
dato("la presión viene separada en sistólica y diastólica", ultimos[1]["sistolica"] == 118 and ultimos[1]["diastolica"] == 76)
check("ciudadano2 ve SUS signos", "GET", f"/pacientes/{p2}/signos", T["ciudadano2"], 200)
check("ciudadano1 NO ve signos de otro", "GET", f"/pacientes/{p2}/signos", T["ciudadano1"], 403)
check("recepcion1 NO ve signos (dato clínico)", "GET", f"/pacientes/{p2}/signos", T["recepcion1"], 403)
check("caja1 NO ve signos (dato clínico)", "GET", f"/pacientes/{p2}/signos", T["caja1"], 403)
check("signos de paciente que no existe", "GET", "/pacientes/999999/signos", T["medico1"], 404)
r = check("nota con fiebre y saturación baja", "POST", f"/hospitalizaciones/{h['id']}/notas", T["enfermera1"], 201,
          json={"nota": "Febril", "temperatura": 39.2, "saturacion": 91, "frecuencia_cardiaca": 80}).json()
dato("avisa lo que está fuera de rango (y no el pulso normal)",
     [x["signo"] for x in r["data"]["alertas"]] == ["temperatura", "saturacion"] and "Fiebre (39.2 °C)" in r["message"])
notas_h = check("las notas traen sus alertas", "GET", f"/hospitalizaciones/{h['id']}", T["medico1"], 200).json()["data"]["notas"]
dato("la nota con fiebre trae la alerta; la nota normal, ninguna",
     any(n["alertas"] and n["nota"] == "Febril" for n in notas_h) and all(not n["alertas"] for n in notas_h if n["nota"] == "Duerme tranquilo"))
sv = check("el historial de signos trae las alertas", "GET", f"/pacientes/{p2}/signos", T["medico1"], 200).json()["data"]
dato("la última medición trae la fiebre", any(x["signo"] == "temperatura" and x["nivel"] == "alto" for x in sv[-1]["alertas"]))
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
bit = requests.get(API + f"/bitacora/accesos?paciente_id={p2}&usuario=caja1&limite=1000", headers=H("admin.salud")).json()["data"]
dato("la bitácora anota los cambios de caja1 en la cuenta (abrir, cargo, descuento, cerrar)",
     {f"Abrió la cuenta No. {amb['id']}", f"Agregó un cargo a la cuenta No. {amb['id']}",
      f"Aplicó un descuento a la cuenta No. {amb['id']}", f"Cerró la cuenta No. {amb['id']}"}
     <= {x["descripcion"] for x in bit})
dato("los intentos rechazados (409, 400) no quedan en la bitácora", all(x["metodo"] != "GET" or x["accion"] == "ver" for x in bit)
     and sum(1 for x in bit if x["descripcion"] == f"Cerró la cuenta No. {amb['id']}") == 1)

print("--- Alergias al recetar")
check("caja1 NO registra alergias", "PUT", f"/pacientes/{p1}/alergias", T["caja1"], 403, json={"alergias": "X"})
check("farmacia1 NO registra alergias", "PUT", f"/pacientes/{p1}/alergias", T["farmacia1"], 403, json={"alergias": "X"})
check("ciudadano1 NO cambia sus alergias (dato clínico)", "PUT", f"/pacientes/{p1}/alergias", T["ciudadano1"], 403, json={"alergias": ""})
check("alergias de paciente que no existe", "PUT", "/pacientes/999999/alergias", T["medico1"], 404, json={"alergias": "X"})
check("alergias que no son texto", "PUT", f"/pacientes/{p1}/alergias", T["medico1"], 400, json={"alergias": 5})
check("alergias demasiado largas", "PUT", f"/pacientes/{p1}/alergias", T["medico1"], 400, json={"alergias": "x" * 501})
check("recepcion1 registra la alergia de p1", "PUT", f"/pacientes/{p1}/alergias", T["recepcion1"], 200, json={"alergias": "Penicilina, látex"})
dato("la ficha de p1 muestra la alergia",
     requests.get(API + f"/pacientes/{p1}", headers=H("medico1")).json()["data"]["alergias"] == "Penicilina, látex")
requests.post(API + "/medicamentos", headers=H("farmacia1"),
              json={"codigo": "PRB-AMOX", "nombre": "Amoxicilina", "presentacion": "Cápsula 500 mg (prueba)", "existencia": 0})
amox = requests.get(API + "/medicamentos?q=PRB-AMOX", headers=H("farmacia1")).json()["data"][0]
item_amox = [{"medicamento_id": amox["id"], "cantidad": 1}]
r = check("recetar amoxicilina a un alérgico a penicilina: avisa", "POST", "/recetas", T["medico1"], 409,
          json={"paciente_id": p1, "items": item_amox}).json()
dato("dice qué medicamento choca con qué alergia", r["error"] == "alergia" and r["alergias"][0]["medicamento_id"] == amox["id"]
     and r["alergias"][0]["alergias"] == ["penicilina"] and "Amoxicilina" in r["message"])
check("confirmar_alergia que no es true/false", "POST", "/recetas", T["medico1"], 400,
      json={"paciente_id": p1, "items": item_amox, "confirmar_alergia": "si"})
ra = check("el médico confirma y receta igual", "POST", "/recetas", T["medico1"], 201,
           json={"paciente_id": p1, "items": item_amox, "confirmar_alergia": True}).json()["data"]
dato("la receta queda marcada con la alergia (Farmacia la ve)", "penicilina" in (ra["alerta_alergia"] or ""))
check("se anula la receta de prueba", "POST", f"/recetas/{ra['id']}/anular", T["medico1"], 200, json={"motivo": "Prueba de alergia"})
rn = check("un medicamento sin conflicto se receta sin aviso", "POST", "/recetas", T["medico1"], 201,
           json={"paciente_id": p1, "items": [{"medicamento_id": m["id"], "cantidad": 1}]}).json()["data"]
dato("y no queda marcado", rn["alerta_alergia"] is None)
check("se anula esa receta también", "POST", f"/recetas/{rn['id']}/anular", T["medico1"], 200, json={"motivo": "Prueba"})
check("enfermera1 quita las alergias (texto vacío)", "PUT", f"/pacientes/{p1}/alergias", T["enfermera1"], 200, json={"alergias": ""})
check("sin alergias, la amoxicilina ya no avisa", "POST", "/recetas", T["medico1"], 201,
      json={"paciente_id": p1, "items": item_amox, "indicaciones": "Prueba"})
bit = requests.get(API + f"/bitacora/accesos?paciente_id={p1}&usuario=recepcion1&limite=50", headers=H("admin.salud")).json()["data"]
dato("la bitácora anota quién cambió las alergias", any(x["descripcion"] == "Actualizó las alergias del paciente" for x in bit))
ultima = requests.get(API + f"/recetas?paciente_id={p1}", headers=H("medico1")).json()["data"]
for x in ultima:   # deja anuladas las recetas pendientes de amoxicilina de prueba
    if x["estado"] == "PENDIENTE" and any(i["medicamento_id"] == amox["id"] for i in x["items"]):
        requests.post(API + f"/recetas/{x['id']}/anular", headers=H("medico1"), json={"motivo": "Prueba"})

print("--- Interacciones entre medicamentos al recetar")
for codigo, nombre in (("PRB-WARF", "Warfarina"), ("PRB-IBUP", "Ibuprofeno")):
    requests.post(API + "/medicamentos", headers=H("farmacia1"),
                  json={"codigo": codigo, "nombre": nombre, "presentacion": "Tableta (prueba)", "existencia": 0})
warf = requests.get(API + "/medicamentos?q=PRB-WARF", headers=H("farmacia1")).json()["data"][0]
ibup = requests.get(API + "/medicamentos?q=PRB-IBUP", headers=H("farmacia1")).json()["data"][0]
ambos = [{"medicamento_id": warf["id"], "cantidad": 1}, {"medicamento_id": ibup["id"], "cantidad": 1}]
r = check("warfarina + ibuprofeno en la misma receta: avisa", "POST", "/recetas", T["medico1"], 409,
          json={"paciente_id": p1, "items": ambos}).json()
grave = [a for a in r.get("interacciones", []) if {a["medicamento"], a["con"]} == {"Warfarina", "Ibuprofeno"}]
dato("dice qué medicamentos, que es grave y por qué", r.get("error") == "interaccion" and grave
     and grave[0]["severidad"] == "grave" and "sangrado" in grave[0]["texto"] and grave[0]["origen"] == "esta receta")
check("confirmar_interaccion que no es true/false", "POST", "/recetas", T["medico1"], 400,
      json={"paciente_id": p1, "items": ambos, "confirmar_interaccion": "si"})
rw = check("el médico confirma y receta igual", "POST", "/recetas", T["medico1"], 201,
           json={"paciente_id": p1, "items": ambos, "confirmar_interaccion": True}).json()["data"]
dato("la receta queda marcada con la interacción (Farmacia la ve)", "Warfarina" in (rw["alerta_interaccion"] or "")
     and any(x["id"] == rw["id"] and x["alerta_interaccion"] for x in
             requests.get(API + "/recetas?estado=PENDIENTE", headers=H("farmacia1")).json()["data"]))
r = check("después, ibuprofeno solo: avisa por la warfarina de la receta activa", "POST", "/recetas", T["medico1"], 409,
          json={"paciente_id": p1, "items": [ambos[1]]}).json()
dato("dice de qué receta viene", any(a["con"] == "Warfarina" and a["origen"].startswith(f"receta #{rw['id']} ")
                                     for a in r.get("interacciones", [])))
check("se anula la receta de prueba", "POST", f"/recetas/{rw['id']}/anular", T["medico1"], 200, json={"motivo": "Prueba de interacción"})
r = requests.post(API + "/recetas", headers=H("medico1"), json={"paciente_id": p1, "items": [ambos[1]]})
dato("una receta anulada ya no cuenta", r.status_code == 201
     or not any(a["con"] == "Warfarina" for a in r.json().get("interacciones", [])))
if r.status_code == 201:
    requests.post(API + f"/recetas/{r.json()['data']['id']}/anular", headers=H("medico1"), json={"motivo": "Prueba"})

print("--- Receta verificable con QR (pública, sin token)")
cod = ra["codigo_verificacion"] or ""
dato("cada receta trae su código del QR (12 caracteres)", len(cod) == 12 and cod != rn["codigo_verificacion"])
v = check("una farmacia verifica la receta sin token", "GET", f"/verificar/receta/{cod}", None, 200).json()["data"]
dato("dice número, médico, medicamentos y que está ANULADA", v["numero"] == ra["id"] and v["estado"] == "ANULADA"
     and v["medico"] and v["medicamentos"][0]["medicamento"] == "Amoxicilina")
crudo = requests.get(API + f"/verificar/receta/{cod}").text
dato("del paciente solo iniciales y DPI tapado (nada de nombre, teléfono ni alergias)",
     v["paciente_iniciales"] == "C. P." and "Perez" not in crudo and "alergia" not in crudo.lower()
     and "telefono" not in crudo and "paciente_id" not in crudo and (v["paciente_dpi"] or "").startswith("•••• "))
alterado = cod[:-1] + ("A" if cod[-1] != "A" else "B")
check("código alterado: no existe", "GET", f"/verificar/receta/{alterado}", None, 404)
check("código con caracteres raros", "GET", "/verificar/receta/abc'%20OR%201=1", None, 404)
check("el número de receta NO sirve como código", "GET", f"/verificar/receta/{ra['id']}", None, 404)
desp = next(x for x in requests.get(API + "/recetas?estado=DESPACHADA", headers=H("medico1")).json()["data"])
v = check("la receta ya despachada", "GET", f"/verificar/receta/{desp['codigo_verificacion']}", None, 200).json()["data"]
dato("avisa que ya se despachó y cuándo", v["estado"] == "DESPACHADA" and bool(v["fecha_despacho"]))

print("--- Paciente posiblemente duplicado")
check("medico1 NO consulta duplicados (solo quien registra)", "GET", "/pacientes/posibles-duplicados?nombre_completo=Maria", T["medico1"], 403)
check("sin nombre", "GET", "/pacientes/posibles-duplicados", T["recepcion1"], 400)
check("nombre muy corto", "GET", "/pacientes/posibles-duplicados?nombre_completo=ab", T["recepcion1"], 400)
check("fecha con otro formato", "GET", "/pacientes/posibles-duplicados?nombre_completo=Maria&fecha_nacimiento=18/10/2000", T["recepcion1"], 400)
d = check("mismo nombre sin tilde ni mayúsculas", "GET", "/pacientes/posibles-duplicados?nombre_completo=MARÍA garcía",
          T["recepcion1"], 200).json()["data"]
dato("encuentra a p2 como 'Mismo nombre'", any(x["id"] == p2 and x["motivo"].startswith("Mismo nombre") for x in d))
con_cui = next((x for x in requests.get(API + "/pacientes", headers=H("recepcion1")).json()["data"]
                if x["cui"] and len(x["cui"]) == 13), None)
if con_cui:
    d = check("por CUI", "GET", f"/pacientes/posibles-duplicados?nombre_completo=Otro%20Nombre&cui={con_cui['cui']}",
              T["recepcion1"], 200).json()["data"]
    dato("encuentra al paciente por 'Mismo CUI' (primero)", bool(d) and d[0]["id"] == con_cui["id"] and d[0]["motivo"] == "Mismo CUI")
d = check("un nombre que no existe", "GET", "/pacientes/posibles-duplicados?nombre_completo=Zuxtyq%20Plorvan", T["recepcion1"], 200).json()["data"]
dato("no encuentra a nadie", d == [])
dato("como máximo 5 resultados", len(requests.get(API + "/pacientes/posibles-duplicados?nombre_completo=Maria%20Garcia",
                                                    headers=H("recepcion1")).json()["data"]) <= 5)

print("--- Reporte de diagnósticos más frecuentes")
for paciente, texto_dx in ((p1, "Rinitis de prueba."), (p2, "RINITIS DE PRUEBA"), (p2, "rinitis de prueba" + chr(10) + "Con congestión")):
    check("medico1 registra una atención para el reporte", "POST", f"/expedientes/{paciente}/atenciones", T["medico1"], 201,
          json={"diagnostico": texto_dx})
rep = check("jefatura1 ve el reporte", "GET", "/reportes/diagnosticos?limite=50", T["jefatura1"], 200).json()
fila = next((x for x in rep["data"] if x["diagnostico"].lower() == "rinitis de prueba"), None)
dato("agrupa sin importar mayúsculas, punto final ni la segunda línea", fila is not None and fila["atenciones"] >= 3 and fila["pacientes"] == 2)
dato("trae totales y porcentajes", rep["total_atenciones"] >= 3 and 0 < fila["porcentaje"] <= 100 and bool(rep["desde"] and rep["hasta"]))
dato("solo cifras: ningún dato de pacientes", "paciente_id" not in str(rep) and "Perez" not in str(rep) and "Garcia" not in str(rep))
aud = check("analista1 (Auditoría) ve el reporte", "GET", "/reportes/diagnosticos?limite=50", T["analista1"], 200).json()
dato("para Auditoría, un diagnóstico de solo 2 pacientes se suma en 'Otros'",
     not any(x["diagnostico"].lower() == "rinitis de prueba" for x in aud["data"]) and aud["data"][-1]["diagnostico"] == "Otros diagnósticos")
dato("Auditoría y Jefatura suman el mismo total", aud["total_atenciones"] == rep["total_atenciones"])
check("recepcion1 NO ve el reporte", "GET", "/reportes/diagnosticos", T["recepcion1"], 403)
check("ciudadano1 NO ve el reporte", "GET", "/reportes/diagnosticos", T["ciudadano1"], 403)
check("fecha con otro formato", "GET", "/reportes/diagnosticos?desde=01/10/2026", T["jefatura1"], 400)
check("desde después de hasta", "GET", "/reportes/diagnosticos?desde=2026-10-10&hasta=2026-10-01", T["jefatura1"], 400)
check("período de más de 3 años", "GET", "/reportes/diagnosticos?desde=2020-01-01&hasta=2026-01-01", T["jefatura1"], 400)
check("límite fuera de rango", "GET", "/reportes/diagnosticos?limite=0", T["jefatura1"], 400)
vacio = check("un período sin atenciones", "GET", "/reportes/diagnosticos?desde=2001-01-01&hasta=2001-12-31", T["jefatura1"], 200).json()
dato("da cero sin fallar", vacio["total_atenciones"] == 0 and vacio["data"] == [])

print("--- Diagnósticos con código CIE-10")
r = check("medico1 busca 'hiper arter' en la CIE-10", "GET", "/cie10?q=hiper%20arter", T["medico1"], 200).json()
dato("encuentra I10 Hipertensión esencial", bool(r["data"]) and r["data"][0]["codigo"] == "I10" and r["total_catalogo"] > 200)
check("analista1 (Auditoría) también busca", "GET", "/cie10?q=J00", T["analista1"], 200)
check("recepcion1 NO busca diagnósticos", "GET", "/cie10?q=gripe", T["recepcion1"], 403)
check("ciudadano1 NO busca diagnósticos", "GET", "/cie10?q=gripe", T["ciudadano1"], 403)
check("búsqueda vacía", "GET", "/cie10?q=", T["medico1"], 400)
check("límite fuera de rango", "GET", "/cie10?q=a&limite=0", T["medico1"], 400)
check("código que no está en el catálogo", "POST", f"/expedientes/{p2}/atenciones", T["medico1"], 400,
      json={"codigo_cie10": "X99.9"})
check("código que no es texto", "POST", f"/expedientes/{p2}/atenciones", T["medico1"], 400, json={"codigo_cie10": 10})
check("atención solo con el código (sin escribir el diagnóstico)", "POST", f"/expedientes/{p2}/atenciones", T["medico1"], 201,
      json={"codigo_cie10": "z02.7"})
ultima = max(requests.get(API + f"/expedientes/{p2}", headers=H("medico1")).json()["data"], key=lambda x: x["id"])
dato("se guarda el código en mayúsculas y el diagnóstico es su nombre oficial",
     ultima["codigo_cie10"] == "Z02.7" and ultima["diagnostico"] == "Extensión de certificado médico" and ultima["cie10"] == ultima["diagnostico"])
check("otra atención con el mismo código pero escrito distinto", "POST", f"/expedientes/{p1}/atenciones", T["medico1"], 201,
      json={"codigo_cie10": "Z02.7", "diagnostico": "Constancia para el trabajo"})
rep = check("el reporte agrupa por código CIE-10", "GET", "/reportes/diagnosticos?limite=50", T["jefatura1"], 200).json()
fila = next((x for x in rep["data"] if x.get("codigo_cie10") == "Z02.7"), None)
dato("una sola fila 'Z02.7 · Extensión de certificado médico' con las dos atenciones",
     fila is not None and fila["diagnostico"] == "Z02.7 · Extensión de certificado médico" and fila["atenciones"] >= 2
     and fila["pacientes"] >= 2)

print("--- Constancias de consulta e incapacidad (con QR verificable)")
CON = "/constancias"
hoy = date.today().isoformat()
check("enfermera1 NO emite constancias", "POST", CON, T["enfermera1"], 403, json={"paciente_id": p1, "tipo": "CONSULTA"})
check("recepcion1 NO ve constancias", "GET", CON, T["recepcion1"], 403)
check("tipo inválido", "POST", CON, T["medico1"], 400, json={"paciente_id": p1, "tipo": "PERMISO"})
check("incapacidad sin días", "POST", CON, T["medico1"], 400, json={"paciente_id": p1, "tipo": "INCAPACIDAD"})
check("incapacidad de 61 días", "POST", CON, T["medico1"], 400, json={"paciente_id": p1, "tipo": "INCAPACIDAD", "dias_reposo": 61})
check("consulta con días de reposo", "POST", CON, T["medico1"], 400, json={"paciente_id": p1, "tipo": "CONSULTA", "dias_reposo": 2})
check("reposo que empieza antes de la atención", "POST", CON, T["medico1"], 400,
      json={"paciente_id": p1, "tipo": "INCAPACIDAD", "dias_reposo": 2, "desde": "2020-01-01"})
check("fecha de atención en el futuro", "POST", CON, T["medico1"], 400,
      json={"paciente_id": p1, "tipo": "CONSULTA", "fecha_atencion": "2099-01-01"})
check("paciente que no existe", "POST", CON, T["medico1"], 404, json={"paciente_id": 999999, "tipo": "CONSULTA"})
ci = check("medico1 emite una incapacidad de 3 días", "POST", CON, T["medico1"], 201,
           json={"paciente_id": p1, "tipo": "INCAPACIDAD", "dias_reposo": 3, "desde": hoy,
                 "diagnostico": "Faringitis aguda", "observaciones": "Reposo en casa."}).json()["data"]
dato("calcula hasta qué día es el reposo (3 días contando el primero)",
     ci["hasta"] == (date.today() + timedelta(days=2)).isoformat() and ci["estado"] == "VIGENTE")
dato("trae su código del QR (12 caracteres)", len(ci["codigo_verificacion"] or "") == 12)
cc = check("medico1 emite una constancia de consulta", "POST", CON, T["medico1"], 201,
           json={"paciente_id": p1, "tipo": "CONSULTA"}).json()["data"]
dato("la constancia de consulta no lleva reposo", cc["dias_reposo"] is None and cc["desde"] is None)
check("enfermera1 ve la constancia para imprimirla", "GET", f"{CON}/{ci['id']}", T["enfermera1"], 200)
lista = check("constancias del paciente", "GET", f"{CON}?paciente_id={p1}", T["jefatura1"], 200).json()["data"]
dato("aparecen las dos", {ci["id"], cc["id"]} <= {x["id"] for x in lista})
v = check("verificar la incapacidad sin token", "GET", f"/verificar/constancia/{ci['codigo_verificacion']}", None, 200).json()["data"]
crudo = requests.get(API + f"/verificar/constancia/{ci['codigo_verificacion']}").text
dato("dice tipo, días y fechas, pero NO el diagnóstico ni el nombre", v["tipo"] == "INCAPACIDAD" and v["dias_reposo"] == 3
     and v["hasta"] == ci["hasta"] and "Faringitis" not in crudo and "Perez" not in crudo and bool(v["paciente_iniciales"]))
check("un código alterado no existe", "GET", "/verificar/constancia/" + ci["codigo_verificacion"][:-1] + "Z", None, 404)
check("el código de una receta no sirve para constancias", "GET", f"/verificar/constancia/{cod}", None, 404)
check("anular sin motivo", "POST", f"{CON}/{cc['id']}/anular", T["medico1"], 400, json={})
check("enfermera1 NO anula", "POST", f"{CON}/{cc['id']}/anular", T["enfermera1"], 403, json={"motivo": "Prueba de anulación"})
check("medico1 anula su constancia", "POST", f"{CON}/{cc['id']}/anular", T["medico1"], 200, json={"motivo": "Prueba de anulación"})
check("no se anula dos veces", "POST", f"{CON}/{cc['id']}/anular", T["medico1"], 409, json={"motivo": "Prueba de anulación"})
dato("al verificarla sale ANULADA", requests.get(API + f"/verificar/constancia/{cc['codigo_verificacion']}").json()["data"]["estado"] == "ANULADA")
mias = check("ciudadano1 (dueño de p1) ve sus constancias", "GET", CON, T["ciudadano1"], 200).json()["data"]
dato("y solo las suyas", bool(mias) and all(x["paciente_id"] == p1 for x in mias))
check("ciudadano1 abre su incapacidad para imprimirla", "GET", f"{CON}/{ci['id']}", T["ciudadano1"], 200)
check("ciudadano2 NO ve la constancia de otro (404)", "GET", f"{CON}/{ci['id']}", T["ciudadano2"], 404)
bit = requests.get(API + f"/bitacora/accesos?paciente_id={p1}&usuario=medico1&limite=100", headers=H("admin.salud")).json()["data"]
dato("la bitácora anota la constancia emitida", any(x["descripcion"] == f"Emitió la constancia No. {ci['id']}" for x in bit))

print("--- Laboratorio clínico: orden, muestra, resultados e interpretación")
LAB = "/laboratorio/ordenes"
cat = check("enfermera1 ve el catálogo de exámenes", "GET", "/laboratorio/examenes", T["enfermera1"], 200).json()["data"]
dato("el catálogo trae parámetros con su rango de referencia",
     any(e["codigo"] == "GLUCOSA" and e["parametros"][0]["referencia"] == "70 – 100 mg/dL" for e in cat))
check("recepcion1 NO ve el laboratorio", "GET", "/laboratorio/examenes", T["recepcion1"], 403)
check("enfermera1 NO ordena exámenes", "POST", LAB, T["enfermera1"], 403, json={"paciente_id": p1, "examenes": ["GLUCOSA"]})
check("orden sin exámenes", "POST", LAB, T["medico1"], 400, json={"paciente_id": p1, "examenes": []})
check("examen que no existe", "POST", LAB, T["medico1"], 400, json={"paciente_id": p1, "examenes": ["RAYOS_X"]})
check("examen repetido", "POST", LAB, T["medico1"], 400, json={"paciente_id": p1, "examenes": ["GLUCOSA", "GLUCOSA"]})
check("examenes que no son texto", "POST", LAB, T["medico1"], 400, json={"paciente_id": p1, "examenes": [1, 2]})
check("prioridad inválida", "POST", LAB, T["medico1"], 400, json={"paciente_id": p1, "examenes": ["GLUCOSA"], "prioridad": "YA"})
check("paciente que no existe", "POST", LAB, T["medico1"], 404, json={"paciente_id": 999999, "examenes": ["GLUCOSA"]})
orden = check("medico1 pide glucosa y orina, urgente", "POST", LAB, T["medico1"], 201,
              json={"paciente_id": p1, "examenes": ["GLUCOSA", "ORINA"], "prioridad": "URGENTE",
                    "indicaciones": "Ayuno de 8 horas"}).json()["data"]
dato("queda PENDIENTE, a nombre del médico", orden["estado"] == "PENDIENTE" and orden["medico"] and len(orden["examenes"]) == 2)
cola = check("la cola de pendientes", "GET", f"{LAB}?estado=PENDIENTE", T["enfermera1"], 200).json()["data"]
dato("la orden urgente sale en la cola", any(x["id"] == orden["id"] for x in cola)
     and [x["prioridad"] for x in cola] == sorted([x["prioridad"] for x in cola], key=lambda pr: pr != "URGENTE"))
check("estado inválido en el filtro", "GET", f"{LAB}?estado=LISTA", T["enfermera1"], 400)
check("resultados antes de tomar la muestra", "PUT", f"{LAB}/{orden['id']}/resultados", T["enfermera1"], 409,
      json={"resultados": {"GLUCOSA": {"glucosa": 90}}})
check("medico1 NO toma muestras", "POST", f"{LAB}/{orden['id']}/muestra", T["medico1"], 403)
check("enfermera1 toma la muestra", "POST", f"{LAB}/{orden['id']}/muestra", T["enfermera1"], 200)
check("no se toma la muestra dos veces", "POST", f"{LAB}/{orden['id']}/muestra", T["enfermera1"], 409)
R = f"{LAB}/{orden['id']}/resultados"
check("valor imposible (glucosa 99999)", "PUT", R, T["enfermera1"], 400, json={"resultados": {"GLUCOSA": {"glucosa": 99999}}})
check("parámetro que no existe", "PUT", R, T["enfermera1"], 400, json={"resultados": {"GLUCOSA": {"azucar": 90}}})
check("examen que no está en la orden", "PUT", R, T["enfermera1"], 400, json={"resultados": {"HEMATO": {"hemoglobina": 13}}})
check("opción que no existe (nitritos)", "PUT", R, T["enfermera1"], 400, json={"resultados": {"ORINA": {"nitritos": "Mucho"}}})
check("resultados que no son objeto", "PUT", R, T["enfermera1"], 400, json={"resultados": [1, 2]})
parcial = check("guarda la glucosa (parcial)", "PUT", R, T["enfermera1"], 200,
                json={"resultados": {"GLUCOSA": {"glucosa": "182"}}}).json()
glu = parcial["data"]["examenes"][0]["resultados"][0]
dato("la glucosa 182 sale ALTA y el mensaje lo avisa", glu["valor"] == 182 and glu["nivel"] == "alto" and "fuera de rango" in parcial["message"])
check("completar sin todos los resultados", "PUT", R, T["enfermera1"], 400, json={"resultados": {}, "completar": True})
orina = {"ph": 6, "densidad": 1.02, "proteinas": "Negativo", "glucosa_orina": "Negativo", "nitritos": "Positivo",
         "leucocitos_campo": 25, "eritrocitos_campo": 1, "bacterias": "Abundantes"}
fin = check("completa la orina y la orden", "PUT", R, T["enfermera1"], 200,
            json={"resultados": {"ORINA": orina}, "observaciones": "Muestra de chorro medio", "completar": True}).json()["data"]
dato("queda COMPLETADA con quién y cuándo", fin["estado"] == "COMPLETADA" and fin["resultado_por"] and fin["fecha_resultado"])
dato("cuenta 4 resultados fuera de rango (glucosa, nitritos, leucocitos, bacterias)", fin["fuera_de_rango"] == 4)
check("una orden completada ya no se edita", "PUT", R, T["enfermera1"], 409, json={"resultados": {"GLUCOSA": {"glucosa": 90}}})
check("ni se anula", "POST", f"{LAB}/{orden['id']}/anular", T["medico1"], 409, json={"motivo": "Prueba de anulación"})
mia = check("ciudadano1 (dueño) ve su resultado completado", "GET", f"{LAB}/{orden['id']}", T["ciudadano1"], 200).json()["data"]
dato("con los resultados", mia["examenes"][0]["resultados"][0]["valor"] == 182)
check("ciudadano2 NO ve la orden de otro (404)", "GET", f"{LAB}/{orden['id']}", T["ciudadano2"], 404)
otra = check("otra orden para anular", "POST", LAB, T["medico1"], 201, json={"paciente_id": p1, "examenes": ["HEMATO"]}).json()["data"]
pend = check("ciudadano1 ve su orden pendiente", "GET", f"{LAB}/{otra['id']}", T["ciudadano1"], 200).json()["data"]
dato("pero sin resultados mientras no esté completa", "resultados" not in pend["examenes"][0])
check("anular sin motivo", "POST", f"{LAB}/{otra['id']}/anular", T["medico1"], 400, json={})
check("medico1 anula su orden", "POST", f"{LAB}/{otra['id']}/anular", T["medico1"], 200, json={"motivo": "Se pidió por error"})
bit = requests.get(API + f"/bitacora/accesos?paciente_id={p1}&limite=200", headers=H("admin.salud")).json()["data"]
dato("la bitácora anota la orden y los resultados", any(x["descripcion"] == f"Ordenó los exámenes de laboratorio No. {orden['id']}" for x in bit)
     and any(x["descripcion"] == f"Registró resultados de la orden de laboratorio No. {orden['id']}" for x in bit))

print("--- Accesos inusuales en la bitácora (solo Administración)")
INU = "/bitacora/inusuales"
check("accesos inusuales sin token", "GET", INU, None, 401)
check("medico1 NO ve los accesos inusuales", "GET", INU, T["medico1"], 403)
check("jefatura1 NO ve los accesos inusuales", "GET", INU, T["jefatura1"], 403)
for x in requests.get(API + "/pacientes", headers=H("medico1")).json()["data"][:3]:
    requests.get(API + f"/pacientes/{x['id']}", headers=H("medico1"))      # 3 pacientes distintos ahora mismo
r = check("admin.salud ve los accesos inusuales (umbrales bajos)", "GET",
          f"{INU}?pacientes_por_hora=2&anulaciones_por_dia=2", T["admin.salud"], 200).json()
dato("medico1 aparece por ver muchos pacientes en una hora", any(
    a["tipo"] == "muchos_pacientes" and a["usuario"] == "medico1" and a["cantidad"] >= 3 for a in r["data"]))
dato("medico1 aparece por las anulaciones de hoy (recetas de prueba)", any(
    a["tipo"] == "muchas_anulaciones" and a["usuario"] == "medico1" and a["nivel"] == "alto" for a in r["data"]))
dato("los ciudadanos no cuentan", all(a["puesto"] != "Ciudadano" for a in r["data"]))
niveles = [a["nivel"] for a in r["data"]]
dato("primero los de nivel alto", niveles == sorted(niveles, key=lambda n: n != "alto"))
dato("devuelve los umbrales usados", r["umbrales"]["pacientes_por_hora"] == 2 and r["umbrales"]["dias"] == 7)
check("dias fuera de rango", "GET", f"{INU}?dias=0", T["admin.salud"], 400)
check("dias que no es número", "GET", f"{INU}?dias=siete", T["admin.salud"], 400)
check("umbral de pacientes demasiado bajo", "GET", f"{INU}?pacientes_por_hora=1", T["admin.salud"], 400)

print("--- Estado del servicio (monitor externo, sin token)")
e = check("estado sin token", "GET", "/estado", None, 200)
dato("dice ok y nada más (ni versión, ni datos)", e.json() == {"success": True, "estado": "ok"}
     and e.headers.get("Cache-Control") == "no-store")
check("estado no acepta POST", "POST", "/estado", None, 405)

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
