"""
Prueba de QA con datos basura: ataca cada endpoint que crea, edita o borra
(los saca de Swagger) y avisa si alguno responde 500 o una página HTML.

  - Tokens falsos: Bearer null, undefined, vacío, alterado, alg=none.
  - Cuerpos raros: vacío, null, [], texto, JSON mal escrito.
  - Cada campo con: null, "", espacios, números, listas, objetos, booleanos,
    5000 caracteres, SQL, <script>, fechas imposibles, emojis.

SOLO EN LA PC: escribe miles de datos basura. Antes saca una copia de la base
local con mysqldump y al final la restaura, así la base queda como estaba.
Necesita lo mismo que prueba_auth.py (Keycloak local, simuladores y backend).

Uso (en la PC, desde SALUD-BACKEND):  venv\\Scripts\\python pruebas\\prueba_qa.py
"""
import base64
import collections
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

import requests
from dotenv import load_dotenv

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
load_dotenv(os.path.join(RAIZ, ".env"))

API = "http://127.0.0.1:5050"
AUTH = "http://localhost:8081/realms/rsd/protocol/openid-connect/token"
USUARIOS = ["admin.salud", "medico1", "enfermera1", "recepcion1", "farmacia1", "caja1", "jefatura1"]

# --- Seguridad: solo contra la base local ---------------------------------------
m = re.match(r".*://(\w+):(.*)@([^/:]+)(?::\d+)?/(\w+)", os.getenv("DATABASE_URL", ""))
if not m or m.group(3) not in ("localhost", "127.0.0.1"):
    sys.exit("DATABASE_URL no apunta a una base local: esta prueba solo se corre en la PC.")
USUARIO_DB, CLAVE_DB, HOST_DB, BASE_DB = m.groups()
BIN = r"C:\Program Files\MySQL\MySQL Server 8.0\bin"
MYSQLDUMP = shutil.which("mysqldump") or os.path.join(BIN, "mysqldump.exe")
MYSQL = shutil.which("mysql") or os.path.join(BIN, "mysql.exe")
if not os.path.exists(MYSQLDUMP):
    sys.exit("No se encontró mysqldump: sin copia de la base no se corre la prueba.")
ENV_DB = {**os.environ, "MYSQL_PWD": CLAVE_DB}


def token(usuario):
    return requests.post(AUTH, data={"client_id": "rsd-test-cli", "grant_type": "password",
                                     "username": usuario, "password": "Demo2026*"}).json()["access_token"]


def ids_reales():
    """Un id existente por recurso, para que las rutas con {id} lleguen a la validación."""
    import logging
    logging.disable(logging.CRITICAL)
    from app import crear_app
    import models as M
    ids = {}
    with crear_app().app_context():
        for segmento, modelo in {"pacientes": M.Paciente, "citas": M.CitaMedica, "servicios": M.Servicio,
                                 "cuentas": M.CuentaPaciente, "movimientos": M.MovimientoCuenta,
                                 "medicamentos": M.Medicamento, "recetas": M.Receta, "camas": M.Cama,
                                 "hospitalizaciones": M.Hospitalizacion, "recursos": M.RecursoHospitalario,
                                 "turnos": M.Turno}.items():
            fila = modelo.query.order_by(modelo.id.desc()).first()
            ids[segmento] = fila.id if fila else 1
        vacuna = M.Vacunacion.query.first()
        ids["vacunacion"] = vacuna.paciente_id if vacuna else 1
        ids["expedientes"] = ids["pacientes"]
    logging.disable(logging.NOTSET)
    return ids


VALORES = {
    "null": None, "vacío": "", "espacios": "   ", "número": 12345, "negativo": -5, "cero": 0,
    "número enorme": 1e308, "lista": [1, 2], "objeto": {"a": 1}, "booleano": True,
    "texto de 5000": "x" * 5000, "SQL": "' OR 1=1; DROP TABLE pacientes; --",
    "script": "<script>alert(1)</script>", "fecha imposible": "2026-13-45", "emojis": "😀" * 10,
}
CUERPOS_RAROS = {"sin cuerpo": None, "JSON mal escrito": "{malo", "arreglo": "[]", "null": "null", "texto": "hola"}


