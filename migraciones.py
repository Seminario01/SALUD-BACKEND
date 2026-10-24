"""
Migraciones automáticas al arrancar el backend.

db.create_all() crea las tablas que faltan, pero NO agrega columnas a tablas
que ya existen. Aquí se agregan las columnas nuevas a las bases que ya están
en uso (la del servidor y las locales), sin borrar datos. Es seguro correrlo
en cada arranque: si la columna ya existe, no hace nada.
"""
import logging
import secrets

from sqlalchemy import inspect, text

log = logging.getLogger(__name__)

COLUMNAS = [
    # (tabla, columna, definición SQL)
    # Red de establecimientos (establecimientos.py)
    ("establecimientos", "codigo_municipio", "VARCHAR(4) NULL"),
    ("establecimientos", "nivel", "VARCHAR(40) NULL"),
    ("establecimientos", "fuente", "VARCHAR(200) NULL"),
    # Detalle de cada llamada entre módulos (bitacora.py)
    ("bitacora_integraciones", "url", "VARCHAR(500) NULL"),
    ("bitacora_integraciones", "solicitud", "TEXT NULL"),
    ("bitacora_integraciones", "respuesta", "TEXT NULL"),
    # Sedes (sedes.py)
    ("establecimientos", "es_sede", "TINYINT(1) NOT NULL DEFAULT 0"),
    ("turnos", "sede_id", "INT NULL"),
    ("camas", "sede_id", "INT NULL"),
    ("hospitalizaciones", "sede_id", "INT NULL"),
    ("recursos_hospitalarios", "sede_id", "INT NULL"),
    ("citas_medicas", "numero_referencia", "VARCHAR(20) NULL UNIQUE"),
    ("citas_medicas", "estado_cobro", "VARCHAR(20) NULL"),
    ("citas_medicas", "fecha_vencimiento", "DATE NULL"),
    ("citas_medicas", "numero_autorizacion", "VARCHAR(60) NULL"),
    ("citas_medicas", "fecha_pago", "DATETIME NULL"),
    # Farmacia
    ("medicamentos", "presentacion", "VARCHAR(100) NULL"),
    ("recetas", "medico_sub", "VARCHAR(36) NULL"),
    ("recetas", "medico_nombre", "VARCHAR(150) NULL"),
    ("recetas", "expediente_id", "INT NULL"),
    ("recetas", "indicaciones", "TEXT NULL"),
    ("recetas", "estado", "VARCHAR(20) NOT NULL DEFAULT 'PENDIENTE'"),
    ("recetas", "despachado_por", "VARCHAR(36) NULL"),
    ("recetas", "fecha_despacho", "DATETIME NULL"),
    ("recetas", "motivo_anulacion", "VARCHAR(255) NULL"),
    ("detalle_receta", "dosis", "VARCHAR(200) NULL"),
    ("movimientos_inventario", "receta_id", "INT NULL"),
    ("movimientos_inventario", "usuario", "VARCHAR(100) NULL"),
    # Hospitalización (la tabla existe desde schema.sql con menos columnas)
    ("hospitalizaciones", "cama_id", "INT NULL"),
    ("hospitalizaciones", "indicaciones", "TEXT NULL"),
    ("hospitalizaciones", "expediente_id", "INT NULL"),
    ("hospitalizaciones", "medico_sub", "VARCHAR(36) NULL"),
    ("hospitalizaciones", "medico_nombre", "VARCHAR(150) NULL"),
    ("hospitalizaciones", "fecha_asignacion", "DATETIME NULL"),
    ("hospitalizaciones", "asignado_por", "VARCHAR(100) NULL"),
    ("hospitalizaciones", "tipo_egreso", "VARCHAR(30) NULL"),
    ("hospitalizaciones", "resumen_egreso", "TEXT NULL"),
    ("hospitalizaciones", "egresado_por", "VARCHAR(150) NULL"),
    ("hospitalizaciones", "motivo_anulacion", "VARCHAR(255) NULL"),
    # Caja y cuentas (tablas existentes desde schema.sql con menos columnas)
    ("servicios", "codigo", "VARCHAR(20) NULL UNIQUE"),
    ("servicios", "categoria", "VARCHAR(30) NULL"),
    ("cuentas_paciente", "tipo", "VARCHAR(20) NOT NULL DEFAULT 'HOSPITALIZACION'"),
    ("cuentas_paciente", "hospitalizacion_id", "INT NULL"),
    ("cuentas_paciente", "fecha_apertura", "DATETIME NULL"),
    ("cuentas_paciente", "fecha_cierre", "DATETIME NULL"),
    ("cuentas_paciente", "abierta_por", "VARCHAR(150) NULL"),
    ("cuentas_paciente", "cerrada_por", "VARCHAR(150) NULL"),
    ("cuentas_paciente", "tramo_inicio", "DATETIME NULL"),
    ("cuentas_paciente", "tramo_area", "VARCHAR(80) NULL"),
    ("cuentas_paciente", "numero_referencia", "VARCHAR(20) NULL UNIQUE"),
    ("cuentas_paciente", "estado_cobro", "VARCHAR(20) NULL"),
    ("cuentas_paciente", "fecha_vencimiento", "DATE NULL"),
    ("cuentas_paciente", "numero_autorizacion", "VARCHAR(60) NULL"),
    ("cuentas_paciente", "fecha_pago", "DATETIME NULL"),
    ("movimientos_cuenta", "categoria", "VARCHAR(30) NULL"),
    ("movimientos_cuenta", "servicio_id", "INT NULL"),
    ("movimientos_cuenta", "cantidad", "INT NULL"),
    ("movimientos_cuenta", "precio_unitario", "DECIMAL(10,2) NULL"),
    ("movimientos_cuenta", "receta_id", "INT NULL"),
    ("movimientos_cuenta", "usuario", "VARCHAR(150) NULL"),
    ("movimientos_cuenta", "anulado", "TINYINT(1) NOT NULL DEFAULT 0"),
    ("movimientos_cuenta", "motivo_anulacion", "VARCHAR(255) NULL"),
    # Tributario: referencia que genera su sistema
    ("citas_medicas", "referencia_tributario", "VARCHAR(40) NULL"),
    ("cuentas_paciente", "referencia_tributario", "VARCHAR(40) NULL"),
    # Citas: médico que atiende y quién la agendó (detalle de la cita)
    ("citas_medicas", "medico_nombre", "VARCHAR(150) NULL"),
    ("citas_medicas", "agendada_por", "VARCHAR(150) NULL"),
    # Signos vitales: peso en las notas de hospitalización
    ("notas_hospitalizacion", "peso", "DECIMAL(5,1) NULL"),
    # Seguridad del paciente: alergias (se revisan al recetar)
    ("pacientes", "alergias", "VARCHAR(500) NULL"),
    ("recetas", "alerta_alergia", "VARCHAR(255) NULL"),
    ("recetas", "alerta_interaccion", "VARCHAR(255) NULL"),
    ("expedientes_clinicos", "codigo_cie10", "VARCHAR(8) NULL"),
    ("turnos", "triage", "VARCHAR(10) NULL"),
    ("pacientes", "municipio", "VARCHAR(4) NULL"),
    ("pacientes", "zona", "VARCHAR(120) NULL"),
    ("turnos", "motivo_triage", "VARCHAR(255) NULL"),
    ("turnos", "triage_por", "VARCHAR(150) NULL"),
    ("turnos", "fecha_triage", "DATETIME NULL"),
    # Receta verificable con QR
    ("recetas", "codigo_verificacion", "VARCHAR(24) NULL UNIQUE"),
]

