"""
Alertas para la seguridad del paciente (sin base de datos: se prueban en pruebas/prueba_alertas.py).

  - alertas_signos(nota): signos vitales fuera del rango normal de un adulto.
  - alergias_en_conflicto(alergias, medicamento): si un medicamento choca con las alergias
    registradas del paciente (por nombre o por familia: penicilinas, sulfas, AINE...).
  - parecido_nombre(a, b): para avisar de un paciente posiblemente duplicado.
"""
import re
import unicodedata
from difflib import SequenceMatcher

# Rangos normales de referencia en adultos (los mismos que la franja gris de las gráficas)
TEMPERATURA = (36.1, 37.5)
FRECUENCIA = (60, 100)
SATURACION_MINIMA = 95
SISTOLICA = (90, 139)
DIASTOLICA = (60, 89)


def _alerta(signo, nivel, texto):
    return {"signo": signo, "nivel": nivel, "texto": texto}


def alertas_signos(nota):
    """Lista de alertas de una nota (objeto o dict con presion, temperatura, frecuencia_cardiaca, saturacion)."""
    leer = nota.get if isinstance(nota, dict) else (lambda campo: getattr(nota, campo, None))
    alertas = []
    presion = leer("presion")
    if presion and re.fullmatch(r"\d{2,3}/\d{2,3}", presion):
        sis, dia = (int(x) for x in presion.split("/"))
        if sis > SISTOLICA[1] or dia > DIASTOLICA[1]:
            alertas.append(_alerta("presion", "alto", f"Presión alta ({presion} mmHg)"))
        elif sis < SISTOLICA[0] or dia < DIASTOLICA[0]:
            alertas.append(_alerta("presion", "bajo", f"Presión baja ({presion} mmHg)"))
    temperatura = leer("temperatura")
    if temperatura is not None:
        t = float(temperatura)
        if t > TEMPERATURA[1]:
            alertas.append(_alerta("temperatura", "alto", f"Fiebre ({t:.1f} °C)"))
        elif t < TEMPERATURA[0]:
            alertas.append(_alerta("temperatura", "bajo", f"Temperatura baja ({t:.1f} °C)"))
    fc = leer("frecuencia_cardiaca")
    if fc is not None:
        if fc > FRECUENCIA[1]:
            alertas.append(_alerta("frecuencia_cardiaca", "alto", f"Pulso alto ({fc} lpm)"))
        elif fc < FRECUENCIA[0]:
            alertas.append(_alerta("frecuencia_cardiaca", "bajo", f"Pulso bajo ({fc} lpm)"))
    sat = leer("saturacion")
    if sat is not None and sat < SATURACION_MINIMA:
        alertas.append(_alerta("saturacion", "bajo", f"Saturación baja ({sat} %)"))
    return alertas


def normalizar(texto):
    """minúsculas, sin tildes y con un solo espacio entre palabras."""
    sin_tildes = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", sin_tildes.lower()).split())


