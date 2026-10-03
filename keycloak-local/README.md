# Login Único local (réplica para desarrollo)

Réplica del realm `rsd` para trabajar sin depender de la URL del túnel, que cambia cada día.
Sigue el contrato de "Cómo consumir el Login Único":

| Dato | Valor |
|---|---|
| Issuer | `http://localhost:8081/realms/rsd` |
| Client del frontend | `salud-web` (público, Authorization Code + PKCE) |
| Client para curl | `rsd-test-cli` (solo terminal) |
| Audiencia (`aud`) | `rsd-api` |
| Usuarios | `medico1`, `admin.salud`, `ciudadano1`, `ciudadano2`, `analista1`, y los puestos `enfermera1`, `recepcion1`, `farmacia1`, `caja1`, `jefatura1` |
| Contraseña | `Demo2026*` |
| Roles | `salud:medico`, `salud:admin`, `salud:enfermeria`, `salud:recepcion`, `salud:farmacia`, `salud:caja`, `salud:jefatura`, `ciudadano`, `servidor_publico`, `auditoria:*` |

> Si la ingeniera comparte el export oficial del realm, reemplacen `import/rsd-realm.json` por ese archivo.
> El `sub` de cada usuario aquí es distinto al del servidor oficial. Por eso no se guardan subs en los datos de prueba.

## Levantar

```bash
cd keycloak-local
docker compose -f docker-compose.local.yml up -d
```

Consola de administración: http://localhost:8081/admin (usuario `admin` y contraseña `admin`).

## Probar un token (Git Bash)

```bash
AUTH=http://localhost:8081/realms/rsd
TOKEN=$(curl -s -X POST "$AUTH/protocol/openid-connect/token" \
  -d client_id=rsd-test-cli -d grant_type=password \
  -d username=medico1 -d "password=Demo2026*" \
  | python -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

curl -i http://localhost:5050/api/v1/salud/pacientes                                  # 401 sin token
curl -i -H "Authorization: Bearer $TOKEN" http://localhost:5050/api/v1/salud/pacientes # 200 con token
```

Para usar el Login Único oficial, solo cambien `AUTH_ISSUER` en el `.env` del backend por `<URL_DEL_DIA>/realms/rsd` y reinicien el backend.

## Agregar los puestos a un Keycloak que ya está funcionando

`import/rsd-realm.json` solo se importa la primera vez. Para agregar los roles y usuarios de la matriz de permisos a un Keycloak existente **sin perder los `sub`** de los usuarios actuales:

```bash
python keycloak-local/agregar_puestos.py                       # http://localhost:8081
```

Pide el usuario y la contraseña del **admin** de Keycloak. Se puede correr varias veces: lo que ya existe no se toca. En el servidor, la consola solo responde en `localhost:8081`, así que se corre desde el servidor o por un túnel SSH.
