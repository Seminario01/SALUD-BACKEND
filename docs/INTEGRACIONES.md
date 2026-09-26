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
| Tributario | `POST /api/v1/tributario/pagos/verificar` (WS-SALUD-09) | `POST /api/v1/salud/citas/{id}/verificar-pago` | Citas → **Verificar pago** | Personal |
| Los tres | `GET /api/v1/{modulo}/indicadores` (como verificación de conexión) | `GET /api/v1/salud/integraciones/estado` | Dashboard → **Integración con otros módulos** | Personal |

### Datos acordados

**Seguridad (antecedentes).** Salud envía el CUI y el nombre completo. Seguridad responde:
`tieneAntecedentes`, `tipoAntecedente`, `nivelRiesgo`, `requiereCustodia`.
Si Seguridad responde 404, Salud lo interpreta como "sin antecedentes registrados".
El paciente **siempre** se atiende; el resultado solo indica cuidados o custodia adicionales.

**Educación (estudiante).** Salud envía el CUI. Educación responde `establecimiento`, `grado`, `seccion`, `jornada`.
Un 404 significa que no es estudiante.

**Tributario (verificar pago).** Salud envía `numero_referencia` (lo genera Salud: `SALUD-AAAA-XXXXXXXX`), `dpi`, `concepto`, `monto` y `estado_pago`.
Salud da el pago por confirmado si la respuesta trae `pagoConfirmado: true`, `confirmado: true` o `estado` igual a `CONFIRMADO`, `PAGADO` o `APROBADO`. En ese caso la cita queda con `pago_confirmado = true`.
El monto es el `costo` de la cita o, si no tiene, `COSTO_CONSULTA` (por defecto Q150).

## 3. Configuración (`.env` del backend)

```
URL_EDUCACION=https://<url-de-educacion>
URL_SEGURIDAD=https://<url-de-seguridad>
URL_TRIBUTARIO=https://<url-de-tributario>
MODULOS_API_KEY=<la clave acordada entre módulos>
COSTO_CONSULTA=150
```

Con una URL vacía, ese módulo aparece como **"No configurado"** en el Dashboard.

## 4. Simuladores (solo desarrollo)

`simuladores/app.py` imita los tres módulos, con las mismas rutas y campos. Todas sus respuestas llevan `"simulado": true`, y el Dashboard y las pantallas lo indican con "(simulador)".

```bash
python simuladores/app.py          # http://localhost:5055
```

En el `.env`: `URL_EDUCACION`, `URL_SEGURIDAD` y `URL_TRIBUTARIO` apuntando a `http://localhost:5055`.

| Módulo | Regla del simulador |
|---|---|
| Seguridad | CUI que termina en **9**: riesgo ALTO, requiere custodia. En **7**: riesgo BAJO. Otro: sin antecedentes |
| Educación | CUI que termina en número **par**: es estudiante. Impar: no es estudiante |
| Tributario | monto mayor a 0: pago CONFIRMADO |

**Cuando un equipo publique su servicio real**, solo se cambia su URL en el `.env` y se reinicia el backend. El código no cambia.
Si sus rutas o campos son distintos a los acordados, se ajustan en `services_externos.py`.

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
