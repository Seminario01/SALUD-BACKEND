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

## Datos de demostración

`deploy/cargar_demo.sh` carga de SALUD-DATABASE `datos_demo.sql` (bloques que se completan solos) y
`demo_poblacion.sql` (826 pacientes ficticios de los 22 departamentos, generado por
`generar_demo_poblacion.py` con semilla fija: dosis por peso en niños, alergias respetadas, crecimiento con
las curvas OMS; solo dos brotes planeados, Escuintla y Cobán). Las fechas son relativas al día de carga,
así que envejecen: `cargar_demo.sh --hoy` corre `demo_refrescar_fechas.sql` (mueve cada bloque los días que
pasaron, medido con un dato ancla de fecha conocida; solo datos demo, nunca bitácoras ni cobros enviados a
Tributario) y carga los turnos de hoy. Correrlo el día de la presentación. Si se agrega un bloque demo
nuevo con fechas relativas, agregarle su ancla en `demo_refrescar_fechas.sql`.

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

## Constancias de consulta e incapacidad

`routes/constancias.py` (tabla `constancias_medicas`): el médico emite (`constancias.emitir`) una
CONSULTA o una INCAPACIDAD (1 a 60 días de reposo, `hasta` = desde + días - 1). El diagnóstico solo
se guarda si el médico decide imprimirlo. Se ven con `constancias.ver` (Médico, Enfermería, Jefatura,
Administración) o el ciudadano las suyas; se anulan con motivo (el médico las suyas, Jefatura cualquiera).
Igual que las recetas llevan `codigo_verificacion` y QR a `/verificar/constancia/<código>`, que consulta
`GET /verificar/constancia/<código>` sin token y **sin diagnóstico**.

## Lista de espera de citas

`routes/lista_espera.py` (tabla `lista_espera_citas`): con `citas.gestionar` se agrega a un paciente
(uno activo por paciente) con motivo y preferencia; se ve con `citas.ver`, primero el que lleva más
tiempo. Estados ESPERANDO -> AVISADO -> AGENDADO (con una `cita_id` del mismo paciente) o CANCELADA.
Al cancelar una cita, `DELETE /citas/{id}` devuelve `en_lista_espera` (cuántos esperan un espacio).

## Triage en la cola de turnos

`routes/turnos.py` `TRIAGE`: 5 niveles (ROJO inmediato, NARANJA 10 min, AMARILLO 60, VERDE 120,
AZUL 240). Clasifican Enfermería y Médico (`turnos.clasificar`) con `PUT /turnos/{id}/triage` o al
generar el turno. La cola (`/turnos/activos`) se ordena por nivel y luego por llegada (sin clasificar:
urgente entre naranja y amarillo, normal como verde); el personal ve motivo, espera y si `excede` el
tiempo recomendado. La pantalla pública solo ve el color.

## Laboratorio clínico

`laboratorio.py` (sin base de datos; `pruebas/prueba_laboratorio.py`): catálogo de exámenes
(hematología, química, orina y heces, inmunología) con parámetros numéricos (unidad, rango normal de
un adulto y límites de lo posible para rechazar errores de digitación) o cualitativos (opciones y
cuáles son normales); `interpretar()` da normal, alto, bajo o anormal. `routes/laboratorio.py`:
el médico ordena (`laboratorio.ordenar`), Enfermería toma la muestra y registra resultados
(`laboratorio.procesar`; no hay puesto "Laboratorio" en el Login Único), PENDIENTE -> EN_PROCESO
-> COMPLETADA (ya no se edita) o ANULADA. Resultados en JSON por examen. El ciudadano ve sus órdenes
y los resultados solo cuando están completos.

## Residencia y vigilancia epidemiológica

