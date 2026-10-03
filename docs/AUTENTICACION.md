# Autenticación y autorización — Módulo de Salud

Cómo el Módulo de Salud consume el **Login Único** (servicio transversal AUTH, Keycloak) y qué rol protege cada operación.
Este documento cubre el punto del checklist de entrega *"Documentado qué claims consume y qué rol protege cada operación"*.

## 1. Resumen

| Aspecto | Implementación |
|---|---|
| Servidor de identidad | Login Único (Keycloak), realm `rsd` |
| Client del frontend | `salud-web` (público, sin `client_secret`) |
| Flujo del frontend | Authorization Code + PKCE (`react-oidc-context` + `oidc-client-ts`) |
| Token enviado al backend | **Access token** en `Authorization: Bearer <token>` (nunca el id_token) |
| Validación en el backend | **Local** contra el JWKS (`PyJWT` + `PyJWKClient`), con las llaves en caché |
| Algoritmo | `RS256` fijo (el token no puede elegirlo) |
| Validaciones | firma, `iss`, `aud = rsd-api`, `exp`; también exige `sub` |
| Identificador de usuario | claim `sub`; el email nunca se usa como llave |
| Tabla de usuarios propia | **No existe**: los usuarios viven en el Login Único |
| Comunicación entre módulos | Header `X-API-Key`, solo de servidor a servidor. Nunca desde el navegador |

### Validación local (sin llamar al Login Único en cada petición)

- Al arrancar, el backend descarga las llaves públicas del JWKS (`precargar_jwks()` en `auth.py`).
- Cada llave queda en caché según su `kid`. Las peticiones siguientes verifican la firma con cómputo local.
- **Prueba realizada:** con el Login Único apagado, un token vigente sigue respondiendo `200` (y `403` o `401` cuando corresponde).
- Si llega un token firmado con una llave desconocida y el Login Único no responde, el backend devuelve `503 auth_no_disponible`.

## 2. Configuración

**Backend (`.env`)**

```
AUTH_ISSUER=<URL_DEL_DIA>/realms/rsd     # cambia cada día: solo aquí, nunca en el código
AUTH_AUDIENCE=rsd-api
MODULOS_API_KEY=<clave entre módulos>
```

El JWKS se deriva del issuer: `<AUTH_ISSUER>/protocol/openid-connect/certs`.

**Frontend (`.env.local`)**

```
VITE_AUTH_URL=<URL_DEL_DIA>/realms/rsd
VITE_CLIENT_ID=salud-web
```

El frontend corre en `http://localhost:4200`, que es el puerto registrado en el Login Único para `salud-web`.
El frontend **no** tiene la API key: todo lo que llega al navegador es público.

## 3. Claims que consume el módulo

| Claim | Dónde se usa | Para qué |
|---|---|---|
| `iss` | backend | Debe ser igual a `AUTH_ISSUER`. Si no coincide, responde `401` |
| `aud` | backend | Debe incluir `rsd-api`. Si no, responde `401` |
| `exp` | backend | Si el token está vencido, responde `401 token_expirado` |
| `sub` | backend | Llave del usuario. `pacientes.usuario_sub` vincula a un ciudadano con su registro; `citas_medicas.medico_sub` y `expedientes_clinicos.medico_sub` guardan al médico |
| `realm_access.roles` | backend y frontend | Autorización (`requiere_rol`) y el rol que se muestra en la barra |
| `preferred_username`, `email`, `name` | backend y frontend | Solo informativos: se muestran en pantalla. **No** se usan como llave |
| `azp` | backend | Módulo que originó el token (se guarda en `g.usuario["origen"]`) |

## 4. Roles

| Rol | Origen | Uso en Salud |
|---|---|---|
| `salud:medico` | Login Único | Atención clínica: expedientes, vacunación, turnos |
| `salud:admin` | Login Único | Administración: pacientes, recursos, presupuesto, turnos |
| `salud:recepcion` | **Pendiente de solicitar** | Registro de pacientes y generación de turnos. Mientras no exista, esas operaciones las hace `salud:admin` |
| `ciudadano` | Login Único | Solo sus propios datos: su paciente, sus citas, su expediente y su vacunación |
| `auditoria:analista`, `auditoria:admin` | Login Único | Auditoría Social: solo indicadores **agregados** (`/panel`, `/indicadores`, `/presupuesto/ejecucion`). Nunca datos personales |

En la tabla siguiente, **"Personal"** significa cualquiera de `salud:medico`, `salud:admin` o `salud:recepcion`.

