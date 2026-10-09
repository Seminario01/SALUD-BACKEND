"""
Cuentas del paciente: cargos automáticos que generan otros módulos.

- Hospitalización: al asignar la cama se ABRE la cuenta; el día cama se carga
  por tramos (cada traslado cierra el tramo del área anterior) y al egreso se
  carga el último tramo (mínimo un día por estancia).
- Farmacia: al despachar una receta de un paciente ingresado, cada medicamento
  se carga a su cuenta (precio del catálogo × cantidad).

Caja agrega servicios del catálogo, aplica descuentos, cierra la cuenta y envía
el cobro a Tributario (routes/caja.py).
"""
from datetime import datetime
from decimal import Decimal

from extensions import db
from models import CuentaPaciente, Hospitalizacion, MovimientoCuenta, Servicio

# Tarifa de día cama por área (si el catálogo no la tiene, se crea con este valor)
TARIFAS_CAMA = {
    "Medicina general": ("CAMA-GEN", Decimal("150.00")),
    "Pediatría": ("CAMA-PED", Decimal("150.00")),
    "Cuidados intensivos": ("CAMA-UCI", Decimal("600.00")),
}


def tarifa_cama(area):
    codigo, costo = TARIFAS_CAMA.get(area, ("CAMA-GEN", Decimal("150.00")))
    servicio = Servicio.query.filter_by(codigo=codigo).first()
    if servicio is None:
        servicio = Servicio(codigo=codigo, nombre=f"Día cama — {area}", categoria="DIA_CAMA", costo=costo)
        db.session.add(servicio)
        db.session.flush()
    return servicio


def recalcular(cuenta):
    """saldo = cargos - descuentos - pagos (sin los movimientos anulados)."""
    saldo = Decimal("0")
    for m in cuenta.movimientos:
        if m.anulado:
            continue
        saldo += Decimal(m.monto) if m.tipo == "CARGO" else -Decimal(m.monto)
    cuenta.saldo = max(saldo, Decimal("0"))
    return cuenta.saldo


def agregar(cuenta, movimiento):
    """Agrega el movimiento por la relación (no por cuenta_id): así no queda dos veces en
    la lista en memoria si la colección se carga después de un autoflush."""
    cuenta.movimientos.append(movimiento)
    recalcular(cuenta)
    return movimiento


def cargar(cuenta, categoria, descripcion, cantidad, precio, usuario, servicio_id=None, receta_id=None, fecha=None):
    monto = (Decimal(precio) * cantidad).quantize(Decimal("0.01"))
    m = MovimientoCuenta(tipo="CARGO", categoria=categoria, descripcion=descripcion,
                         cantidad=cantidad, precio_unitario=precio, monto=monto, usuario=usuario,
                         servicio_id=servicio_id, receta_id=receta_id, fecha=fecha or datetime.now())
    return agregar(cuenta, m)


def cuenta_de_hospitalizacion(hospitalizacion_id):
    return CuentaPaciente.query.filter_by(hospitalizacion_id=hospitalizacion_id, tipo="HOSPITALIZACION").first()


def abrir_por_ingreso(h, usuario):
    """Se llama cuando Enfermería asigna la cama (la hospitalización pasa a ACTIVO)."""
    if cuenta_de_hospitalizacion(h.id):
        return None
    cuenta = CuentaPaciente(paciente_id=h.paciente_id, tipo="HOSPITALIZACION", hospitalizacion_id=h.id,
                            estado="ABIERTA", saldo=0, fecha_apertura=h.fecha_asignacion or datetime.now(),
                            abierta_por=usuario, tramo_inicio=h.fecha_asignacion or datetime.now(), tramo_area=h.sala)
    db.session.add(cuenta)
    db.session.flush()
    return cuenta


def _dias_cargados(cuenta):
    return sum(m.cantidad or 0 for m in cuenta.movimientos if m.categoria == "DIA_CAMA" and not m.anulado)


def _cargar_tramo(cuenta, fin, usuario, final=False):
    if not cuenta.tramo_inicio or not cuenta.tramo_area:
        return
    dias = max(0, (fin.date() - cuenta.tramo_inicio.date()).days)
    if final and dias == 0 and _dias_cargados(cuenta) == 0:
        dias = 1                                  # toda estancia cobra al menos un día
    if dias:
        servicio = tarifa_cama(cuenta.tramo_area)
        cargar(cuenta, "DIA_CAMA", f"{servicio.nombre} ({dias} {'día' if dias == 1 else 'días'})",
               dias, servicio.costo, usuario, servicio_id=servicio.id, fecha=fin)


def traslado(h, nueva_area, usuario):
    """Cierra el tramo del área anterior y empieza el de la nueva."""
    cuenta = cuenta_de_hospitalizacion(h.id)
    if cuenta is None or cuenta.estado != "ABIERTA":
        return
    ahora = datetime.now()
    if cuenta.tramo_area != nueva_area:
        _cargar_tramo(cuenta, ahora, usuario)
        cuenta.tramo_inicio, cuenta.tramo_area = ahora, nueva_area


def egreso(h, usuario):
    """Carga el último tramo de día cama. La cuenta queda ABIERTA para que Caja la revise y la cierre."""
    cuenta = cuenta_de_hospitalizacion(h.id)
    if cuenta is None or cuenta.estado != "ABIERTA":
        return
    _cargar_tramo(cuenta, h.fecha_egreso or datetime.now(), usuario, final=True)
    cuenta.tramo_inicio = cuenta.tramo_area = None


def cargar_receta(receta, usuario):
    """Si el paciente está ingresado, los medicamentos despachados van a su cuenta."""
    h = Hospitalizacion.query.filter_by(paciente_id=receta.paciente_id, estado="ACTIVO").first()
    if h is None:
        return None
    cuenta = cuenta_de_hospitalizacion(h.id)
    if cuenta is None or cuenta.estado != "ABIERTA":
        return None
    for d in receta.detalles:
        precio = d.medicamento.precio if d.medicamento and d.medicamento.precio is not None else Decimal("0")
        nombre = d.medicamento.nombre if d.medicamento else "Medicamento"
        presentacion = f" — {d.medicamento.presentacion}" if d.medicamento and d.medicamento.presentacion else ""
        cargar(cuenta, "MEDICAMENTO", f"{nombre}{presentacion} (receta No. {receta.id})", d.cantidad, precio,
               usuario, receta_id=receta.id)
    return cuenta


def estancia_en_curso(cuenta):
    """Día cama que corre y todavía no se ha cargado (se carga al traslado o al egreso)."""
    if cuenta.estado != "ABIERTA" or not cuenta.tramo_inicio or not cuenta.tramo_area:
        return None
    dias = max(0, (datetime.now().date() - cuenta.tramo_inicio.date()).days)
    if dias == 0 and _dias_cargados(cuenta) == 0:
        dias = 1
    codigo, tarifa = TARIFAS_CAMA.get(cuenta.tramo_area, ("CAMA-GEN", Decimal("150.00")))
    servicio = Servicio.query.filter_by(codigo=codigo).first()
    tarifa = Decimal(servicio.costo) if servicio else tarifa
    return {"area": cuenta.tramo_area, "dias": dias, "tarifa": float(tarifa), "monto": float(tarifa * dias)}
