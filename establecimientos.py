"""
Red de establecimientos: los 45 hospitales públicos del MSPAS (datos/red_hospitalaria.json).

Fuente: portal "Establecimientos de Salud" del MSPAS (listado, categoría Hospital, estado Funcionando),
consultado el 23/10/2026. El portal no publica dirección ni teléfono de cada hospital: quedan vacíos y
Administración los completa en la pantalla "Red de establecimientos". El nivel sale del nombre oficial.

  cargar_red(db)   al arrancar: agrega los hospitales que falten (por nombre u otro nombre conocido) y
                   completa municipio, nivel y fuente de los que ya estaban, SIN pisar lo que Administración
                   haya editado (dirección, teléfono, estado, tipo de atención).
"""
import json
import logging
import os
import unicodedata

from sqlalchemy import inspect

log = logging.getLogger(__name__)
_RUTA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "datos", "red_hospitalaria.json")
with open(_RUTA, encoding="utf-8") as _f:
    RED = json.load(_f)

TIPOS = ("HOSPITAL", "CENTRO_SALUD", "PUESTO_SALUD", "OTRO")


def _clave(nombre):
    texto = unicodedata.normalize("NFD", (nombre or "").lower()).encode("ascii", "ignore").decode()
    return " ".join(texto.replace(".", " ").split())


def _unir_repetidos(db, Establecimiento):
    """Si un hospital quedó dos veces (por ejemplo, la red se cargó y DESPUÉS los datos demo con otro
    nombre del mismo hospital), se queda el primero, toma lo que le falte del otro y el otro se borra
    (si nadie lo usa en una referencia)."""
    from models import Referencia
    for h in RED["hospitales"]:
        claves = set(map(_clave, [h["nombre"], *h["otros_nombres"]]))
        filas = sorted((e for e in Establecimiento.query.all() if _clave(e.nombre) in claves), key=lambda e: e.id_establecimiento)
        for otro in filas[1:]:
            primero = filas[0]
            for campo in ("direccion", "telefono", "tipo_atencion_disponible"):
                setattr(primero, campo, getattr(primero, campo) or getattr(otro, campo))
            if not Referencia.query.filter_by(establecimiento_id=otro.id_establecimiento).first():
                db.session.delete(otro)
                log.warning("Red de establecimientos: %s estaba repetido; se unió", otro.nombre)


def cargar_red(db):
    from models import Establecimiento
    if "establecimientos" not in inspect(db.engine).get_table_names():
        return
    try:
        existentes = {_clave(e.nombre): e for e in Establecimiento.query.all()}
        nuevos = 0
        for h in RED["hospitales"]:
            e = next((existentes[k] for k in map(_clave, [h["nombre"], *h["otros_nombres"]]) if k in existentes), None)
            if e is None:
                e = Establecimiento(nombre=h["nombre"], tipo="HOSPITAL", estado_servicio="ACTIVO",
                                    tipo_atencion_disponible=h["tipo_atencion"], departamento=h["departamento"],
                                    municipio=h["municipio"])
                db.session.add(e)
                nuevos += 1
            # Lo que viene del MSPAS se completa solo si falta (no se pisa lo editado)
            e.codigo_municipio = e.codigo_municipio or h["codigo_municipio"]
            e.nivel = e.nivel or h["nivel"]
            e.fuente = e.fuente or "MSPAS"
            e.departamento = e.departamento or h["departamento"]
            e.municipio = e.municipio or h["municipio"]
        db.session.flush()
        _unir_repetidos(db, Establecimiento)
        # Los que ya estaban sin código de municipio (cargados a mano): se busca por departamento y municipio
        import ubicaciones
        for e in Establecimiento.query.filter(Establecimiento.codigo_municipio.is_(None)).all():
            codigo = next((c for c, m in ubicaciones.MUNICIPIOS.items() if not c.endswith("00")
                           and _clave(m["nombre"]) == _clave(e.municipio)
                           and _clave(ubicaciones.nombre_departamento(c)) == _clave(e.departamento)), None)
            e.codigo_municipio = codigo
        db.session.commit()
        if nuevos:
            log.warning("Red de establecimientos: %s hospitales agregados", nuevos)
    except Exception as error:  # noqa: BLE001 - el arranque no debe caerse por el catálogo
        db.session.rollback()
        log.warning("No se pudo cargar la red de establecimientos: %s", error)
