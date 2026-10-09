# Integración con otros módulos — Módulo de Salud

Qué servicios **consume** Salud de Educación, Seguridad y Tributario, cómo se usan desde el frontend y cómo probarlos antes de que los otros equipos publiquen sus servicios.
Los servicios que Salud **expone** a los demás están en Swagger (`/apidocs`) y en `docs/AUTENTICACION.md`.

## 1. Cómo funciona

```
Navegador ──token──> Backend de Salud ──X-API-Key + token del usuario──> Módulo destino
                     (valida el rol)        (servidor a servidor, 3 s máx.)
```

- El frontend **nunca** llama directo a otro módulo ni conoce la API key.
- El backend de Salud envía la **`X-API-Key`** acordada entre equipos y, si hay un usuario, **reenvía su access token** (guía del Login Único, sección 7: todos comparten `aud: rsd-api`).
- Si el otro módulo no está configurado o no responde, Salud responde **503** con un mensaje claro. **Las operaciones propias de Salud no se ven afectadas.**

## 2. Servicios que consume Salud

| Módulo | Servicio (en el módulo destino) | Endpoint de Salud que lo usa | Pantalla | Quién |
|---|---|---|---|---|
| Seguridad | `GET /api/v1/seguridad/ciudadanos/antecedentes/{cui}?nombreCompleto=` (WS-SALUD-08) | `GET /api/v1/salud/pacientes/{id}/antecedentes` | Pacientes → **Consultar** | Personal |
| Educación | `GET /api/v1/educacion/estudiantes/{cui}` | `GET /api/v1/salud/educacion/estudiantes/{cui}` | Vacunación → **Verificar en Educación** | Médico, admin |
| Educación | `POST /api/v1/educacion/jornadas/coordinar` (WS-SALUD-01) | `POST /api/v1/salud/jornadas/coordinar` | (entre módulos) | API key |
| Tributario | `POST /api/v1/integraciones/salud/obligaciones` | `POST /api/v1/salud/citas/{id}/cobro` | Citas → **Enviar cobro** | Caja, Recepción, Admin |
| Tributario | `GET /api/v1/integraciones/salud/obligaciones/{ref}` (por confirmar) | `POST /api/v1/salud/citas/{id}/verificar-pago` | Citas → **Verificar pago** | Caja, Recepción, Admin |
| Los tres | `GET /api/v1/{modulo}/indicadores` (como verificación de conexión) | `GET /api/v1/salud/integraciones/estado` | Dashboard → **Integración con otros módulos** | Personal |

### Datos acordados

**Seguridad (antecedentes).** Salud envía el CUI y el nombre completo. Seguridad responde:
`tieneAntecedentes`, `tipoAntecedente`, `nivelRiesgo`, `requiereCustodia`.
Si Seguridad responde 404, Salud lo interpreta como "sin antecedentes registrados".
El paciente **siempre** se atiende; el resultado solo indica cuidados o custodia adicionales.

**Educación (estudiante).** Salud envía el CUI. Educación responde `establecimiento`, `grado`, `seccion`, `jornada`.
Un 404 significa que no es estudiante.

**Tributario (cobro de citas).**
1. *Enviar cobro* genera `SAL-AAAA-NNNNNN` y registra la obligación (`dpi_persona`, `tipo_obligacion`, `concepto`, `monto`, `moneda`, `fecha_emision`, `fecha_vencimiento`). La cita queda **Por pagar**.
2. El ciudadano ve la referencia y el vencimiento en *Mi resumen* y paga en Tributario.
3. Salud se entera del pago de una de dos formas: con *Verificar pago*, que consulta la obligación, o con el aviso de Tributario a `POST /api/v1/salud/pagos/notificacion` (API key). La cita queda **Pagada** con el número de autorización.

Si la obligación ya existe (`409`), Salud no la duplica. El monto es el `costo` de la cita o, si no tiene, `COSTO_CONSULTA` (Q150).

## 3. Configuración (`.env` del backend)

```
URL_EDUCACION=https://<url-de-educacion>
URL_SEGURIDAD=https://<url-de-seguridad>
URL_TRIBUTARIO=https://<url-de-tributario>
MODULOS_API_KEY=<la clave acordada entre módulos>
COSTO_CONSULTA=150
```

Con una URL vacía, ese módulo aparece como **"No configurado"** en el Dashboard.

