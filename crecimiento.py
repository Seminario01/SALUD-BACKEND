"""
Crecimiento infantil con los Patrones de Crecimiento Infantil de la OMS (2006), de 0 a 5 años.

datos/oms_crecimiento.json se generó de las tablas ampliadas oficiales de puntuación z
(who.int/tools/child-growth-standards): L, M y S por día de edad (0 a 1856 días) o por cada 0.1 cm
de longitud/talla. pruebas/prueba_crecimiento.py lo compara con las columnas -4/-3/-2 DE de la OMS.

  puntaje_z(indicador, sexo, x, valor)   puntuación z (método LMS; en los de peso, con el ajuste
                                         de la OMS más allá de ±3 DE)
  evaluar(sexo, dias, peso, talla)       z de peso/edad, talla/edad y peso/talla con su clasificación
  curva(indicador, sexo, z, puntos)      valores de una línea de referencia (para las gráficas)
"""
import json
import math
import os

_RUTA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "datos", "oms_crecimiento.json")
with open(_RUTA, encoding="utf-8") as _f:
    _OMS = json.load(_f)

FUENTE = _OMS["fuente"]
INDICADORES = _OMS["indicadores"]
DIAS_MAX = 1856                      # 5 años
DIAS_LONGITUD = 731                  # antes de 2 años se mide acostado (longitud); después, de pie (talla)
DE_PESO = ("peso_edad", "peso_longitud", "peso_talla")


def _lms(indicador, sexo, x):
    """L, M y S en x (días o cm), interpolando entre los puntos de la tabla; None fuera de rango."""
    t = INDICADORES[indicador]
    datos = t[sexo]
    pos = (x - t["inicio"]) / t["paso"]
    if pos < -1e-9 or pos > len(datos["M"]) - 1 + 1e-9:
        return None
    i = min(int(math.floor(pos + 1e-9)), len(datos["M"]) - 2)
    fr = max(0.0, min(1.0, pos - i))
    return tuple(datos[k][i] + (datos[k][i + 1] - datos[k][i]) * fr for k in ("L", "M", "S"))


def _valor_en_z(L, M, S, z):
    return M * (1 + L * S * z) ** (1 / L) if L != 0 else M * math.exp(S * z)


def puntaje_z(indicador, sexo, x, valor):
    lms = _lms(indicador, sexo, x)
    if lms is None or valor is None or valor <= 0:
        return None
    L, M, S = lms
    z = ((valor / M) ** L - 1) / (L * S) if L != 0 else math.log(valor / M) / S
    # Ajuste de la OMS para los indicadores de peso más allá de ±3 DE (la distribución se estira)
    if indicador in DE_PESO and abs(z) > 3:
        if z > 3:
            de3, de2 = _valor_en_z(L, M, S, 3), _valor_en_z(L, M, S, 2)
            z = 3 + (valor - de3) / (de3 - de2)
        else:
            de3, de2 = _valor_en_z(L, M, S, -3), _valor_en_z(L, M, S, -2)
            z = -3 + (valor - de3) / (de2 - de3)
    return round(z, 2)


def curva(indicador, sexo, z, puntos):
    """Valores de la línea de z (por ejemplo -2) en cada punto x (días o cm)."""
    salida = []
    for x in puntos:
        lms = _lms(indicador, sexo, x)
        if lms is None:
            continue
        L, M, S = lms
        if indicador in DE_PESO and abs(z) > 3:
            signo = 1 if z > 0 else -1
            de3, de2 = _valor_en_z(L, M, S, 3 * signo), _valor_en_z(L, M, S, 2 * signo)
            valor = de3 + (abs(z) - 3) * (de3 - de2) * signo * signo
        else:
            valor = _valor_en_z(L, M, S, z)
        salida.append({"x": x, "y": round(valor, 2)})
    return salida


# Clasificación con los puntos de corte de la OMS (los que usa el MSPAS en Guatemala)
def _talla_edad(z):
    if z < -3:
        return "grave", "Retardo severo del crecimiento (desnutrición crónica severa)"
    if z < -2:
        return "alerta", "Retardo del crecimiento (desnutrición crónica)"
    return "normal", "Talla adecuada para la edad"


def _peso_talla(z):
    if z < -3:
        return "grave", "Desnutrición aguda severa"
    if z < -2:
        return "alerta", "Desnutrición aguda moderada"
    if z > 3:
        return "grave", "Obesidad"
    if z > 2:
        return "alerta", "Sobrepeso"
    if z > 1:
        return "vigilar", "Riesgo de sobrepeso"
    return "normal", "Peso adecuado para la talla"


def _peso_edad(z):
    if z < -3:
        return "grave", "Bajo peso severo"
    if z < -2:
        return "alerta", "Bajo peso"
    return "normal", "Peso adecuado para la edad"


def evaluar(sexo, dias, peso=None, talla=None):
    """Indicadores de una medición. sexo "M"/"F"; dias de edad; peso en kg; talla en cm
    (longitud acostado antes de 2 años, de pie después, como indica la OMS)."""
    if sexo not in ("M", "F") or dias is None or not 0 <= dias <= DIAS_MAX:
        return {}
    resultado = {}

    def agregar(clave, z, clasificar):
        if z is not None:
            nivel, texto = clasificar(z)
            resultado[clave] = {"z": z, "nivel": nivel, "texto": texto, "nombre": INDICADORES[clave]["nombre"]}

    if peso:
        agregar("peso_edad", puntaje_z("peso_edad", sexo, dias, peso), _peso_edad)
    if talla:
        agregar("talla_edad", puntaje_z("talla_edad", sexo, dias, talla), _talla_edad)
    if peso and talla:
        tabla = "peso_longitud" if dias < DIAS_LONGITUD else "peso_talla"
        agregar(tabla, puntaje_z(tabla, sexo, talla, peso), _peso_talla)
    return resultado
