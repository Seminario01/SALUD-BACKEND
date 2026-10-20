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

Al cerrar cada sesión de trabajo, el servidor de respaldo se replica desde producción con
`deploy/replicar.sh` (código, contenedores y datos; ver `deploy/README.md`, sección 10).
El respaldo nunca enciende el túnel de Cloudflare mientras producción esté funcionando.

## Reglas

- Trabajar siempre en la rama `denilson-dev`. Nunca en `main`.
- No unir (merge) nada de las ramas de los compañeros (`jeffry-dev`, `amilcar-dev`, `sandy-dev`) ni de
  `main` hasta nuevo aviso de Antonio: se trabaja solo en `denilson-dev`.
- Explicar en español, paso a paso y simple.
- Al dar comandos de servidor, darlos para pegar en la PC con el `ssh` incluido
  (`ssh denis@IP '...'`), así siempre queda claro en qué servidor corren.
  Con PowerShell 5.1, lo que va dentro del `ssh` se escribe entre comillas simples y sin
  comillas dobles adentro (PowerShell 5.1 las rompe al pasarlas a ssh).
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

`pruebas/ver_token.py` revisa un token del Login Único (emisor, audiencia `rsd-api`, vencimiento
y rol `auditoria:lectura`) y lo prueba contra `/api/indicadores`. Los 401/403 de `auth.py` dicen
exactamente qué falló (`token_audiencia`, `token_otro_emisor`, `token_firma`, `token_expirado`...).

Revisión de librerías con vulnerabilidades conocidas (antes de cada entrega):
`npm audit` en SALUD-FRONTEND y `pip-audit -r requirements.txt` en SALUD-BACKEND
(instalar `pip-audit` en un entorno aparte, no en `venv`). Al 14 oct 2026: 0 en los dos.

En GitHub, `.github/workflows/pruebas.yml` corre todo esto solo en cada push a `denilson-dev`
(MySQL, Keycloak con `keycloak-local/import`, simuladores y datos de SALUD-DATABASE): ver la
pestaña Actions del repo. Si se agrega una prueba que necesita algo nuevo, agregarlo también ahí.

## Validación de datos

Los datos que llegan en el cuerpo se validan con `validacion.py` (`texto`, `cui`, `monto`,
`opcion`, `fecha_pasada`, `telefono`, `booleano`): si no sirven lanzan `DatoInvalido` y
`app.py` responde 400 en JSON. `app.py` también rechaza cuerpos que no son un objeto JSON y
convierte en 400/409 los errores de la base (`DataError`, `IntegrityError`), nunca en 500.
Reglas de negocio: citas solo desde ahora hasta 366 días y sin repetir paciente y hora;
un turno activo por paciente al día; el presupuesto ejecutado no supera al asignado.
Las pruebas crean citas con `futuro(dias, hora)`, nunca con fechas fijas.

## Lotes y vencimientos (Farmacia)

`lotes.py`: una ENTRADA con `fecha_vencimiento` (y `numero_lote` opcional) crea un lote. La
existencia total sigue en `medicamentos.existencia`; lo que no tiene lote es "sin lote" (como
antes). Al despachar se descuenta primero el lote que vence antes y nunca uno vencido; las
vencidas no cuentan como `disponible`. `pruebas/prueba_lotes.py` revisa esa regla sin servidor.

## Alertas para la seguridad del paciente

`alertas_clinicas.py` (sin base de datos; `pruebas/prueba_alertas.py` lo revisa sin servidor):
- **Signos fuera de rango**: las notas de hospitalización y `GET /pacientes/{id}/signos` traen
  `alertas` [{signo, nivel alto|bajo, texto}] con los rangos normales de un adulto (los mismos de las gráficas).
- **Alergias**: `pacientes.alergias` (texto libre). Las cambian Médico, Enfermería y Recepción con
  `PUT /pacientes/{id}/alergias` (permiso `pacientes.alergias`). Al recetar, si un medicamento choca
  (por nombre o familia: penicilinas, sulfas, AINE...), `POST /recetas` responde 409 `alergia`; el
  médico puede reenviar con `confirmar_alergia: true` y la receta queda con `alerta_alergia` para Farmacia.
- **Paciente duplicado**: `GET /pacientes/posibles-duplicados` (mismo CUI, mismo nombre, o nombre parecido
  con la misma fecha de nacimiento). Solo avisa; el registro no se bloquea.
- **Interacciones entre medicamentos**: `interacciones()` revisa los medicamentos de la receta entre sí
  y contra los de las recetas no anuladas del paciente de los últimos 30 días (`DIAS_RECETA_ACTIVA`).
  Grupos por nombre (`GRUPOS`: anticoagulantes, AINE, IECA, ARA II, ISRS...), pares en `INTERACCIONES`
  (grave/moderada) y duplicidad del mismo grupo. Si hay alguna, `POST /recetas` responde 409
  `interaccion` con `interacciones` [{medicamento, con, origen, severidad, texto}]; se reenvía con
  `confirmar_interaccion: true` y la receta queda con `alerta_interaccion`. Es apoyo: no prohíbe.

## Receta verificable con QR

Cada receta tiene `codigo_verificacion` (12 caracteres al azar, `migraciones.codigo_receta`; las
recetas viejas lo reciben al arrancar). La receta impresa trae un QR a `/verificar/<código>` (página
pública del frontend) que consulta `GET /verificar/receta/<código>` **sin token**: número, fecha,
médico, medicamentos y estado (vigente, despachada o anulada); del paciente solo iniciales y los
últimos 4 del DPI. Límite: 30 consultas por minuto por visitante. El número de receta no sirve como código.

## Reporte de diagnósticos

`GET /reportes/diagnosticos` (`routes/reportes.py`, permiso `reportes.ver`: Médico, Jefatura,
Administración y Auditoría): diagnósticos más frecuentes en un período, agrupados sin tildes,
mayúsculas ni el punto final. Solo cifras. Para Auditoría, los de menos de 3 pacientes van en "Otros".

## Bitácora de accesos

`bitacora_accesos.py` (after_request en `app.py`) anota quién vio o modificó datos de pacientes:
cada GET a los datos de UN paciente (ficha, expediente, vacunación, antecedentes, receta, cuenta,
hospitalización; sin repetir lo mismo en 5 minutos) y todo POST/PUT/DELETE que terminó bien.
Lo rechazado (4xx) no se anota. Se consulta en `GET /bitacora/accesos` (permiso `bitacora.ver`,
solo Administración) y en la pantalla `/bitacora` del frontend. Al agregar una ruta nueva que
toque pacientes, poner su descripción en `VER` o `CAMBIOS` de ese archivo.

## Integraciones con otros módulos

- Todas las llamadas salientes pasan por `_llamar` en `services_externos.py` y quedan en
  la bitácora de integraciones (con el motivo del rechazo, datos personales enmascarados).
- `_error_modulo` (`routes/integraciones.py`): **422** si el módulo rechaza la petición,
  **424** si su respuesta no se puede usar, **503** si no está disponible o configurado.
  No usar 502: el proxy lo reemplaza y el mensaje no llega a la pantalla.
- Contratos con cada módulo: `docs/CONTRATOS.md` y `docs/INTEGRACIONES.md`.