# Columnas que deben permitir NULL (ej. recetas.id_medico: el médico se
# identifica por su `sub` del Login Único, la tabla medicos es opcional).
OPCIONALES = [
    ("recetas", "id_medico", "INT NULL"),
]


def aplicar(db):
    inspector = inspect(db.engine)
    tablas = set(inspector.get_table_names())
    for tabla, columna, definicion in COLUMNAS:
        if tabla not in tablas:
            continue
        existentes = {c["name"] for c in inspector.get_columns(tabla)}
        if columna in existentes:
            continue
        with db.engine.begin() as conexion:
            conexion.execute(text(f"ALTER TABLE {tabla} ADD COLUMN {columna} {definicion}"))
        log.warning("Migración: columna %s.%s agregada", tabla, columna)

    for tabla, columna, definicion in OPCIONALES:
        if tabla not in tablas:
            continue
        col = next((c for c in inspect(db.engine).get_columns(tabla) if c["name"] == columna), None)
        if col is not None and not col["nullable"]:
            with db.engine.begin() as conexion:
                conexion.execute(text(f"ALTER TABLE {tabla} MODIFY {columna} {definicion}"))
            log.warning("Migración: columna %s.%s ahora admite NULL", tabla, columna)

    _codigos_de_recetas(db, tablas)
    _vacunacion_unica(db, tablas)


