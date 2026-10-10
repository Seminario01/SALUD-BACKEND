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
| Autenticación entre servidores | Header `X-API-Key`. Cada módulo tiene **su propia clave** para consumir a Salud (`CLAVE_ENTRADA_<MODULO>` en Salud) y Salud usa la clave que cada módulo le entrega (`API_KEY_<MODULO>`). Las claves se envían solo por mensaje privado |
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

URL base de producción de Seguridad: `https://securitytubac.com/api/v1/seguridad` (en el `.env` de Salud va solo el dominio, `URL_SEGURIDAD=https://securitytubac.com`). Documentación: `https://securitytubac.com/api/docs/`. Salud envía en todas las solicitudes:

```
X-API-Key: <clave que Seguridad entrega a Salud, por mensaje privado>
X-Modulo-Origen: Salud
```

En el `.env` de Salud: `URL_SEGURIDAD=https://securitytubac.com`, `API_KEY_SEGURIDAD=<su clave>` y `REENVIAR_TOKEN_USUARIO=false`.

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

- El CUI va en la ruta y tiene **exactamente 13 dígitos**; Salud no consulta si el paciente no tiene un CUI válido.
- `nombreCompleto` es **opcional**: Seguridad puede usarlo para confirmar la identidad o ignorarlo. La llave es el CUI.
- `nivelRiesgo` puede ser `NINGUNO`, `BAJO`, `MEDIO` o `ALTO`.
- Un `404` se interpreta como "sin antecedentes registrados".

**Alertas activas.** Se muestran en el panel del personal de Emergencias (departamento del hospital, `DEPARTAMENTO_ALERTAS`).

```
GET /api/v1/seguridad/alertas?zona=Antigua Guatemala&departamento=Sacatepéquez
```
Ambos filtros son opcionales. Responde una lista de alertas, cada una con `id`, `tipo`, `zona`, `departamento`, `nivel` (`BAJO`, `MEDIO`, `ALTO`), `descripcion` y `estado` (`ACTIVA`). Salud muestra solo las `ACTIVA`.

**Indicadores.** `GET /api/v1/seguridad/indicadores`: cualquier `200` marca a Seguridad como "Conectado".

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

**Obligaciones de pago (contrato de Tributario).** Salud registra el cobro de cada consulta; el ciudadano paga en Tributario con el número de referencia. Reemplaza la verificación de pago anterior (WS-SALUD-09).

```
POST /api/v1/integraciones/salud/obligaciones
{ "numero_referencia": "SAL-2026-000120", "dpi_persona": "1234567890101",
  "tipo_obligacion": "CONSULTA_MEDICA", "concepto": "Consulta médica general",
  "monto": 150.00, "moneda": "GTQ", "fecha_emision": "2026-10-08", "fecha_vencimiento": "2026-10-23" }
```

- `numero_referencia` lo genera Salud: `SAL-AAAA-NNNNNN`, correlativo por año.
- El vencimiento es la emisión más `DIAS_VENCIMIENTO_COBRO` (15 días por defecto).
- Un `409` (ya registrada) no es error para Salud: la obligación ya existe.
- `tipo_obligacion` que envía Salud (*por confirmar con Tributario*):

| tipo_obligacion | Cuándo | concepto (ejemplo) |
|---|---|---|
| `CONSULTA_MEDICA` | Cobro de una cita | "Consulta médica general" |
| `HOSPITALIZACION` | Caja cierra la cuenta de un paciente egresado | "Hospitalización — Medicina general, 3 días" |
| `SERVICIOS_MEDICOS` | Caja cierra una cuenta ambulatoria (laboratorio, imágenes) | "Servicios médicos ambulatorios" |

  El `monto` de una cuenta es su saldo: cargos (día cama, medicamentos, servicios) menos descuentos. Las citas y las cuentas comparten el correlativo `SAL-AAAA-NNNNNN`.

**Estado de la obligación** (ruta propuesta, *por confirmar con Tributario*):

```
GET /api/v1/integraciones/salud/obligaciones/{numero_referencia}
→ { "success": true, "data": { "estado": "PAGADO", "numero_autorizacion": "AUT-…", "fecha_pago": "2026-10-08T10:15" } }
```