def atacar():
    tokens = {u: token(u) for u in USUARIOS}
    clave_api = os.getenv("MODULOS_API_KEY", "")
    fallas = []   # (endpoint, caso, status)

    # 1. Tokens falsos
    t = tokens["admin.salud"]
    falso = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")  # noqa: E731
    for caso, valor in {
        "Bearer null": "Bearer null", "Bearer undefined": "Bearer undefined", "Bearer vacío": "Bearer ",
        "token sin Bearer": t, "token alterado": "Bearer " + t[:-4] + "AAAA", "basura": "Bearer abc.def.ghi",
        "alg none": "Bearer " + falso({"alg": "none"}) + "." + falso(
            {"sub": "x", "aud": "rsd-api", "exp": 9999999999, "realm_access": {"roles": ["salud:admin"]}}) + ".",
    }.items():
        r = requests.get(f"{API}/api/v1/salud/pacientes", headers={"Authorization": valor})
        if r.status_code != 401:
            fallas.append(("GET /pacientes", caso, r.status_code))

    # 2. Endpoints de escritura con datos basura
    ids = ids_reales()
    spec = requests.get(f"{API}/apispec_1.json").json()
    enviadas = 0
    for ruta, operaciones in spec["paths"].items():
        for metodo, op in operaciones.items():
            metodo = metodo.upper()
            if metodo not in ("POST", "PUT", "DELETE"):
                continue
            partes = ruta.split("/")
            for i, p in enumerate(partes):
                if p.startswith("{"):
                    partes[i] = str(ids.get(partes[i - 1], 1))
            url = API + "/".join(partes)
            # el primer puesto que sí tiene permiso en esta ruta
            hdr = {"Authorization": f"Bearer {t}", "Content-Type": "application/json"}
            for u in USUARIOS:
                prueba = {"Authorization": f"Bearer {tokens[u]}", "Content-Type": "application/json"}
                if requests.request(metodo, url, headers=prueba, json={}).status_code != 403:
                    hdr = prueba
                    break
            if clave_api:
                hdr["X-API-Key"] = clave_api
            campos = {}
            for p in op.get("parameters", []):
                if p.get("in") == "body":
                    campos = p.get("schema", {}).get("properties", {}) or {}

            casos = [(c, {"data": cuerpo}) for c, cuerpo in CUERPOS_RAROS.items()]
            casos += [(f"{campo}={c}", {"json": {campo: v}}) for campo in campos for c, v in VALORES.items()]
            casos += [(f"todos={c}", {"json": {campo: v for campo in campos}}) for c, v in VALORES.items() if campos]
            for caso, kw in casos:
                enviadas += 1
                r = requests.request(metodo, url, headers=hdr, **kw)
                if r.status_code >= 500 or "<html" in r.text.lower():
                    fallas.append((f"{metodo} {ruta}", caso, r.status_code))
    return enviadas, fallas


def main():
    copia = os.path.join(tempfile.gettempdir(), f"{BASE_DB}_antes_de_prueba_qa.sql")
    with open(copia, "wb") as f:
        if subprocess.run([MYSQLDUMP, "-u", USUARIO_DB, "-h", HOST_DB, "--single-transaction",
                           "--databases", BASE_DB], stdout=f, env=ENV_DB).returncode != 0:
            sys.exit("No se pudo copiar la base local; no se corre la prueba.")
    print(f"Copia de la base local: {copia}")
    try:
        enviadas, fallas = atacar()
    finally:
        with open(copia, "rb") as f:
            ok = subprocess.run([MYSQL, "-u", USUARIO_DB, "-h", HOST_DB], stdin=f, env=ENV_DB).returncode == 0
        print("Base local restaurada" if ok else f"FALLA al restaurar: restáurela a mano desde {copia}")

    print(f"\nPeticiones con datos basura: {enviadas}")
    if not fallas:
        print("OK: ninguna respondió 500 ni HTML, y todos los tokens falsos dieron 401")
        sys.exit(0)
    por_endpoint = collections.defaultdict(list)
    for endpoint, caso, status in fallas:
        por_endpoint[endpoint].append(f"{caso} -> {status}")
    for endpoint, casos in por_endpoint.items():
        print(f"FALLA {endpoint}: {len(casos)} caso(s), por ejemplo {', '.join(casos[:5])}")
    sys.exit(1)


if __name__ == "__main__":
    main()