`ubicaciones.py` + `datos/municipios_gt.json`: 22 departamentos y 340 municipios con el código del
INE (el mismo de los últimos 4 dígitos del DPI, que es el lugar de inscripción, no de residencia).
Fuente: límites de CONRED/OCHA (HDX `cod-ab-gtm`, CC BY-IGO); el frontend dibuja el mapa con
`public/mapas/guatemala.geojson` (simplificado del mismo archivo). `pacientes.municipio` (4 dígitos)
y `pacientes.zona` (texto) se validan contra el catálogo; los lagos (`..00`) no son residencia.
`routes/vigilancia.py`: `GET /vigilancia/casos` (permiso `vigilancia.ver`, solo cifras) cuenta
atenciones con CIE-10 por municipio de residencia, con filtros (período, grupo de `GRUPOS`, código,
departamento, sexo, edad), tendencia semanal, tabla municipio × grupo y alertas de posible brote
(últimos 7 días >= 3 casos y más del doble del promedio semanal de las 4 semanas anteriores). Sin
`vigilancia.pacientes` los municipios con menos de 3 pacientes salen como `pocos`.
`GET /vigilancia/pacientes?municipio=` (Médico y Jefatura) da quiénes son y queda en la bitácora.

## Crecimiento infantil (OMS, 0 a 5 años)

`crecimiento.py` + `datos/oms_crecimiento.json`: L, M y S de las tablas ampliadas oficiales de la OMS
(Patrones de Crecimiento Infantil 2006; peso/edad y talla/edad por día hasta 1856 días, peso/longitud
45-110 cm y peso/talla 65-120 cm por cada 0.1 cm). Puntuación z por el método LMS con el ajuste de la
OMS más allá de ±3 DE en los indicadores de peso; se comparó contra TODAS las columnas -4..+4 DE de
la OMS y coincide. Antes de 2 años se usa peso para la longitud; después, peso para la talla.
Clasificación con los puntos de corte de la OMS (desnutrición crónica, aguda, bajo peso, sobrepeso).
`routes/crecimiento.py`: `GET/POST /pacientes/{id}/crecimiento` (registran Médico y Enfermería,
`crecimiento.registrar`; ven quienes tienen `expediente.ver` o el ciudadano dueño), `DELETE .../{mid}`.
`pruebas/prueba_crecimiento.py` lo revisa sin servidor.

## Reporte de diagnósticos

`GET /reportes/diagnosticos` (`routes/reportes.py`, permiso `reportes.ver`: Médico, Jefatura,
Administración y Auditoría): diagnósticos más frecuentes en un período, agrupados sin tildes,
mayúsculas ni el punto final. Solo cifras. Para Auditoría, los de menos de 3 pacientes van en "Otros".
Las atenciones con código CIE-10 se agrupan por el código ("J00 · Rinofaringitis aguda...").

## Catálogo CIE-10

`cie10.py`: ~260 diagnósticos frecuentes (no la CIE-10 completa) con capítulo y sinónimos de uso
común ("gripe", "ivu", "presión alta"); `pruebas/prueba_cie10.py` lo revisa sin servidor.
`GET /cie10?q=` busca por código o palabras (Médico, Enfermería, Jefatura, Administración, Auditoría).
`POST /expedientes/{id}/atenciones` acepta `codigo_cie10` (solo códigos del catálogo; si no se escribe
diagnóstico, se usa su nombre oficial) y queda en `expedientes_clinicos.codigo_cie10`.

## Puestos asignados en Salud

`routes/puestos.py` (permiso `puestos.asignar`, solo Administración): da un puesto de Salud (`salud:*`) a
una cuenta del Login Único por su `sub` (el código que muestra "Mi resumen"; nunca por correo o usuario,
que se pueden cambiar allá). Tabla `puestos_asignados`; `auth.validar_token` los suma a los roles del token
(`g.usuario["roles"]`; los del token quedan en `roles_token` y los asignados en `asignados`), leídos en
cada petición (sin memoria: con varios procesos, quitar un puesto vale al instante). Solo vale en Salud. Nadie puede asignarse ni quitarse su
propio puesto; cada cambio queda en la bitácora ("Asignó el puesto Jefatura médica a ...").
`usuarios_recientes` guarda a quien entra (cualquier cuenta) para listar "Entraron sin puesto".
`GET /mis-permisos` devuelve `asignados`, que el frontend suma al menú.

