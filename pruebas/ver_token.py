"""
Revisa un token del Login Único contra lo que espera Salud y lo prueba en la API.

Pensado para la validación con Auditoría: si el tablero recibe 401 o 403, esto dice
por qué (emisor, audiencia, vencimiento o rol) sin tener que leer el JWT a mano.

Uso (en la PC, desde SALUD-BACKEND):
    venv\\Scripts\\python pruebas\\ver_token.py
    venv\\Scripts\\python pruebas\\ver_token.py --sitio http://127.0.0.1:5050 --issuer http://localhost:8081/realms/rsd

Pide el token sin mostrarlo en pantalla y no lo guarda en ningún lado.
Por defecto toma el emisor esperado de https://saludumg.online/config.js (la URL del día).
"""
import argparse
import base64
import getpass
import json
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime

AUDIENCIA = "rsd-api"
ROL = "auditoria:lectura"


def leer_json(url, token=None):
    peticion = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"} if token else {})
    try:
        with urllib.request.urlopen(peticion, timeout=15) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def partes(token):
    try:
        cabecera, cuerpo = (json.loads(base64.urlsafe_b64decode(p + "=" * (-len(p) % 4)))
                            for p in token.split(".")[:2])
        return cabecera, cuerpo
    except Exception:  # noqa: BLE001
        sys.exit("Eso no parece un token JWT (debe tener tres partes separadas por puntos).")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sitio", default="https://saludumg.online")
    ap.add_argument("--issuer", help="emisor esperado (por defecto, el de config.js del sitio)")
    args = ap.parse_args()

    issuer = args.issuer
    if not issuer:
        _, js = leer_json(args.sitio + "/config.js")
        encontrado = re.search(r'AUTH_URL:\s*"([^"]+)"', js)
        issuer = encontrado.group(1) if encontrado else "(no se pudo leer config.js)"

    token = getpass.getpass("Pegue el token (no se ve al pegar) y presione Enter: ").strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    cabecera, datos = partes(token)

    aud = datos.get("aud")
    auds = aud if isinstance(aud, list) else [aud] if aud else []
    roles = (datos.get("realm_access") or {}).get("roles", [])
    roles_cliente = {c: v.get("roles", []) for c, v in (datos.get("resource_access") or {}).items()}
    vence = datetime.fromtimestamp(datos["exp"]) if "exp" in datos else None
    falta = int((vence - datetime.now()).total_seconds()) if vence else None

    def fila(ok, texto):
        print(f"{'OK      ' if ok else 'REVISAR '} {texto}")

    print("\n=== Lo que trae el token")
    print(f"         usuario: {datos.get('preferred_username', '?')}   cliente (azp): {datos.get('azp', '?')}   algoritmo: {cabecera.get('alg')}")
    fila(datos.get("iss") == issuer, f"emisor: {datos.get('iss')}" + ("" if datos.get("iss") == issuer else f"  <- se espera {issuer}"))
    fila(AUDIENCIA in auds, f"audiencia: {', '.join(auds) or 'ninguna'}" + ("" if AUDIENCIA in auds else f"  <- falta {AUDIENCIA}"))
    fila(falta is not None and falta > 0, f"vence: {vence:%Y-%m-%d %H:%M:%S}" + (f" (quedan {falta} s)" if falta and falta > 0 else "  <- ya venció, pida uno nuevo") if vence else "sin fecha de vencimiento")
    fila(ROL in roles, f"roles del realm: {', '.join(roles) or 'ninguno'}" + ("" if ROL in roles else f"  <- falta {ROL}"))
    cliente_con_rol = [c for c, rs in roles_cliente.items() if ROL in rs]
    if cliente_con_rol and ROL not in roles:
        print(f"         ¡Ojo! {ROL} está como rol del CLIENTE {', '.join(cliente_con_rol)}: debe ser rol del REALM.")

    print(f"\n=== Prueba real: {args.sitio}/api/indicadores")
    status, cuerpo = leer_json(f"{args.sitio}/api/indicadores?desde=2026-01-01&hasta=2026-12-31", token)
    try:
        respuesta = json.loads(cuerpo)
    except ValueError:
        respuesta = {"mensaje": cuerpo[:200]}
    if status == 200:
        print(f"OK       200: {len(respuesta.get('indicadores', []))} indicadores y {len(respuesta.get('series', []))} series")
    else:
        print(f"REVISAR  {status}: {respuesta.get('error', '')} - {respuesta.get('mensaje') or respuesta.get('message')}")


if __name__ == "__main__":
    main()
