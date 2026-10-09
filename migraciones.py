"""
Migraciones automáticas al arrancar el backend.

db.create_all() crea las tablas que faltan, pero NO agrega columnas a tablas
que ya existen. Aquí se agregan las columnas nuevas a las bases que ya están
en uso (la del servidor y las locales), sin borrar datos. Es seguro correrlo
en cada arranque: si la columna ya existe, no hace nada.
"""
import logging

from sqlalchemy import inspect, text

log = logging.getLogger(__name__)

COLUMNAS = [
    # (tabla, columna, definición SQL)
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
