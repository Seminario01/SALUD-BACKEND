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
| `sub` | backend | Llave del usuario. `pacientes.usuario_sub` vincula a un ciudadano con su registro; `citas_medicas.medico_sub`, `expedientes_clinicos.medico_sub` y `recetas.medico_sub` guardan al médico; `recetas.despachado_por` guarda a Farmacia |
| `realm_access.roles` | backend y frontend | Autorización (`requiere_rol`) y el rol que se muestra en la barra |
| `preferred_username`, `email`, `name` | backend y frontend | Solo informativos: se muestran en pantalla. **No** se usan como llave |
| `azp` | backend | Módulo que originó el token (se guarda en `g.usuario["origen"]`) |

## 4. Puestos y matriz de permisos

La autorización sigue el documento **"Matriz de permisos — Módulo Salud"**. Está implementada en un solo lugar: el diccionario `PERMISOS` de `auth.py`, y el frontend tiene la misma tabla en `src/permisos.js`.
- Las rutas preguntan por un **permiso**, no por un rol: `@requiere_permiso("citas.gestionar")` o `puede("expediente.ver")`.
- Para cambiar quién puede hacer algo, se edita `PERMISOS` (y `permisos.js`), no las rutas.
- `GET /mis-permisos` devuelve los permisos del usuario que llama.

| Puesto | Rol | Usuario de prueba |
|---|---|---|
| Médico | `salud:medico` | `medico1` |
| Enfermería | `salud:enfermeria` | `enfermera1` |
| Recepción / Admisión | `salud:recepcion` | `recepcion1` |
| Farmacia | `salud:farmacia` | `farmacia1` |
| Caja | `salud:caja` | `caja1` |
| Jefatura médica | `salud:jefatura` (y `salud:medico`) | `jefatura1` |
| Administración | `salud:admin` | `admin.salud` |
| Ciudadano | `ciudadano` | `ciudadano1`, `ciudadano2` |
| Auditoría Social | `auditoria:analista`, `auditoria:admin` | `analista1` |

Los roles nuevos y sus usuarios se agregan a un Keycloak existente con `keycloak-local/agregar_puestos.py`, sin reimportar el realm: los `sub` de los usuarios no cambian. También están en `keycloak-local/import/rsd-realm.json` para instalaciones nuevas.

| Permiso | Puestos | Endpoints |
|---|---|---|
| `pacientes.ver` | Médico, Enfermería, Recepción, Farmacia, Caja, Jefatura, Admin | `GET /pacientes`, `GET /pacientes/<id>` |
| `pacientes.registrar` | Recepción, Admin | `POST /pacientes`; `PUT /pacientes/<id>` con todos los campos y la vinculación (`usuario_sub`: 36 caracteres → si no, 400; ya usado → 409) |
| `pacientes.antecedentes` | Médico, Enfermería, Recepción, Jefatura | `GET /pacientes/<id>/antecedentes` (Seguridad, WS-SALUD-08) |
| `citas.ver` | Médico, Enfermería, Recepción, Caja, Jefatura, Admin | `GET /citas` (todas; filtro `?paciente_id`) |
| `citas.gestionar` | Médico, Recepción | `POST`, `PUT` (incluye el **estado**) y `DELETE /citas/<id>` de cualquier paciente |
| `turnos.generar` | Enfermería, Recepción | `POST /turnos` |
| `turnos.atender` | Médico, Enfermería | `PUT /turnos/<id>/llamar`, `/atender`, `/finalizar` |
| `turnos.ver_cola` | Médico, Enfermería, Recepción, Jefatura, Admin | Nombres de pacientes en `GET /turnos/activos` |
| `expediente.ver` | Médico, Enfermería, Jefatura, Admin (solo lectura) | `GET /expedientes/<paciente_id>` |
| `expediente.registrar` | Médico | `POST /expedientes/<paciente_id>/atenciones` (queda el `sub` del médico) |
| `vacunacion.ver` | Médico, Enfermería, Jefatura, Admin (solo lectura) | `GET /vacunacion`, `GET /vacunacion/<paciente_id>` |
| `vacunacion.registrar` | Médico, Enfermería | `POST /vacunacion`, `PUT /vacunacion/<paciente_id>`, `GET /educacion/estudiantes/<cui>` |
| `vacunacion.anular` | Jefatura | `DELETE /vacunacion/<paciente_id>` (solo registros creados por error) |
| `recursos.ver` | Médico, Enfermería, Recepción, Jefatura, Admin | `GET /recursos` |
| `recursos.gestionar` | Admin | `POST /recursos`, `PUT /recursos/<id>` (todo) |
| `recursos.camas` | Enfermería, Admin | `PUT /recursos/<id>`: Enfermería solo cambia `disponible` de las **camas**. Las áreas con censo de camas no se editan a mano (409): se calculan desde Hospitalización |
| `pagos.verificar` | Caja, Recepción, Admin | `POST /citas/<id>/cobro` y `POST /citas/<id>/verificar-pago` (obligaciones de Tributario) |
| `hospitalizacion.ver` | Médico, Enfermería, Recepción, Caja, Jefatura, Admin | `GET /camas`, `GET /hospitalizaciones`, `GET /hospitalizaciones/<id>`. Recepción y Caja ven área y cama, sin diagnóstico ni notas. El ciudadano ve solo las suyas |
| `hospitalizacion.ordenar` | Médico | `POST /hospitalizaciones` (orden de ingreso), `POST /hospitalizaciones/<id>/egreso`, `POST /hospitalizaciones/<id>/anular` (solo sin cama) |
| `hospitalizacion.camas` | Enfermería | `POST /hospitalizaciones/<id>/asignar-cama` (ingreso o traslado), `PUT /camas/<id>` (limpieza, mantenimiento, disponible). Admin también cambia el estado y agrega camas (`POST /camas`, con `recursos.gestionar`) |
| `hospitalizacion.notas` | Médico, Enfermería | `POST /hospitalizaciones/<id>/notas` (nota y signos vitales; solo pacientes ingresados) |
| `cuentas.ver` | Recepción, Caja, Admin (solo lectura) | `GET /cuentas`, `GET /cuentas/<id>`, `GET /servicios`. El ciudadano ve solo sus cuentas |
| `cuentas.gestionar` | Caja | `POST /cuentas` (ambulatoria), `POST /cuentas/<id>/cargos`, `/descuentos`, `/movimientos/<mid>/anular`, `/cerrar` (cobro a Tributario), `/verificar-pago`. El catálogo de servicios (`POST`/`PUT /servicios`) es de Administración (`recursos.gestionar`) |
| `recetas.ver` | Médico, Enfermería, Farmacia, Caja, Jefatura, Admin | `GET /recetas` (todas; filtros `?estado`, `?paciente_id`). El ciudadano ve solo las suyas |
| `recetas.crear` | Médico | `POST /recetas` (queda el `sub` y el nombre del médico) |
| `recetas.anular` | Médico (solo las que él emitió), Jefatura | `POST /recetas/<id>/anular` (solo si está PENDIENTE) |
| `recetas.despachar` | Farmacia | `POST /recetas/<id>/despachar`: descuenta el inventario; quien recetó no puede despachar |
| `inventario.ver` | Médico, Enfermería, Farmacia, Jefatura, Admin | `GET /medicamentos`, `GET /medicamentos/<id>/movimientos` (kardex). El médico también lista medicamentos para recetar |
| `inventario.gestionar` | Farmacia | `POST /medicamentos`, `POST /medicamentos/<id>/movimientos` (entrada o ajuste; nunca existencia negativa) |
| `panel.ver` | Todo el personal y Auditoría | `GET /panel` |
| `presupuesto.ver` | Jefatura, Admin, Auditoría | `GET /presupuesto/ejecucion` (también con API key) |
| `presupuesto.editar` | Admin | `PUT /presupuesto` |
| `integraciones.ver` | Jefatura, Admin | `GET /integraciones/estado`, `GET /integraciones/bitacora` |
| `integraciones.demo` | Jefatura, Admin | `POST /integraciones/simular/<caso>` |

