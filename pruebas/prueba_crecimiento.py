"""
Pruebas de crecimiento.py contra valores de las tablas oficiales de la OMS, sin servidor.
(Al generar datos/oms_crecimiento.json se comparó además TODA la tabla: cada fila y cada línea
de -4 a +4 DE de la OMS coincide.)
Uso (desde SALUD-BACKEND):  venv/Scripts/python.exe pruebas/prueba_crecimiento.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import crecimiento as C  # noqa: E402

resultados = []


def dato(nombre, ok):
    resultados.append(bool(ok))
    print(f"{'OK ' if ok else 'FALLA'}  {nombre}")


def z(ind, sexo, x, v):
    return C.puntaje_z(ind, sexo, x, v)


# Valores de las tablas ampliadas de la OMS (columnas -4, -3, -2 DE y mediana)
dato("niño al nacer: 3.3464 kg es la mediana (z = 0)", z("peso_edad", "M", 0, 3.3464) == 0)
dato("niño al nacer: 2.459 kg es -2 DE", z("peso_edad", "M", 0, 2.459) == -2)
dato("niño al nacer: 2.08 kg es -3 DE", z("peso_edad", "M", 0, 2.08) == -3)
dato("niño al nacer: 1.701 kg es -4 DE (con el ajuste de la OMS más allá de -3)", z("peso_edad", "M", 0, 1.701) == -4)
dato("niño de 1856 días: 14.175 kg es -2 DE", z("peso_edad", "M", 1856, 14.175) == -2)
dato("niña al nacer: 49.1477 cm es la mediana; 45.422 cm es -2 DE",
     z("talla_edad", "F", 0, 49.1477) == 0 and z("talla_edad", "F", 0, 45.422) == -2)
dato("niña de 1856 días: 100.353 cm es -2 DE", z("talla_edad", "F", 1856, 100.353) == -2)
dato("niño de 45 cm: 2.043 kg es -2 DE y 1.71 kg es -4 DE",
     z("peso_longitud", "M", 45, 2.043) == -2 and z("peso_longitud", "M", 45, 1.71) == -4)
dato("niña de 65 cm de talla: 6.071 kg es -2 DE y 5.095 kg es -4 DE",
     z("peso_talla", "F", 65, 6.071) == -2 and z("peso_talla", "F", 65, 5.095) == -4)
dato("entre dos filas (45.05 cm) se interpola", -2.05 < z("peso_longitud", "M", 45.05, 2.05) < -1.95)
dato("fuera de la tabla no hay z (6 años, 30 cm, 125 cm de talla)", z("peso_edad", "M", 2200, 18) is None
     and z("peso_longitud", "F", 30, 1) is None and z("peso_talla", "F", 125, 20) is None)
dato("la curva de -2 DE devuelve el valor de la tabla", C.curva("peso_edad", "M", -2, [0])[0]["y"] == 2.46)
dato("la curva de -4 DE usa el ajuste de la OMS", abs(C.curva("peso_edad", "M", -4, [0])[0]["y"] - 1.70) < 0.01)

# Clasificación (puntos de corte de la OMS)
e = C.evaluar("M", 365, peso=7.0, talla=69.0)        # 1 año: bajo peso y talla baja
dato("niño de 1 año con 7 kg y 69 cm: bajo peso y retardo del crecimiento",
     e["peso_edad"]["nivel"] in ("alerta", "grave") and e["talla_edad"]["texto"].startswith("Retardo"))
dato("antes de 2 años se usa peso para la longitud", "peso_longitud" in e and "peso_talla" not in e)
e = C.evaluar("F", 3 * 365, peso=14.0, talla=95.0)    # 3 años, normal
dato("niña de 3 años con 14 kg y 95 cm: todo normal y usa peso para la talla",
     all(i["nivel"] == "normal" for i in e.values()) and "peso_talla" in e)
e = C.evaluar("M", 700, peso=7.0, talla=80.0)
dato("peso muy bajo para la longitud: desnutrición aguda", e["peso_longitud"]["texto"].startswith("Desnutrición aguda"))
e = C.evaluar("F", 1000, peso=19.0, talla=90.0)
dato("peso muy alto para la talla: sobrepeso u obesidad", e["peso_talla"]["texto"] in ("Sobrepeso", "Obesidad"))
dato("solo con peso: solo peso para la edad", set(C.evaluar("M", 200, peso=7.5)) == {"peso_edad"})
dato("mayor de 5 años o sin sexo: nada", C.evaluar("M", 2000, 15, 100) == {} and C.evaluar("X", 100, 6, 60) == {})

print(f"\n{sum(resultados)}/{len(resultados)} pruebas OK")
sys.exit(0 if all(resultados) else 1)
