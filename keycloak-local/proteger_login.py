"""
Activa la protección contra fuerza bruta del realm "rsd" en un Keycloak que ya
está funcionando: después de 5 contraseñas equivocadas seguidas, el usuario
queda bloqueado 1 minuto, y la espera crece con cada nuevo intento fallido
(hasta 15 minutos). El bloqueo es temporal: nunca deshabilita la cuenta.

Se puede correr varias veces: solo cambia esas opciones del realm.

Uso (solo Python 3, sin librerías extra):
    python proteger_login.py                          # Keycloak en http://localhost:8081
    python proteger_login.py http://localhost:8081

Pide el usuario y la contraseña del ADMIN de Keycloak (realm master).
En el servidor, la consola solo responde en localhost:8081 (por SSH).
"""
import getpass
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # para encontrar agregar_puestos.py
from agregar_puestos import BASE, REALM, pedir  # noqa: E402

PROTECCION = {
    "bruteForceProtected": True,
    "permanentLockout": False,           # bloqueo temporal, la cuenta no se deshabilita
    "failureFactor": 5,                  # intentos fallidos antes de bloquear
    "waitIncrementSeconds": 60,          # primera espera: 1 minuto
    "maxFailureWaitSeconds": 900,        # espera máxima: 15 minutos
    "maxDeltaTimeSeconds": 43200,        # el contador de fallos se reinicia a las 12 horas
    "minimumQuickLoginWaitSeconds": 60,  # intentos a máquina (menos de 1 s entre sí): 1 minuto
    "quickLoginCheckMilliSeconds": 1000,
}


def main():
    print(f"Keycloak: {BASE}  (realm {REALM})")
    usuario = input("Usuario admin de Keycloak [admin]: ").strip() or "admin"
    clave = getpass.getpass("Contraseña del admin (no se ve al escribir): ")
    status, r = pedir("POST", "/realms/master/protocol/openid-connect/token", formulario={
        "client_id": "admin-cli", "grant_type": "password", "username": usuario, "password": clave})
    if status != 200:
        sys.exit(f"No se pudo iniciar sesión como admin ({status}). Revise usuario, contraseña y URL.")
    token = r["access_token"]

    status, realm = pedir("GET", f"/admin/realms/{REALM}", token)
    if status != 200:
        sys.exit(f"No se encontró el realm {REALM} ({status}).")
    realm.update(PROTECCION)
    status, r = pedir("PUT", f"/admin/realms/{REALM}", token, realm)
    if status != 204:
        sys.exit(f"FALLA {status}: {r}")

    _, realm = pedir("GET", f"/admin/realms/{REALM}", token)
    activa = all(realm.get(k) == v for k, v in PROTECCION.items())
    print("Protección contra fuerza bruta: " + ("ACTIVADA" if activa else "NO quedó activada, revise la consola"))
    print("  5 intentos fallidos -> espera de 1 minuto, que crece hasta 15 minutos. La cuenta no se deshabilita.")
    print("  Para desbloquear a alguien antes: consola de Keycloak -> Users -> el usuario -> 'Unlock'.")


if __name__ == "__main__":
    main()