## 5. Reglas por registro

Todas las rutas empiezan con `/api/v1/salud`.

### 5.1 El ciudadano: solo lo propio (OWASP API1, BOLA)

| Operación | Regla |
|---|---|
| `GET /pacientes/me` | Su paciente vinculado. Si no hay: 404 `no_vinculado` con su `sub` (el código de vinculación de *Mi resumen*) |
| `GET`, `PUT /pacientes/<id>` | Solo si `usuario_sub == sub`. Un id ajeno o inexistente responde 403, para no revelar si existe. En `PUT` solo `telefono`, `tipo_seguro` y `cuidador` |
| `GET /citas` | Solo sus citas; el filtro `?paciente_id` se ignora |
| `POST /citas` | Solo con su propio `paciente_id` |
| `PUT /citas/<id>` | Solo reprograma la fecha; el estado lo cambia el personal |
| `DELETE /citas/<id>` | Solo cancela sus citas |
| `GET /expedientes/<id>`, `GET /vacunacion/<id>` | Solo los suyos |
| `GET /recetas` | Solo sus recetas; el filtro `?paciente_id` se ignora |
| `GET /hospitalizaciones`, `GET /hospitalizaciones/<id>` | Solo las suyas; una ajena responde 403 |
| `GET /cuentas`, `GET /cuentas/<id>` | Solo sus cuentas (con la referencia de pago); una ajena responde 403 |
| `GET /turnos/activos` | Sin nombres (igual que la pantalla de sala de espera) |

### 5.2 Operaciones entre módulos (`X-API-Key`, servidor a servidor)

`/indicadores` y `/presupuesto/ejecucion` aceptan además el **token de un usuario de Auditoría** (`auditoria:analista` o `auditoria:admin`) reenviado por ese módulo.

| Método | Ruta | Consumidor |
|---|---|---|
| POST | `/jornadas/coordinar` | Educación (WS-SALUD-01) |
| GET | `/establecimientos/disponibilidad` | Seguridad (WS-SALUD-02) |
| GET | `/practicantes/<cui>/horas` | Educación |
| GET | `/citas/<id>/costo` | Tributario |
| POST | `/pagos/notificacion` | Tributario (aviso de pago) |
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
3. Agregar los puestos, una sola vez por Keycloak: `python keycloak-local/agregar_puestos.py`.
4. Correr las pruebas:
   ```bash
   venv/Scripts/python.exe pruebas/prueba_auth.py       # 73 verificaciones: 401, 200, 403, BOLA, validaciones, Auditoría, integraciones, API key
   venv/Scripts/python.exe pruebas/prueba_permisos.py   # la matriz completa: 9 usuarios × 22 permisos = 198 celdas
   ```
5. Probar siempre también con `ciudadano1`: es el usuario que **no** debe poder entrar a las operaciones protegidas.

## 9. Pendientes

- Solicitar a la ingeniera los roles de la matriz (`salud:enfermeria`, `salud:recepcion`, `salud:farmacia`, `salud:caja`, `salud:jefatura`) con esos mismos nombres.
- Solicitar el registro de `https://saludumg.online/*` (redirect URI) y `https://saludumg.online` (Web origins) para `salud-web`.
- Comprobar el SSO entre módulos, con otro módulo en la misma sesión del navegador.
