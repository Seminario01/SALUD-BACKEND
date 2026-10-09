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