# Familia de la alergia -> principios activos que la provocan (en minúsculas y sin tildes)
FAMILIAS = {
    "penicilina": ["penicilina", "amoxicilina", "ampicilina", "dicloxacilina", "oxacilina", "piperacilina",
                   "bencilpenicilina", "penicilinas", "betalactamico"],
    "cefalosporina": ["cefalexina", "cefadroxilo", "cefuroxima", "ceftriaxona", "cefotaxima", "cefixima",
                      "cefazolina", "cefepima", "cefalosporinas"],
    "sulfa": ["sulfametoxazol", "sulfadiazina", "sulfasalazina", "trimetoprim sulfametoxazol", "sulfas",
              "cotrimoxazol"],
    "aine": ["ibuprofeno", "naproxeno", "diclofenaco", "ketorolaco", "aspirina", "acido acetilsalicilico",
             "meloxicam", "piroxicam", "indometacina", "ketoprofeno", "celecoxib", "aines"],
    "aspirina": ["aspirina", "acido acetilsalicilico", "asa"],
    "dipirona": ["dipirona", "metamizol"],
    "macrolido": ["eritromicina", "azitromicina", "claritromicina", "macrolidos"],
    "quinolona": ["ciprofloxacina", "levofloxacina", "moxifloxacina", "norfloxacina", "quinolonas"],
    "tetraciclina": ["tetraciclina", "doxiciclina", "minociclina", "tetraciclinas"],
    "opioide": ["morfina", "tramadol", "codeina", "oxicodona", "fentanilo", "opioides"],
    "yodo": ["yodo", "povidona yodada", "yodopovidona"],
}
# Sinónimos que la gente escribe en el campo de alergias -> familia
SINONIMOS = {"penicilinas": "penicilina", "betalactamicos": "penicilina", "cefalosporinas": "cefalosporina",
             "sulfas": "sulfa", "sulfamidas": "sulfa", "sulfonamidas": "sulfa", "aines": "aine",
             "antiinflamatorios": "aine", "antiinflamatorio": "aine", "metamizol": "dipirona",
             "macrolidos": "macrolido", "quinolonas": "quinolona", "tetraciclinas": "tetraciclina",
             "opioides": "opioide", "opiaceos": "opioide", "acido acetilsalicilico": "aspirina"}
SIN_ALERGIAS = {"ninguna", "ninguno", "niega", "no", "no refiere", "niega alergias", "no conocidas",
                "ninguna conocida", "sin alergias", "no tiene", "nkda", "n a", "na"}


def terminos_alergia(alergias):
    """Separa el texto de alergias ("Penicilina, AINE; látex") en términos normalizados."""
    terminos = []
    for parte in re.split(r"[,;\n/]+| y ", alergias or ""):
        t = normalizar(parte)
        t = re.sub(r"^(alergia|alergico|alergica)( a| al)? ", "", t)
        if len(t) >= 3 and t not in SIN_ALERGIAS:
            terminos.append(t)
    return terminos


def _contiene(texto, palabra):
    return re.search(rf"(?<![a-z0-9]){re.escape(palabra)}(?![a-z0-9])", texto) is not None


def alergias_en_conflicto(alergias, medicamento):
    """Alergias del paciente que chocan con el medicamento. `medicamento`: objeto o dict con nombre,
    presentacion y descripcion. Devuelve la lista de alergias (como las escribió el personal)."""
    leer = medicamento.get if isinstance(medicamento, dict) else (lambda campo: getattr(medicamento, campo, None))
    texto_med = normalizar(" ".join(filter(None, [leer("nombre"), leer("presentacion"), leer("descripcion")])))
    if not texto_med:
        return []
    choques = []
    for termino in terminos_alergia(alergias):
        familia = SINONIMOS.get(termino, termino)
        candidatos = {termino, familia, *FAMILIAS.get(familia, [])}
        # "Alergia a la amoxicilina": también avisa con otras penicilinas
        for nombre_familia, miembros in FAMILIAS.items():
            if termino in miembros:
                candidatos.update(miembros)
                candidatos.add(nombre_familia)
        if any(len(c) >= 3 and _contiene(texto_med, c) for c in candidatos):
            choques.append(termino)
    return choques


def parecido_nombre(a, b):
    """0..1: qué tanto se parecen dos nombres (sin importar tildes, mayúsculas ni el orden de las palabras)."""
    na, nb = normalizar(a), normalizar(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    pa, pb = set(na.split()), set(nb.split())
    # "María García" frente a "María José García López": todas las palabras del corto están en el largo
    if min(len(pa), len(pb)) >= 2 and (pa <= pb or pb <= pa):
        return 0.9
    return max(SequenceMatcher(None, na, nb).ratio(),
               SequenceMatcher(None, " ".join(sorted(pa)), " ".join(sorted(pb))).ratio())