## 4. Simuladores, demostración y bitácora

El contrato completo para los otros equipos está en **`docs/CONTRATOS.md`**.

**Simuladores.** `simuladores/app.py` imita Educación, Seguridad y Tributario con las mismas rutas y campos del contrato.
- Sus datos son ficticios (`simuladores/datos.py`) y coherentes con los pacientes de `datos_demo.sql`: los mismos CUI, nombres y edades.
- Todas sus respuestas llevan `"simulado": true`, y la interfaz lo muestra.

| Dónde | Cómo se levantan |
|---|---|
| Servidor (Docker) | Servicio `simuladores` de `deploy/docker-compose.yml`, solo en la red interna. Con `URL_*` vacías en `.env`, el backend los usa |
| Local | `python simuladores/app.py` (puerto 5055) y en el `.env`: `URL_EDUCACION`, `URL_SEGURIDAD` y `URL_TRIBUTARIO` apuntando a `http://localhost:5055` |

| Caso de demostración | Paciente de `datos_demo.sql` |
|---|---|
| Seguridad: riesgo ALTO, requiere custodia | José Antonio Pérez García, Juan Carlos Ixcoy Batz |
| Seguridad: riesgo BAJO | Carlos Enrique Ramírez Solís, Fernando José Barrios Ochoa |
| Educación: estudiante | Ana Lucía Morales, Sofía Gómez, Gabriela Díaz, Diego Méndez, Karla Estrada, Lucía Tzul, Kevin Coyoy |
| Tributario: la obligación sigue pendiente al consultarla | Pedro Pablo Juárez, Rosa Elena Velásquez, Marta Julia Orellana |
| Tributario: la obligación aparece pagada al consultarla | cualquier otro |

Para CUI que no están en el padrón (pacientes nuevos) hay reglas por último dígito:
- Seguridad: si termina en 9, riesgo ALTO; si termina en 7, riesgo BAJO.
- Educación: si termina en número par, es estudiante.
- Tributario: si termina en 3, el pago no está registrado.

**Demostración en las dos direcciones.** En *Integraciones*, admin y médico pueden pedirle a un módulo simulado que **consuma un servicio de Salud**. Lo hace con `POST /api/v1/salud/integraciones/simular/{caso}`, y se ve la petición y la respuesta. Los casos disponibles:

| Caso | Quién consulta | Qué pide |
|---|---|---|
| `seguridad-establecimientos` | Seguridad | WS-SALUD-02 |
| `educacion-jornada` | Educación | WS-SALUD-01; Salud a su vez le consulta a Educación |
| `educacion-practicante` | Educación | WS-SALUD-06 |
| `tributario-costo` | Tributario | Costo de una cita |
| `tributario-pago` | Tributario | Aviso de pago del último cobro pendiente |
| `auditoria-indicadores` | Auditoría | Indicadores agregados |

**Bitácora** (`GET /api/v1/salud/integraciones/bitacora`, solo el personal; tabla `bitacora_integraciones`).
- Registra cada llamada saliente, desde `services_externos.py`, y cada entrante con API key, desde `routes/externos.py`.
- Los CUI se guardan enmascarados.
- No registra las verificaciones de conexión del panel.

**Cuando un equipo publique su servicio real**, solo se pone su URL en el `.env` y se reinicia. El código no cambia.

## 5. Auditoría Social

Auditoría consume indicadores **agregados** de Salud (sin datos personales):

| Endpoint | Con API key | Con token de `auditoria:analista` / `auditoria:admin` |
|---|---|---|
| `GET /api/v1/salud/indicadores` | ✅ | ✅ |
| `GET /api/v1/salud/presupuesto/ejecucion` | ✅ | ✅ |
| `GET /api/v1/salud/panel` | — | ✅ |

Un analista de Auditoría que entra al frontend de Salud ve **solo el panel de indicadores**, en modo lectura. No puede ver pacientes, citas, vacunación ni expedientes (el backend responde 403).

## 6. Pruebas

`pruebas/prueba_auth.py` verifica todo lo anterior (65 pruebas). Las de datos de integración se ejecutan solo si los módulos (o los simuladores) responden.
Probado también con los simuladores **apagados**: la consulta responde 503 en milisegundos con "Seguridad no está disponible", y el resto de Salud sigue funcionando.