## 5. Qué protege cada operación

Todas las rutas empiezan con `/api/v1/salud`.

### 5.1 Operaciones con token del Login Único (frontend y usuarios)

| Método | Ruta | Quién puede | Regla por registro (OWASP API1, BOLA) |
|---|---|---|---|
| GET | `/pacientes` | Personal | — |
| POST | `/pacientes` | `salud:admin`, `salud:recepcion` | — |
| GET | `/pacientes/me` | Cualquier usuario autenticado | Devuelve solo el paciente vinculado a su `sub`. Si no hay: 404 `no_vinculado` con su `sub` (el "código de vinculación" que ve en *Mi resumen*) |
| GET | `/pacientes/<id>` | Personal, o el ciudadano dueño | Ciudadano: solo si `usuario_sub == sub`. Un id ajeno o inexistente responde `403` (no revela si existe) |
| PUT | `/pacientes/<id>` | `salud:admin`, `salud:recepcion`, o el ciudadano dueño | Admin/recepción: todos los campos, incluido `usuario_sub` (vincular; 36 caracteres → si no, 400; si ya lo usa otro paciente → 409). Ciudadano: solo su propio registro y solo `telefono`, `tipo_seguro`, `cuidador` |
| GET | `/citas` | Cualquier usuario autenticado | Personal: todas (filtro `?paciente_id` opcional). Ciudadano: **solo sus citas**; el filtro se ignora |
| POST | `/citas` | Personal, o ciudadano para sí mismo | Ciudadano: solo con su propio `paciente_id` |
| PUT | `/citas/<id>` | Personal, o el ciudadano dueño | Ciudadano: solo puede reprogramar la fecha; el **estado** lo cambia el personal |
| DELETE | `/citas/<id>` | Personal, o el ciudadano dueño | Ciudadano: solo cancela sus propias citas |
| GET | `/expedientes/<paciente_id>` | `salud:medico`, `salud:admin`, o el ciudadano dueño | Datos clínicos: recepción **no** tiene acceso |
| POST | `/expedientes/<paciente_id>/atenciones` | `salud:medico` | El médico queda registrado con su `sub` |
| GET | `/vacunacion` | `salud:medico`, `salud:admin` | — |
| POST | `/vacunacion` | `salud:medico`, `salud:admin` | — |
| GET | `/vacunacion/<paciente_id>` | Personal, o el ciudadano dueño | Ciudadano: solo su propio registro |
| PUT | `/vacunacion/<paciente_id>` | `salud:medico`, `salud:admin` | — |
| DELETE | `/vacunacion/<paciente_id>` | `salud:admin` | — |
| POST | `/turnos` | `salud:admin`, `salud:recepcion` | — |
| GET | `/turnos/activos` | Cualquier usuario autenticado | Solo los de hoy. Número, estado, prioridad y consultorio; el nombre del paciente **solo** para el personal (la pantalla de sala de espera no lo muestra) |
| PUT | `/turnos/<id>/llamar`, `/atender`, `/finalizar` | `salud:medico`, `salud:admin` | `llamar` acepta `{"modulo_asignado": "Consultorio 2"}` |
| GET | `/recursos` | Cualquier usuario autenticado | Datos agregados (camas, ambulancias) |
| POST | `/recursos` | `salud:admin` | — |
| PUT | `/recursos/<id>` | `salud:admin` | — |
| PUT | `/presupuesto` | `salud:admin` | — |
| GET | `/panel` | Personal y Auditoría | Indicadores agregados del Dashboard (reemplaza el uso de la API key en el navegador) |
| GET | `/integraciones/estado` | Personal | Estado de conexión con Educación, Seguridad y Tributario |
| GET | `/integraciones/bitacora` | Personal | Bitácora de llamadas entre módulos (CUI enmascarados) |
| POST | `/integraciones/simular/<caso>` | `salud:medico`, `salud:admin` | Demostración: un módulo simulado consume un servicio de Salud |
| GET | `/pacientes/<id>/antecedentes` | Personal | Consulta a Seguridad (WS-SALUD-08). Ver `docs/INTEGRACIONES.md` |
| GET | `/educacion/estudiantes/<cui>` | `salud:medico`, `salud:admin` | Consulta a Educación |
| POST | `/citas/<id>/verificar-pago` | Personal | Consulta a Tributario (WS-SALUD-09); si está pagada, marca la cita |

### 5.2 Operaciones entre módulos (`X-API-Key`, servidor a servidor)