def codigo_receta():
    """Código del QR: 12 caracteres al azar (72 bits), imposible de adivinar."""
    return secrets.token_urlsafe(9)


def _codigos_de_recetas(db, tablas):
    """Las recetas de antes del QR reciben su código (una sola vez; si dos procesos arrancan
    a la vez, el WHERE ... IS NULL evita que una receta quede con dos códigos distintos)."""
    if "recetas" not in tablas:
        return
    with db.engine.begin() as conexion:
        ids = [fila[0] for fila in conexion.execute(text("SELECT id_receta FROM recetas WHERE codigo_verificacion IS NULL"))]
        for id_receta in ids:
            conexion.execute(text("UPDATE recetas SET codigo_verificacion = :c WHERE id_receta = :i AND codigo_verificacion IS NULL"),
                             {"c": codigo_receta(), "i": id_receta})
    if ids:
        log.warning("Migración: %s receta(s) recibieron su código de verificación", len(ids))


def _vacunacion_unica(db, tablas):
    """Un solo registro de vacunación por paciente. Las bases de antes de esa regla pueden tener
    dos: se deja el más reciente (el último que se guardó) y se borran los anteriores. Después se
    crea el índice único para que no vuelva a pasar (si falla, solo se avisa: la API ya lo impide)."""
    if "vacunacion" not in tablas:
        return
    with db.engine.begin() as conexion:
        sobran = [fila[0] for fila in conexion.execute(text(
            "SELECT v.id FROM vacunacion v JOIN vacunacion w ON w.paciente_id = v.paciente_id "
            "AND (COALESCE(w.fecha_actualizacion, '1970-01-01') > COALESCE(v.fecha_actualizacion, '1970-01-01') "
            "OR (COALESCE(w.fecha_actualizacion, '1970-01-01') = COALESCE(v.fecha_actualizacion, '1970-01-01') AND w.id > v.id))"))]
        for id_registro in set(sobran):
            conexion.execute(text("DELETE FROM vacunacion WHERE id = :i"), {"i": id_registro})
    if sobran:
        log.warning("Migración: %s registro(s) de vacunación repetidos unificados (queda el más reciente)", len(set(sobran)))
    indices = {i["name"] for i in inspect(db.engine).get_indexes("vacunacion")}
    if "ux_vacunacion_paciente" not in indices:
        try:
            with db.engine.begin() as conexion:
                conexion.execute(text("CREATE UNIQUE INDEX ux_vacunacion_paciente ON vacunacion (paciente_id)"))
            log.warning("Migración: índice único vacunacion.paciente_id creado")
        except Exception as error:   # noqa: BLE001 - no impedir el arranque
            log.warning("Migración: no se pudo crear el índice único de vacunación (%s)", error.__class__.__name__)
