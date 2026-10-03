"""
Agrega los puestos de la matriz de permisos (roles y usuarios de prueba) a un
Keycloak que YA tiene el realm "rsd", sin reimportarlo: los usuarios
existentes conservan su "sub" (y su vínculo con los pacientes).

Se puede correr varias veces: lo que ya existe no se toca.

Uso (solo Python 3, sin librerías extra):
    python agregar_puestos.py                          # Keycloak en http://localhost:8081
    python agregar_puestos.py http://localhost:8081

Pide el usuario y la contraseña del ADMIN de Keycloak (realm master).
En el servidor, la consola solo responde en localhost:8081 (por SSH).
"""
import getpass
import json
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8081").rstrip("/")
REALM = "rsd"
CLAVE_DEMO = "Demo2026*"

ROLES = {
    "salud:enfermeria": "Enfermería: triaje, vacunación, hospitalización y camas",
    "salud:recepcion": "Recepción / Admisión: pacientes, citas y turnos (sin datos clínicos)",
    "salud:farmacia": "Farmacia: despacho de recetas e inventario de medicamentos",
    "salud:caja": "Caja: cobros, cuentas del paciente y verificación de pagos",
    "salud:jefatura": "Jefatura médica: personal médico, practicantes y reportes clínicos",
}

USUARIOS = [
    ("enfermera1", "Marta", "Ramírez", ["salud:enfermeria"]),
    ("recepcion1", "Julio", "Castillo", ["salud:recepcion"]),
    ("farmacia1", "Silvia", "Ordóñez", ["salud:farmacia"]),
    ("caja1", "Roberto", "Méndez", ["salud:caja"]),
    ("jefatura1", "Carmen", "Recinos", ["salud:jefatura", "salud:medico"]),
]


def pedir(metodo, ruta, token=None, datos=None, formulario=None):
    cabeceras = {}
    cuerpo = None
    if token:
        cabeceras["Authorization"] = f"Bearer {token}"
    if datos is not None:
        cuerpo = json.dumps(datos).encode()
        cabeceras["Content-Type"] = "application/json"
    if formulario is not None:
        cuerpo = urllib.parse.urlencode(formulario).encode()
        cabeceras["Content-Type"] = "application/x-www-form-urlencoded"
    peticion = urllib.request.Request(BASE + ruta, data=cuerpo, headers=cabeceras, method=metodo)
    try:
        with urllib.request.urlopen(peticion, timeout=15) as r:
            texto = r.read().decode()
            return r.status, (json.loads(texto) if texto else None)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:300]


def main():
    print(f"Keycloak: {BASE}  (realm {REALM})")
    usuario = input("Usuario admin de Keycloak [admin]: ").strip() or "admin"
    clave = getpass.getpass("Contraseña del admin (no se ve al escribir): ")
    status, r = pedir("POST", "/realms/master/protocol/openid-connect/token", formulario={
        "client_id": "admin-cli", "grant_type": "password", "username": usuario, "password": clave})
    if status != 200:
        sys.exit(f"No se pudo iniciar sesión como admin ({status}). Revise usuario, contraseña y URL.")
    token = r["access_token"]
    api = f"/admin/realms/{REALM}"

    for nombre, descripcion in ROLES.items():
        status, _ = pedir("GET", f"{api}/roles/{urllib.parse.quote(nombre, safe='')}", token)
        if status == 200:
            print(f"  ya existe  rol {nombre}")
            continue
        status, r = pedir("POST", f"{api}/roles", token, {"name": nombre, "description": descripcion})
        print(f"  {'creado    ' if status == 201 else 'FALLA ' + str(status)} rol {nombre}")

    for nombre_usuario, nombre, apellido, roles in USUARIOS:
        status, encontrados = pedir("GET", f"{api}/users?exact=true&username={nombre_usuario}", token)
        if encontrados:
            print(f"  ya existe  usuario {nombre_usuario}")
            continue
        status, r = pedir("POST", f"{api}/users", token, {
            "username": nombre_usuario, "enabled": True, "firstName": nombre, "lastName": apellido,
            "email": f"{nombre_usuario}@demo.gt", "emailVerified": True,
            "credentials": [{"type": "password", "value": CLAVE_DEMO, "temporary": False}]})
        if status != 201:
            print(f"  FALLA {status} usuario {nombre_usuario}: {r}")
            continue
        _, encontrados = pedir("GET", f"{api}/users?exact=true&username={nombre_usuario}", token)
        id_usuario = encontrados[0]["id"]
        representaciones = []
        for rol in ["servidor_publico", *roles]:
            s, rep = pedir("GET", f"{api}/roles/{urllib.parse.quote(rol, safe='')}", token)
            if s == 200:
                representaciones.append(rep)
        s, _ = pedir("POST", f"{api}/users/{id_usuario}/role-mappings/realm", token, representaciones)
        print(f"  {'creado    ' if s == 204 else 'FALLA ' + str(s)} usuario {nombre_usuario} ({', '.join(roles)})")

    print(f"\nListo. Contraseña de los usuarios nuevos: {CLAVE_DEMO}")


if __name__ == "__main__":
    main()
