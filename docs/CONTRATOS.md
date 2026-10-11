# Contratos de integración — Módulo de Salud

Este documento es para los equipos de **Educación, Seguridad, Tributario y Auditoría Social**. Dice:

- qué servicios **les consume** Salud: qué enviamos y qué esperamos de respuesta;
- qué servicios **les ofrece** Salud: qué nos pueden pedir y qué respondemos.

Si su módulo implementa estas rutas y campos, la integración funciona sin cambiar nada en Salud: solo se pone su URL en nuestra configuración.

Mientras tanto, Salud usa **simuladores** construidos a partir de este mismo contrato (`simuladores/app.py`). Responden con datos ficticios y se identifican con `"simulado": true`.

---

## 1. Reglas comunes

| Tema | Acuerdo |
|---|---|
| Autenticación entre servidores | Header `X-API-Key: <clave acordada entre módulos>` |
| Usuario final | Si la petición viene de un usuario, se reenvía su token: `Authorization: Bearer <token>`. Lo emite el Login Único, realm `rsd`, `aud: rsd-api` |
| Identificar al módulo que llama | Header opcional `X-Modulo-Origen: Seguridad` (o `Educación`, `Tributario`, `Auditoría`) |
| Formato de respuesta | JSON `{"success": true, "data": {...}}` o `{"success": false, "error": "<codigo>", "message": "..."}` |
| Persona | Se identifica por **CUI/DPI** (13 dígitos) |
| Códigos HTTP | `200` ok · `400` datos incompletos · `401` sin credenciales · `403` credencial inválida o sin permiso · `404` no existe · `5xx` error del servidor |
| Tiempo de espera | Salud espera **3 segundos** como máximo. Si no hay respuesta, informa "módulo no disponible" y sigue funcionando |
| Fechas | ISO 8601 (`2026-10-15`, `2026-10-15T09:30`), hora de Guatemala |

---

## 2. Servicios que Salud CONSUME (los implementa el otro módulo)

### Seguridad

**WS-SALUD-08: Antecedentes de una persona.** Se usa antes de atender a un paciente, para saber si requiere custodia. **El paciente se atiende siempre.**

```
GET /api/v1/seguridad/ciudadanos/antecedentes/{cui}?nombreCompleto=José Antonio Pérez García
```
```json
{ "success": true, "data": {
    "cui": "2501234560109",
    "tieneAntecedentes": true,
    "tipoAntecedente": "Robo agravado",
    "nivelRiesgo": "ALTO",
    "requiereCustodia": true } }
```

- `nivelRiesgo` puede ser `NINGUNO`, `BAJO`, `MEDIO` o `ALTO`.
- Un `404` se interpreta como "sin antecedentes registrados".

**Alertas activas.** Opcional; sirve como contexto para emergencias.

```
GET /api/v1/seguridad/alertas?zona=Antigua Guatemala
```
Responde una lista de alertas, cada una con `id`, `tipo`, `zona`, `departamento`, `nivel`, `descripcion` y `estado`.

### Educación

**Estudiante por CUI.** Se usa en vacunación escolar.

```
GET /api/v1/educacion/estudiantes/{cui}
```
```json
{ "success": true, "data": {
    "cui": "2504567890106", "nombreCompleto": "Sofía Alejandra Gómez Ruiz",
    "establecimiento": "INEB Jornada Matutina, Antigua Guatemala",
    "grado": "3ro. Básico", "seccion": "A", "jornada": "Matutina" } }
```
Un `404` significa que no es estudiante.

**WS-SALUD-01: Estudiantes convocados a una jornada de vacunación.**

```
POST /api/v1/educacion/jornadas/coordinar
{ "tipo_jornada": "Vacunación Td y VPH", "lugar": "INEB Jornada Matutina, Antigua Guatemala",
  "fecha": "2026-10-09", "hora": "08:00" }
```
Responde una lista de estudiantes, cada uno con `cui`, `nombreCompleto`, `establecimiento`, `grado`, `seccion` y `jornada`.

**WS-SALUD-07: Validar practicante.**

```
GET /api/v1/educacion/practicantes/validar/{cui}
```
Responde `esPracticante`, `universidad`, `carrera`, `nivel` y `estado`. Un `404` significa que no es practicante.

### Tributario

Tributario es un servidor externo real (no un módulo hermano como Educación o Seguridad), con su **propia API key** (`TRIBUTARIO_API_KEY`, distinta de `MODULOS_API_KEY`) y enviando siempre `X-Modulo-Origen: salud`.

**WS-SALUD-09: Registrar la obligación de pago de una cita.** El número de referencia lo genera Salud con el formato `SAL-AAAA-NNNNNN` (NNNNNN es el id de la cita, con ceros a la izquierda: la misma cita siempre produce la misma referencia).

```
POST /api/v1/integraciones/salud/obligaciones
{ "numero_referencia": "SAL-2026-000120", "dpi_persona": "1234567890101",
  "tipo_obligacion": "CONSULTA_MEDICA", "concepto": "Consulta médica general",
  "monto": 150.00, "moneda": "GTQ", "fecha_emision": "2026-10-08", "fecha_vencimiento": "2026-10-23" }
```
Respuesta esperada (`201` al registrar por primera vez; `200` si se reenvían los mismos datos; `409` si la referencia se repite con datos distintos):
```json
{ "success": true, "data": {
    "numero_referencia": "SAL-2026-000120", "referencia_tributario": "REF-TRIB-000045",
    "estado": "PENDIENTE" } }
```
- `tipo_obligacion` solo usa `CONSULTA_MEDICA` por ahora; `EMERGENCIA` y `ESPECIALIDAD` están propuestos, pendientes de confirmar con Tributario.
- El estado `PENDIENTE` **no** marca la cita como pagada en Salud: solo confirma que Tributario registró la obligación. El pago se confirma por separado (ver abajo).

