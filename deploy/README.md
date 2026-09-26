# Despliegue — Módulo de Salud

Despliegue con Docker Compose: **MySQL + backend (gunicorn) + frontend (nginx)**, expuesto en `https://saludumg.online` con un túnel de Cloudflare.
Los mismos pasos sirven para el servidor Ubuntu actual y para la máquina en la nube de finales de octubre.

```
Internet ──HTTPS──> Cloudflare ──túnel──> cloudflared (servidor)
                                              │
                                   http://localhost:8080
                                              │
                                   ┌──────────▼──────────┐
                                   │ frontend (nginx)    │  sirve la app y /config.js
                                   │   /api/ ──────────► │ backend (gunicorn :5050)
                                   └─────────────────────┘          │
                                                                 db (MySQL)
```

- Solo el **frontend** se publica, y únicamente en `127.0.0.1:8080`. MySQL y el backend no son accesibles desde fuera.
- El frontend y la API comparten dominio (nginx hace de proxy de `/api`), así que no hace falta CORS.
- La URL del Login Único se inyecta **al arrancar** (`/config.js`): cuando cambia la URL del día **no hay que recompilar**.

## 1. Requisitos en el servidor

- Docker con el plugin Compose (`docker compose version`).
- Git.
- `cloudflared` con el túnel con nombre ya creado (`salud-demo`).

## 2. Clonar los tres repos, uno al lado del otro

```bash
mkdir -p ~/salud && cd ~/salud
git clone -b denilson-dev https://github.com/Seminario01/SALUD-BACKEND.git
git clone -b denilson-dev https://github.com/Seminario01/SALUD-FRONTEND.git
git clone -b denilson-dev https://github.com/Seminario01/SALUD-DATABASE.git
```

Cuando los PR se fusionen, usen `main` en lugar de `denilson-dev`.

## 3. Configurar

```bash
cd ~/salud/SALUD-BACKEND/deploy
cp .env.example .env
nano .env
```

| Variable | Qué poner |
|---|---|
| `MYSQL_ROOT_PASSWORD`, `MYSQL_PASSWORD` | Contraseñas nuevas, **solo letras y números** (van dentro de una URL) |
| `AUTH_ISSUER` | `<URL_DEL_DIA>/realms/rsd`, la que comparte la ingeniera |
| `MODULOS_API_KEY` | Clave entre módulos (la misma que acuerden con los otros módulos) |
| `PUERTO_WEB` | Puerto local al que apunta el túnel (por defecto `8080`) |

El `.env` **nunca** se sube a GitHub (`deploy/.env` está en `.gitignore`).

## 4. Levantar

```bash
docker compose up -d --build
docker compose ps          # los 3 servicios en "running" (db en "healthy")
docker compose logs -f backend
```

La **primera vez** MySQL ejecuta `schema.sql`, `datos insertados.sql`, `datos_demo.sql` (20 pacientes ficticios con citas, expedientes y vacunación) y `demo_turnos_hoy.sql` de `SALUD-DATABASE` (tarda unos 30 segundos). En los arranques siguientes los datos se conservan en el volumen `salud_mysql`.

**Turnos para la presentación:** los turnos son "del día", así que los de la carga inicial dejan de verse al día siguiente. El día de la presentación, recargarlos con:

```bash
docker compose exec db sh -c 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" < /demo/demo_turnos_hoy.sql'
```

(Si ese día ya hay turnos, no hace nada.)

Comprobación local en el servidor:

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8080/                       # 200
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8080/api/v1/salud/pacientes # 401 (correcto: sin token)
curl -s http://127.0.0.1:8080/config.js                                               # debe mostrar el AUTH_URL
```

## 5. Túnel de Cloudflare

En la configuración de `cloudflared` (normalmente `/etc/cloudflared/config.yml`), la regla de `saludumg.online` debe apuntar al puerto del frontend:

```yaml
ingress:
  - hostname: saludumg.online
    service: http://localhost:8080
  - service: http_status:404
```

```bash
sudo systemctl restart cloudflared
```

## 6. Login Único en producción (pedir a la ingeniera)

Para que el login funcione en `https://saludumg.online`, el client `salud-web` debe tener registrados:

- Redirect URI: `https://saludumg.online/*`
- Web origin: `https://saludumg.online`

Sin eso, el Login Único responde `Invalid parameter: redirect_uri`.

## 7. Operación diaria

**Cambió la URL del día del Login Único:**

```bash
cd ~/salud/SALUD-BACKEND/deploy
nano .env                  # actualizar AUTH_ISSUER
docker compose up -d       # recrea backend y frontend con la nueva URL (sin recompilar)
```

**Actualizar a la última versión del código:**

```bash
cd ~/salud/SALUD-BACKEND && git pull
cd ~/salud/SALUD-FRONTEND && git pull
cd ~/salud/SALUD-BACKEND/deploy && docker compose up -d --build
```

**Respaldo de la base de datos:**

```bash
cd ~/salud/SALUD-BACKEND/deploy
docker compose exec -T db sh -c 'mysqldump -uroot -p"$MYSQL_ROOT_PASSWORD" salud_db' > respaldo_$(date +%F).sql
```

**Restaurar un respaldo:**

```bash
docker compose exec -T db sh -c 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" salud_db' < respaldo_AAAA-MM-DD.sql
```

## 8. Si ya tienen datos en una base anterior

Si la base vieja todavía tiene la tabla `usuarios_roles` (esquema de Cognito):

1. Sacar un respaldo de la base vieja (con `mysqldump`).
2. Restaurarlo en el contenedor `db` (sección 7).
3. Aplicar la migración:
   ```bash
   docker compose exec -T db sh -c 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD"' < ../../SALUD-DATABASE/migracion_keycloak.sql
   ```

## 9. Problemas frecuentes

| Síntoma | Causa probable |
|---|---|
| `Invalid parameter: redirect_uri` al iniciar sesión | Falta registrar `https://saludumg.online/*` en `salud-web` (sección 6) |
| La app carga, pero todas las llamadas dan `401 token_invalido` | `AUTH_ISSUER` no coincide con el `iss` del token (por ejemplo, la URL de ayer) |
| El backend reinicia en bucle | MySQL todavía no estaba listo, o `DATABASE_URL` tiene caracteres especiales en la contraseña |
| `502 Bad Gateway` en `/api` | El contenedor del backend está caído: `docker compose logs backend` |
| Cambié `.env` pero no se aplica | Usar `docker compose up -d`; un simple `restart` no relee el `.env` |

## Probado

- gunicorn (`--preload --workers 2`) + nginx con esta misma configuración + Login Único + MySQL.
- Login en el navegador a través de nginx: 15/15 (PKCE, token correcto, SSO, logout, 403 de ciudadano, sin API key en el navegador).
- API: 35/35 (`pruebas/prueba_auth.py`).
- Con el Login Único **apagado**, los dos workers siguen validando tokens: 6/6 llamadas con `200`.
- `docker compose config` válido.

Las imágenes Docker no se construyeron en el entorno de prueba; la primera vez en el servidor hay que confirmar que `docker compose up -d --build` termina bien.
