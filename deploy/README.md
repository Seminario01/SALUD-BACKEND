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
mkdir -p ~/proyecto-salud && cd ~/proyecto-salud
git clone -b denilson-dev https://github.com/Seminario01/SALUD-BACKEND.git
git clone -b denilson-dev https://github.com/Seminario01/SALUD-FRONTEND.git
git clone -b denilson-dev https://github.com/Seminario01/SALUD-DATABASE.git
```

Cuando los PR se fusionen, usen `main` en lugar de `denilson-dev`.

## 3. Configurar

```bash
cd ~/proyecto-salud/SALUD-BACKEND/deploy
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

(Si los turnos demo de ese día ya están, no hace nada; si alguien ya generó turnos, numera después de ellos.)

**Integración con otros módulos (simuladores):** el servicio `simuladores` del compose imita a Educación, Seguridad y Tributario con datos ficticios (ver `docs/INTEGRACIONES.md` y `docs/CONTRATOS.md`). Con `URL_EDUCACION`, `URL_SEGURIDAD` y `URL_TRIBUTARIO` vacías en `.env`, el backend los usa. Cuando un equipo publique su servicio, se pone su URL en `.env` y se corre `docker compose up -d`.

Comprobación local en el servidor:

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8080/                       # 200
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8080/api/v1/salud/pacientes # 401 (correcto: sin token)
curl -s http://127.0.0.1:8080/config.js                                               # debe mostrar el AUTH_URL
```

## 5. Túnel de Cloudflare

El túnel corre como un servicio más del compose (`tunel`), con `restart: unless-stopped`: si el
servidor se reinicia, vuelve solo junto con los demás contenedores. Usa la configuración y las
credenciales de `~/.cloudflared` (túnel con nombre `salud-demo`) y la red del servidor, así que
`localhost:80` del `config.yml` es el frontend:

```yaml
ingress:
  - hostname: saludumg.online
    service: http://localhost:80        # el mismo puerto que PUERTO_WEB
  - service: http_status:404
```

**Solo en producción** se enciende, con esta línea en `deploy/.env`:

```
COMPOSE_PROFILES=tunel
```

El servidor de respaldo nunca la lleva, y `replicar.sh` la anula de todos modos: si dos servidores
atienden el mismo túnel, Cloudflare reparte las visitas entre los dos y los datos quedan divididos.

Revisar el túnel: `docker compose logs tunel --tail 20` (debe decir `Registered tunnel connection`).

## 6. Login Único en producción (pedir a la ingeniera)

Para que el login funcione en `https://saludumg.online`, el client `salud-web` debe tener registrados:

- Redirect URI: `https://saludumg.online/*`
- Web origin: `https://saludumg.online`

Sin eso, el Login Único responde `Invalid parameter: redirect_uri`.

## 7. Operación diaria

**Cambió la URL del día del Login Único:**

```bash
cd ~/proyecto-salud/SALUD-BACKEND/deploy
nano .env                  # actualizar AUTH_ISSUER
docker compose up -d       # recrea backend y frontend con la nueva URL (sin recompilar)
```

**Actualizar a la última versión del código:**

```bash
cd ~/proyecto-salud/SALUD-BACKEND && git pull origin denilson-dev
cd ~/proyecto-salud/SALUD-FRONTEND && git pull origin denilson-dev
cd ~/proyecto-salud/SALUD-BACKEND/deploy && docker compose up -d --build
```

**Respaldo de las bases de datos** (Salud y el Keycloak local), con `deploy/respaldo.sh`:

```bash
bash ~/proyecto-salud/SALUD-BACKEND/deploy/respaldo.sh      # a mano
crontab -e                                                  # automático, todos los días a las 3:15
# agregar la línea:
15 3 * * * bash $HOME/proyecto-salud/SALUD-BACKEND/deploy/respaldo.sh >> $HOME/respaldos-salud/respaldo.log 2>&1
```

Se guardan en `~/respaldos-salud` y se conservan los últimos 7 días. Para ver si ya está programado: `crontab -l` (debe salir la línea de `respaldo.sh`).

**Copia fuera del servidor** (en la PC, PowerShell). Si el disco del servidor falla, los respaldos de `~/respaldos-salud` se pierden con él; `deploy/copiar_respaldos.ps1` trae una copia a la PC (`%USERPROFILE%\Respaldos-Salud`, últimos 30 días, registro en `copias.log`).

1. Llave SSH, una sola vez, para que la copia no pida contraseña (Enter en todas las preguntas):
   ```powershell
   ssh-keygen -t ed25519
   type $env:USERPROFILE\.ssh\id_ed25519.pub | ssh USUARIO@IP_DEL_SERVIDOR "mkdir -p ~/.ssh && cat >> ~/.ssh/authorized_keys"
   ```
   La llave privada (`id_ed25519`, sin `.pub`) da acceso al servidor: no se comparte ni se sube a git.
2. Probar la copia a mano:
   ```powershell
   powershell -ExecutionPolicy Bypass -File C:\Denis\SALUD-BACKEND\deploy\copiar_respaldos.ps1 -Servidor USUARIO@IP_DEL_SERVIDOR
   ```
3. Programarla todos los días a las 9:00 (solo corre si la PC está encendida a esa hora):
   ```powershell
   schtasks /Create /SC DAILY /ST 09:00 /TN "Copiar respaldos Salud" /TR "powershell -NoProfile -ExecutionPolicy Bypass -File C:\Denis\SALUD-BACKEND\deploy\copiar_respaldos.ps1 -Servidor USUARIO@IP_DEL_SERVIDOR"
   ```