**Confirmación de pago (Tributario → Salud).** Cuando el pago se concreta, Tributario llama a Salud:

```
POST https://<url-de-salud>/api/v1/salud/pagos/confirmacion
Headers: X-API-Key: <acordada>, Idempotency-Key: <evento_id> (o enviarlo en el body)
{ "evento_id": "EVT-2026-000982",
  "data": {
    "numero_referencia": "SAL-2026-000120", "referencia_tributario": "REF-TRIB-000045",
    "estado_pago": "APROBADO", "numero_autorizacion": "AUT-C578AB9FF9",
    "monto_pagado": 150.00, "fecha_pago": "2026-10-10T14:32:00" } }
```
```json
{ "success": true, "data": { "cita_id": 120, "pago_confirmado": true } }
```
- `evento_id` (o el header `Idempotency-Key`) hace la llamada idempotente: reenviar el mismo evento responde `200` sin volver a procesar.
- Valores de `estado`/`estado_pago` que Salud interpreta como pagado: `APROBADO`, `PAGADO`, `PAGADO_COMPLETO`, `CONFIRMADO` (pendiente de confirmar con Tributario los valores exactos). Cualquier otro valor se trata como **no pagado**.
- `404` si `numero_referencia` no corresponde a ninguna cita; `409` si `monto_pagado` no coincide con el costo de la cita; `400` si faltan datos o el monto/fecha no tienen formato válido.

### Verificación de conexión (los tres módulos)

```
GET /api/v1/{educacion|seguridad|tributario}/indicadores
```
Cualquier respuesta `200` sirve: Salud solo la usa para mostrar "Conectado" y algunos números generales.

---

## 3. Servicios que Salud OFRECE (los consumen los otros módulos)

URL base: `https://saludumg.online/api/v1/salud`. Todos requieren `X-API-Key`. La documentación interactiva está en Swagger, en `/apidocs`.

| Servicio | Quién lo usa | Petición | Respuesta |
|---|---|---|---|
| **WS-SALUD-01** Coordinar jornada de vacunación | Educación | `POST /jornadas/coordinar` con `tipo_jornada`, `lugar`, `fecha`, `hora` | Lista de estudiantes convocados. Salud se la pide a Educación |
| **WS-SALUD-02** Establecimientos disponibles | Seguridad | `GET /establecimientos/disponibilidad?departamento=&municipio=&tipoAtencion=&nivelUrgencia=` | `disponible`, `mensaje` y `establecimientos[]` con `nombreEstablecimiento`, `tipoEstablecimiento`, `direccion`, `telefono`, `estadoServicio` y `tipoAtencionDisponible` |
| **WS-SALUD-06** Horas de práctica | Educación | `GET /practicantes/{cui}/horas` | `horasAcumuladas`, `fechaInicio`, `fechaFin`, `supervisor`, `estado` |
| Costo de una cita | Tributario | `GET /citas/{id}/costo` | `cita_id`, `monto`, `pago_confirmado` |
| Confirmación de pago | Tributario | `POST /pagos/confirmacion` con `evento_id` y `data` (ver sección 2) | `cita_id`, `pago_confirmado` |
| Indicadores agregados | Auditoría Social | `GET /indicadores` (con API key, o con token de rol `auditoria:*`) | Totales de pacientes, citas, recursos, turnos, vacunación y presupuesto. **Sin datos personales** |
| Ejecución presupuestaria | Auditoría Social | `GET /presupuesto/ejecucion` | Periodo vigente: `monto_asignado`, `monto_ejecutado_servicio_social`, `porcentaje_ejecutado` |

Ejemplo, desde el servidor de Seguridad:

```bash
curl -H "X-API-Key: $CLAVE" -H "X-Modulo-Origen: Seguridad" \
  "https://saludumg.online/api/v1/salud/establecimientos/disponibilidad?departamento=Sacatepéquez&tipoAtencion=EMERGENCIA"
```

---

## 4. Trazabilidad

Salud registra en su **bitácora de integraciones** cada llamada en las dos direcciones: fecha, módulo, operación, resultado, duración y si fue simulada. Se puede ver en la pantalla *Integraciones*.

Los CUI se guardan enmascarados (`*********0109`). Así Auditoría y la ingeniera pueden verificar que el intercambio ocurre.

## 5. Para conectar un módulo real

1. El equipo comparte su URL base y confirma la `X-API-Key`.
2. En el servidor de Salud, en `SALUD-BACKEND/deploy/.env`, se pone `URL_SEGURIDAD=https://...` (o `URL_EDUCACION`, `URL_TRIBUTARIO`).
3. Se corre `docker compose up -d`. En *Integraciones*, ese módulo pasa de **Simulado** a **Servicio real**.
4. Si alguna ruta o campo es distinto a este contrato, se ajusta en `services_externos.py` y se actualiza este documento.