`/indicadores` y `/presupuesto/ejecucion` aceptan además el **token de un usuario de Auditoría** (`auditoria:analista` o `auditoria:admin`) reenviado por ese módulo.

| Método | Ruta | Consumidor |
|---|---|---|
| POST | `/jornadas/coordinar` | Educación (WS-SALUD-01) |
| GET | `/establecimientos/disponibilidad` | Seguridad (WS-SALUD-02) |
| GET | `/practicantes/<cui>/horas` | Educación |
| GET | `/citas/<id>/costo` | Tributario |
| GET | `/presupuesto/ejecucion` | Auditoría Social |
| GET | `/indicadores` | Auditoría Social y otros módulos |

> Según la guía del Login Único, cuando hay un usuario presente lo recomendado es reenviar su access token al módulo destino, porque todos comparten `aud: rsd-api`. La API key queda para procesos sin usuario, hasta que se solicite un client confidencial con service account.

## 6. Respuestas 401 y 403

| Código | `error` | Cuándo |
|---|---|---|
| 401 | `sin_token` | No viene el header `Authorization: Bearer` |
| 401 | `token_invalido` | Firma inválida, token mal formado, `iss` o `aud` incorrectos, o llave desconocida |
| 401 | `token_expirado` | `exp` vencido |
| 403 | `permiso_denegado` | Token válido pero sin el rol, o el registro no pertenece al usuario |
| 503 | `auth_no_disponible` | Llave nueva y el Login Único no responde |
| 401 | `sin_api_key` | Endpoint entre módulos sin `X-API-Key` |
| 401 | `sin_credenciales` | `/indicadores` o `/presupuesto/ejecucion` sin API key ni token |
| 503 | `modulo_no_disponible` / `no_configurado` | Un módulo externo (Educación, Seguridad, Tributario) no responde o no tiene URL |
| 403 | `api_key_invalida` | `X-API-Key` incorrecta |

**401 = autenticación** ("no sé quién sos"). **403 = autorización** ("sé quién sos, pero no podés hacer esto").

## 7. Checklist de entrega del Login Único

| Punto | Estado | Evidencia |
|---|---|---|
| El login redirige al Login Único; la app no tiene campos de contraseña | ✅ | `Login.jsx` solo tiene un botón que llama a `signinRedirect()` |
| Authorization Code + PKCE (`response_type=code`) | ✅ | Prueba de navegador: `response_type=code`, `code_challenge_method=S256` |
| El backend valida la firma con el JWKS localmente | ✅ | `auth.py`: `PyJWKClient` con caché y precarga |
| Valida `iss`, `aud`, `exp` y fija `RS256` | ✅ | `jwt.decode(..., algorithms=["RS256"], audience, issuer)` |
| Al menos un endpoint devuelve 401 sin token | ✅ | `GET /pacientes` sin token responde `401` |
| Al menos un endpoint devuelve 403 con rol insuficiente | ✅ | `GET /pacientes` con `ciudadano1` responde `403` |
| Usa `sub` como identificador en la base de datos | ✅ | `usuario_sub` y `medico_sub` (`VARCHAR(36)`); ya no existe `usuarios_roles` |
| Logout que cierra la sesión en el Login Único | ✅ | `signoutRedirect()`; al volver a entrar se pide la contraseña |
| SSO comprobado | ✅ (dentro del módulo) | Segunda pestaña entra sin volver a pedir contraseña. Falta probarlo entre módulos |
| Documentado qué claims consume y qué rol protege cada operación | ✅ | Este documento |
| Prueba con el Login Único apagado | ✅ | Token vigente con el IdP apagado: `200` para `medico1`, `403` para `ciudadano1`, `401` sin token |

## 8. Cómo probarlo

1. Levantar el Login Único local (ver `keycloak-local/README.md`) o usar la URL del día.
2. Levantar el backend con `AUTH_ISSUER` apuntando a ese issuer.
3. Correr el script de pruebas `pruebas/prueba_auth.py` (65 verificaciones: 401, 200, 403, BOLA, validaciones, `/panel`, Auditoría, integración y API key):
   ```bash
   venv/Scripts/python.exe pruebas/prueba_auth.py
   ```
4. Probar siempre también con `ciudadano1`: es el usuario que **no** debe poder entrar a las operaciones protegidas.

## 9. Pendientes

- Solicitar el rol `salud:recepcion` y un usuario de prueba.
- Solicitar el registro de `https://saludumg.online/*` (redirect URI) y `https://saludumg.online` (Web origins) para `salud-web`.
- Comprobar el SSO entre módulos, con otro módulo en la misma sesión del navegador.