**Restaurar** (desde `SALUD-BACKEND/deploy`; reemplaza los datos actuales):

```bash
gunzip -c ~/respaldos-salud/salud_db_AAAA-MM-DD_HHMM.sql.gz | docker compose exec -T db sh -c 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD"'
gunzip -c ~/respaldos-salud/keycloak_AAAA-MM-DD_HHMM.sql.gz | docker exec -i rsd-postgres-local psql -U keycloak -d keycloak
```

(Para Keycloak, detener antes el contenedor `rsd-keycloak-local` y restaurar sobre una base vacía.)

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

## 10. Servidor de respaldo (réplica en frío)

Flujo de trabajo: **PC → GitHub → producción (Latitude) → al cerrar la sesión, respaldo**.
El respaldo tiene el mismo código y una copia de los datos del último cierre, pero **no tiene
el túnel de Cloudflare encendido**: si dos servidores atienden el mismo túnel, Cloudflare reparte
las visitas entre los dos y los datos quedan divididos.

**Preparar el respaldo (una sola vez).** Todo se corre desde la PC; cada comando lleva su `ssh`:

1. Llave de la PC en los dos servidores (pide la contraseña de cada uno una vez):
   ```powershell
   Get-Content "$env:USERPROFILE\.ssh\id_ed25519.pub" | ssh denis@IP_PRODUCCION "mkdir -p ~/.ssh && cat >> ~/.ssh/authorized_keys"
   Get-Content "$env:USERPROFILE\.ssh\id_ed25519.pub" | ssh denis@IP_RESPALDO "mkdir -p ~/.ssh && cat >> ~/.ssh/authorized_keys"
   ```
2. En el respaldo: clonar los tres repos (sección 2) y copiar el `.env` de producción. El `.env`
   pasa de un servidor al otro a través de la PC, sin guardarse en ella:
   ```powershell
   scp denis@IP_PRODUCCION:proyecto-salud/SALUD-BACKEND/deploy/.env denis@IP_RESPALDO:proyecto-salud/SALUD-BACKEND/deploy/.env
   ```
3. Llave del respaldo hacia producción, para que `replicar.sh` traiga los datos sin contraseña.

**Replicar (al cerrar cada sesión de trabajo):**

```powershell
ssh denis@IP_RESPALDO 'bash ~/proyecto-salud/SALUD-BACKEND/deploy/replicar.sh denis@IP_PRODUCCION'
```

Actualiza el código, levanta los contenedores, trae un respaldo nuevo de producción, lo restaura
y al final compara cuántos pacientes y citas hay en cada servidor (deben coincidir). Las copias
quedan en `~/respaldos-de-produccion` del respaldo (últimos 30 días).

Copia la **misma versión que corre en producción** (no lo último de GitHub), así el respaldo
nunca va adelantado. También corre sola todos los días a las 3:45, después del respaldo de
producción de las 3:15 (registro en `~/respaldos-de-produccion/replica.log`). En los dos
servidores conviven otros proyectos (`tesis-*`): la réplica solo toca los contenedores `salud-*`
y la tarea programada solo agrega su línea.

### Si producción falla: el respaldo toma el control

El respaldo ya tiene una copia de `~/.cloudflared` (credenciales del túnel, permisos 600) y el
túnel definido en el compose, apagado. Todo se corre desde la PC:

1. Apagar el túnel de producción, si todavía responde. Si producción está caída, saltar este paso:
   ```powershell
   ssh denis@IP_PRODUCCION 'cd ~/proyecto-salud/SALUD-BACKEND/deploy && docker compose stop tunel'
   ```
2. En el respaldo: quitar la réplica de la madrugada (si no, cuando producción vuelva, sus datos
   viejos sobrescribirían los nuevos) y encender el túnel:
   ```powershell
   ssh denis@IP_RESPALDO 'crontab -l | grep -v replicar.sh | crontab - ; cd ~/proyecto-salud/SALUD-BACKEND/deploy && COMPOSE_PROFILES=tunel docker compose up -d tunel && sleep 15 && docker compose logs tunel | grep -c Registered'
   ```
   Debe salir un número mayor que 0. Desde ese momento `saludumg.online` lo atiende el respaldo,
   con los datos de la última réplica.

**Volver a producción** es el camino inverso, pero con los datos en sentido contrario: los nuevos
están en el respaldo. Primero se copian del respaldo a producción, después se apaga el túnel del
respaldo, se enciende el de producción y por último se vuelve a programar la réplica. Hacerlo con
calma y con un respaldo de los dos lados antes de empezar.

## Probado

- gunicorn (`--preload --workers 2`) + nginx con esta misma configuración + Login Único + MySQL.
- Login en el navegador a través de nginx: 15/15 (PKCE, token correcto, SSO, logout, 403 de ciudadano, sin API key en el navegador).
- API: 35/35 (`pruebas/prueba_auth.py`).
- Con el Login Único **apagado**, los dos workers siguen validando tokens: 6/6 llamadas con `200`.
- `docker compose config` válido.

Las imágenes Docker no se construyeron en el entorno de prueba; la primera vez en el servidor hay que confirmar que `docker compose up -d --build` termina bien.
