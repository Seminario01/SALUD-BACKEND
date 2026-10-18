"""
Pruebas de la regla de vencimientos (lotes.resumen), sin servidor ni base de datos.

Las pruebas de prueba_auth.py no pueden crear un lote vencido (la API lo rechaza), así que
aquí se revisa con datos en memoria que las unidades vencidas no cuentan como disponibles.
Uso (desde SALUD-BACKEND):  venv/Scripts/python.exe pruebas/prueba_lotes.py
"""
import os
import sys
from datetime import date, timedelta
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lotes import DIAS_POR_VENCER, resumen  # noqa: E402

HOY = date(2026, 10, 18)
resultados = []


def dato(nombre, ok):
    resultados.append(ok)
    print(f"{'OK ' if ok else 'FALLA'}  {nombre}")


def lote(cantidad, dias):
    return SimpleNamespace(cantidad=cantidad, fecha_vencimiento=HOY + timedelta(days=dias))


m = SimpleNamespace(existencia=30)
r = resumen(m, [lote(6, -10), lote(5, 20), lote(10, 400)], HOY)
dato("6 vencidas no se cuentan: disponible 24 de 30", r["disponible"] == 24 and r["vencidas"] == 6)
dato("5 por vencer (dentro de los próximos días)", r["por_vencer"] == 5)
dato("9 unidades sin lote (30 - 21)", r["sin_lote"] == 9)
dato("el próximo vencimiento es el del lote vigente más cercano, no el vencido",
     r["proximo_vencimiento"] == (HOY + timedelta(days=20)).isoformat())

r = resumen(SimpleNamespace(existencia=12), [], HOY)
dato("sin lotes funciona como antes: todo disponible", r == {"sin_lote": 12, "vencidas": 0, "por_vencer": 0,
                                                             "disponible": 12, "proximo_vencimiento": None})
r = resumen(SimpleNamespace(existencia=4), [lote(4, DIAS_POR_VENCER)], HOY)
dato(f"un lote que vence justo a los {DIAS_POR_VENCER} días cuenta como por vencer", r["por_vencer"] == 4)
r = resumen(SimpleNamespace(existencia=4), [lote(4, 0)], HOY)
dato("un lote que vence hoy todavía se puede despachar", r["disponible"] == 4 and r["vencidas"] == 0)
r = resumen(SimpleNamespace(existencia=3), [lote(5, 30)], HOY)
dato("si los lotes suman más que la existencia, sin_lote no es negativo", r["sin_lote"] == 0 and r["disponible"] == 3)

print(f"\n{sum(resultados)}/{len(resultados)} pruebas OK")
sys.exit(0 if all(resultados) else 1)