## Panel de Auditoría Social

`auditoria_registro.py` (before/after_request en `app.py`) anota en la bitácora de integraciones
(entrante, módulo Auditoría) CADA consulta a los servicios para Auditoría (`/indicadores`,
`/presupuesto/ejecucion`, `/auditoria/indicadores` y sus alias), también las rechazadas: qué credencial
mandó ("token de X", "clave de Y", "sin clave ni token") y el motivo. Las de `routes/externos.py` con
X-API-Key ya las anota ese archivo. `routes/auditoria_panel.py` (permiso `integraciones.ver`):
`GET /integraciones/auditoria` (servicios, configuración del token, última consulta exitosa real,
rechazos de 7 días agrupados con su explicación en `MOTIVOS`) y `POST /integraciones/auditoria/probar`
(indicadores con la clave de Auditoría o la común, cálculo del tablero del mes y llaves del Login
Único; queda marcado como prueba y no cuenta como consulta real).

## Red de establecimientos y referencias

`establecimientos.py` + `datos/red_hospitalaria.json`: los 45 hospitales públicos del MSPAS (portal
Establecimientos de Salud, estado Funcionando, consultado el 23/10/2026; cubre los 22 departamentos). Al
arrancar se agregan los que falten y se completa municipio (INE), nivel y fuente, sin pisar lo que
Administración editó. El portal no publica dirección ni teléfono: quedan vacíos. `routes/red.py`:
`GET /establecimientos` (personal), `POST/PUT /establecimientos` (`establecimientos.gestionar`, Administración);
referencias `GET/POST /referencias`, `PUT /referencias/{id}` (RECIBIDA o CANCELADA con motivo) y
`GET /pacientes/{id}/referencias`. Refiere el Médico (`referencias.crear`); las cierran Médico, Enfermería o
Jefatura (`referencias.gestionar`); las ven también Recepción y Administración; el ciudadano las suyas. No se
refiere a un establecimiento inactivo. WS-SALUD-02 (Seguridad) usa la misma tabla: solo los ACTIVOS, con `nivel`
y `codigoMunicipio`.

## Bitácora de accesos

`bitacora_accesos.py` (after_request en `app.py`) anota quién vio o modificó datos de pacientes:
cada GET a los datos de UN paciente (ficha, expediente, vacunación, antecedentes, receta, cuenta,
hospitalización; sin repetir lo mismo en 5 minutos) y todo POST/PUT/DELETE que terminó bien.
Lo rechazado (4xx) no se anota. Se consulta en `GET /bitacora/accesos` (permiso `bitacora.ver`,
solo Administración) y en la pantalla `/bitacora` del frontend. Al agregar una ruta nueva que
toque pacientes, poner su descripción en `VER` o `CAMBIOS` de ese archivo.

`GET /bitacora/inusuales` (mismo permiso, `routes/accesos.py`) revisa los últimos `dias` (sin
ciudadanos) y avisa de: muchos pacientes distintos vistos en una hora, muchas anulaciones en un día
(nivel alto), accesos de noche (22:00 a 6:00) de Recepción, Caja, Administración o Jefatura, y muchas
IP en un día (nivel medio). Los umbrales se pueden cambiar por parámetro. Solo avisa; no bloquea.

## Integraciones con otros módulos

- Todas las llamadas salientes pasan por `_llamar` en `services_externos.py` y quedan en
  la bitácora de integraciones (con el motivo del rechazo, datos personales enmascarados).
- `_error_modulo` (`routes/integraciones.py`): **422** si el módulo rechaza la petición,
  **424** si su respuesta no se puede usar, **503** si no está disponible o configurado.
  No usar 502: el proxy lo reemplaza y el mensaje no llega a la pantalla.
- Contratos con cada módulo: `docs/CONTRATOS.md` y `docs/INTEGRACIONES.md`.
