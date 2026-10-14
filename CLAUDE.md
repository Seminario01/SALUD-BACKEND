# Contexto del proyecto para Claude Code — SALUD-BACKEND

Soy Antonio (Denilson), estudiante. Trabajo en el **Módulo Salud** del proyecto
"Red Inteligente de Servicios Digitales" (organización de GitHub `Seminario01`).

- **SALUD-BACKEND** (este repo): Flask + SQLAlchemy + PyMySQL + gunicorn.
- **SALUD-FRONTEND** (repo hermano, en la carpeta de al lado): React 19 + Vite + Tailwind v4.
- Login Único: Keycloak, realm `rsd`.

## Metodología de trabajo

1. Los cambios se hacen en local (en la PC de Antonio).
2. Se suben a GitHub, a la rama `denilson-dev`.
3. Antonio entra al servidor por SSH y ahí hace `git pull` de esa rama.
4. Se vuelve a levantar con docker compose en `~/proyecto-salud/SALUD-BACKEND/deploy`.

Nunca se edita código directamente en el servidor; todo pasa por git.

## Reglas

- Trabajar siempre en la rama `denilson-dev`. Nunca en `main`.
- No unir (merge) nada de las ramas de los compañeros (`jeffry-dev`, `amilcar-dev`, `sandy-dev`) ni de
  `main` hasta nuevo aviso de Antonio: se trabaja solo en `denilson-dev`.
- Explicar en español, paso a paso y simple.
- Al dar comandos, decir siempre dónde van: en la PC o en el servidor (por SSH).
  Cada comando debe empezar con `cd` a su carpeta, por ejemplo:
  `cd ~/proyecto-salud/SALUD-BACKEND/deploy && docker compose ps`
- Nunca poner API keys ni contraseñas en el código, commits ni documentos
  (van solo en `deploy/.env` del servidor, que no se sube).
- No tocar los contenedores `tesis-*` (son de otro proyecto que corre en el mismo servidor).

## Actualizar el servidor (por SSH)

El compose de `deploy/` construye también el frontend desde `../../SALUD-FRONTEND`,
así que se actualizan los dos repos y se levanta una sola vez:

```bash
cd ~/proyecto-salud/SALUD-BACKEND && git pull origin denilson-dev
cd ~/proyecto-salud/SALUD-FRONTEND && git pull origin denilson-dev
cd ~/proyecto-salud/SALUD-BACKEND/deploy && docker compose up -d --build
cd ~/proyecto-salud/SALUD-BACKEND/deploy && docker compose ps
```

Más detalle (respaldos, cambio de `AUTH_ISSUER`, problemas comunes) en `deploy/README.md`.

## Pruebas

`pruebas/prueba_auth.py` y `pruebas/prueba_permisos.py` no son pytest: son scripts que
llaman al backend ya corriendo. Necesitan tres cosas levantadas en la PC:

- Keycloak local en el puerto 8081. En esta PC no hay Docker; se usa la copia de
  `C:\Denis\keycloak-26.4.0` con `bin/kc.bat start-dev --http-port 8081`.
- Simuladores de los otros módulos: `venv/Scripts/python.exe simuladores/app.py` (puerto 5055).
- Backend en el puerto 5050, con el `.env` local (MySQL local, base `salud_db`).

Las dos pruebas dependen de los datos de la base local: sin camas, sin turnos activos o
con recetas de un solo paciente, fallan aunque el código esté bien. Para tenerlos se cargan
`datos_demo.sql` y luego `demo_turnos_hoy.sql` del repo SALUD-DATABASE (no borran nada y se
pueden correr varias veces; los turnos solo valen para el día en que se cargan).
En `cmd` de Windows las rutas son `C:\Denis\...`, no `/c/Denis/...`.

`pruebas/prueba_qa.py` ataca todos los endpoints de escritura con datos basura (null, tipos
equivocados, textos enormes, SQL, tokens falsos) y falla si alguno responde 500 o HTML.
Solo en la PC: copia la base local antes y la restaura al final.

## Validación de datos

Los datos que llegan en el cuerpo se validan con `validacion.py` (`texto`, `cui`, `monto`,
`opcion`, `fecha_pasada`, `telefono`, `booleano`): si no sirven lanzan `DatoInvalido` y
`app.py` responde 400 en JSON. `app.py` también rechaza cuerpos que no son un objeto JSON y
convierte en 400/409 los errores de la base (`DataError`, `IntegrityError`), nunca en 500.
Reglas de negocio: citas solo desde ahora hasta 366 días y sin repetir paciente y hora;
un turno activo por paciente al día; el presupuesto ejecutado no supera al asignado.
Las pruebas crean citas con `futuro(dias, hora)`, nunca con fechas fijas.

## Integraciones con otros módulos

- Todas las llamadas salientes pasan por `_llamar` en `services_externos.py` y quedan en
  la bitácora de integraciones (con el motivo del rechazo, datos personales enmascarados).
- `_error_modulo` (`routes/integraciones.py`): **422** si el módulo rechaza la petición,
  **424** si su respuesta no se puede usar, **503** si no está disponible o configurado.
  No usar 502: el proxy lo reemplaza y el mensaje no llega a la pantalla.
- Contratos con cada módulo: `docs/CONTRATOS.md` y `docs/INTEGRACIONES.md`.
