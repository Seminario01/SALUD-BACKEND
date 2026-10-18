"""
Lotes y vencimientos de medicamentos.

- La existencia total del medicamento sigue siendo medicamentos.existencia (no cambia
  nada de lo anterior). Los lotes solo dicen de qué fecha de vencimiento es cada unidad.
- "Sin lote" = existencia - suma de los lotes: el inventario que ya había antes de los lotes.
- Al despachar se descuenta primero el lote que vence antes (FEFO) y NUNCA uno vencido;
  después, lo que no tiene lote. Las unidades vencidas no cuentan como disponibles.
"""
from datetime import date, timedelta

from extensions import db
from models import LoteMedicamento

DIAS_POR_VENCER = 60


def lotes_con_saldo(medicamento_ids=None):
    """{medicamento_id: [lotes con cantidad > 0, del que vence antes al último]}"""
    q = LoteMedicamento.query.filter(LoteMedicamento.cantidad > 0)
    if medicamento_ids is not None:
        q = q.filter(LoteMedicamento.medicamento_id.in_(list(medicamento_ids)))
    agrupados = {}
    for l in q.order_by(LoteMedicamento.fecha_vencimiento, LoteMedicamento.id).all():
        agrupados.setdefault(l.medicamento_id, []).append(l)
    return agrupados


def resumen(m, lotes, hoy=None):
    """Cuántas unidades están vencidas, por vencer y disponibles."""
    hoy = hoy or date.today()
    limite = hoy + timedelta(days=DIAS_POR_VENCER)
    en_lotes = sum(l.cantidad for l in lotes)
    vencidas = sum(l.cantidad for l in lotes if l.fecha_vencimiento < hoy)
    por_vencer = sum(l.cantidad for l in lotes if hoy <= l.fecha_vencimiento <= limite)
    vigentes = [l for l in lotes if l.fecha_vencimiento >= hoy]
    return {
        "sin_lote": max(0, m.existencia - en_lotes),
        "vencidas": vencidas,
        "por_vencer": por_vencer,
        "disponible": max(0, m.existencia - vencidas),
        "proximo_vencimiento": vigentes[0].fecha_vencimiento.isoformat() if vigentes else None,
    }


def disponible(m, hoy=None):
    """Unidades que se pueden despachar (sin contar las vencidas)."""
    return resumen(m, lotes_con_saldo([m.id]).get(m.id, []), hoy)["disponible"]


def descontar(m, cantidad, hoy=None):
    """Descuenta `cantidad` de los lotes vigentes (FEFO) y luego de lo sin lote.
    No toca m.existencia (lo hace quien llama). Devuelve el detalle "lote X: n" para el kardex."""
    hoy = hoy or date.today()
    lotes = [l for l in LoteMedicamento.query.filter(LoteMedicamento.medicamento_id == m.id, LoteMedicamento.cantidad > 0)
             .order_by(LoteMedicamento.fecha_vencimiento, LoteMedicamento.id).with_for_update().all()]
    detalle, falta = [], cantidad
    for l in lotes:
        if falta <= 0:
            break
        if l.fecha_vencimiento < hoy:
            continue
        toma = min(l.cantidad, falta)
        l.cantidad -= toma
        falta -= toma
        detalle.append(f"lote {l.numero_lote or l.id} (vence {l.fecha_vencimiento.strftime('%d/%m/%Y')}): {toma}")
    if falta > 0 and lotes:
        detalle.append(f"sin lote: {falta}")
    return ", ".join(detalle)


def ajustar_lotes_a_existencia(m):
    """Si un ajuste negativo deja menos existencia que la suma de los lotes, se recortan los lotes
    (primero los vencidos, luego los que vencen antes) para que nunca sumen más que la existencia."""
    lotes = LoteMedicamento.query.filter(LoteMedicamento.medicamento_id == m.id, LoteMedicamento.cantidad > 0) \
        .order_by(LoteMedicamento.fecha_vencimiento, LoteMedicamento.id).all()
    sobra = sum(l.cantidad for l in lotes) - m.existencia
    for l in lotes:
        if sobra <= 0:
            break
        quita = min(l.cantidad, sobra)
        l.cantidad -= quita
        sobra -= quita


def serializar(l, hoy=None):
    hoy = hoy or date.today()
    dias = (l.fecha_vencimiento - hoy).days
    return {
        "id": l.id, "numero_lote": l.numero_lote, "fecha_vencimiento": l.fecha_vencimiento.isoformat(),
        "cantidad_inicial": l.cantidad_inicial, "cantidad": l.cantidad,
        "fecha_ingreso": l.fecha_ingreso.isoformat(timespec="minutes") if l.fecha_ingreso else None,
        "usuario": l.usuario, "dias_para_vencer": dias,
        "estado": "VENCIDO" if dias < 0 else "POR_VENCER" if dias <= DIAS_POR_VENCER else "VIGENTE",
    }