Salud da la cita por pagada si `estado` es `PAGADO`, `PAGADA`, `CONFIRMADO` o `APROBADO`, o si llega `pagoConfirmado: true`.

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
| **WS-SALUD-02** Establecimientos disponibles | Seguridad | `GET /establecimientos/disponibilidad` (detalle abajo) | `disponible`, `mensaje` y `establecimientos[]` |
| **WS-SALUD-06** Horas de práctica | Educación | `GET /practicantes/{cui}/horas` | `horasAcumuladas`, `fechaInicio`, `fechaFin`, `supervisor`, `estado` |
| Costo de una cita | Tributario | `GET /citas/{id}/costo` | `cita_id`, `monto`, `pago_confirmado` |
| Aviso de pago | Tributario | `POST /pagos/notificacion` con `numero_referencia`, `estado` (`PAGADO` o `ANULADO`), `numero_autorizacion`, `fecha_pago`, `monto_pagado` | `200` registrado (la cita o la cuenta queda pagada) · `400` datos incompletos · `404` referencia desconocida |
| Indicadores agregados | Auditoría Social | `GET /indicadores` (con API key, o con token de rol `auditoria:*`) | Totales de pacientes, citas, recursos, turnos, vacunación, hospitalización (camas, ocupación, hospitalizados, egresos), farmacia (recetas e inventario bajo mínimo), cuentas (abiertas, por cobrar, cobrado en 30 días) y presupuesto. **Sin datos personales** |
| Ejecución presupuestaria | Auditoría Social | `GET /presupuesto/ejecucion` | Periodo vigente: `monto_asignado`, `monto_ejecutado_servicio_social`, `porcentaje_ejecutado` |

### WS-SALUD-02 en detalle (Seguridad)

`GET https://saludumg.online/api/v1/salud/establecimientos/disponibilidad`

Headers: `X-API-Key: <clave que Salud entrega a Seguridad>` y `X-Modulo-Origen: Seguridad`.

| Parámetro | Obligatorio | Valores | Ejemplo |
|---|---|---|---|
| `departamento` | No | Nombre del departamento. Sin importar mayúsculas ni tildes | `Sacatepéquez` o `SACATEPEQUEZ` |
| `municipio` | No | Nombre del municipio | `Antigua Guatemala` |
| `tipoAtencion` | No | `EMERGENCIA`, `CONSULTA_GENERAL`, `ESPECIALIDAD`, `VACUNACION` | `EMERGENCIA` |
| `especialidad` | No | Un tipo de atención (`EMERGENCIA`, …) filtra por ese tipo; una especialidad médica (`Traumatología`, `Pediatría`, …) devuelve los establecimientos que atienden `ESPECIALIDAD` | `Traumatología` |
| `nivelUrgencia` | No | Se recibe y registra; todavía no filtra | `ALTO` |

Sin parámetros devuelve todos los establecimientos activos. Si se envían `tipoAtencion` y `especialidad`, manda `tipoAtencion`.

Respuesta `200` con resultados:

```json
{
  "success": true,
  "disponible": true,
  "mensaje": "Se encontraron establecimientos disponibles",
  "establecimientos": [
    {
      "nombreEstablecimiento": "Hospital Nacional Pedro de Bethancourt",
      "tipoEstablecimiento": "HOSPITAL",
      "direccion": "Aldea San Felipe de Jesús",
      "departamento": "Sacatepéquez",
      "municipio": "Antigua Guatemala",
      "telefono": "78319600",
      "estadoServicio": "ACTIVO",
      "tipoAtencionDisponible": "EMERGENCIA,CONSULTA_GENERAL,ESPECIALIDAD"
    }
  ]
}
```

Respuesta `200` sin resultados: `{"success": true, "disponible": false, "establecimientos": [], "mensaje": "No se encontraron establecimientos para los criterios enviados"}`.

Errores (todos con `{"success": false, "error": "<codigo>", "message": "..."}`):

| HTTP | error | Cuándo |
|---|---|---|
| 400 | `parametro_invalido` | `tipoAtencion` no es uno de los valores permitidos |
| 401 | `sin_api_key` | No se envió `X-API-Key` |
| 403 | `api_key_invalida` | La clave no es la que Salud entregó |
| 405 | `metodo_no_permitido` | Se usó otro método (solo `GET`) |
| 500 | `error_interno` | Falla de Salud (se puede reintentar) |

Datos de prueba (ficticios): `departamento=Sacatepéquez&municipio=Antigua Guatemala&tipoAtencion=EMERGENCIA` devuelve 1 hospital; `departamento=Sacatepéquez` devuelve 3; `departamento=Guatemala&tipoAtencion=EMERGENCIA` devuelve el Hospital Roosevelt; `departamento=Petén` devuelve `disponible: false`.

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
