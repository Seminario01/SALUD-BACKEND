"""
Alertas para la seguridad del paciente (sin base de datos: se prueban en pruebas/prueba_alertas.py).

  - alertas_signos(nota): signos vitales fuera del rango normal de un adulto.
  - alergias_en_conflicto(alergias, medicamento): si un medicamento choca con las alergias
    registradas del paciente (por nombre o por familia: penicilinas, sulfas, AINE...).
  - parecido_nombre(a, b): para avisar de un paciente posiblemente duplicado.
  - interacciones(nuevos, activos): medicamentos que no conviene combinar (sangrado, potasio alto...).
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


# ---------------------------------------------------------------------------
# Interacciones entre medicamentos (apoyo al médico: avisa, no prohíbe)
#
# Grupos de principios activos (minúsculas y sin tildes). Se busca solo en el NOMBRE del
# medicamento (la descripción puede mencionar otros fármacos, como "no combinar con warfarina").
GRUPOS = {
    "aine": [m for m in FAMILIAS["aine"] if m not in FAMILIAS["aspirina"]],
    "aspirina": FAMILIAS["aspirina"],
    "anticoagulante": ["warfarina", "acenocumarol", "rivaroxaban", "apixaban", "dabigatran", "heparina",
                       "enoxaparina"],
    "clopidogrel": ["clopidogrel"],
    "ieca": ["enalapril", "captopril", "lisinopril", "ramipril"],
    "ara2": ["losartan", "valsartan", "irbesartan", "telmisartan", "candesartan"],
    "ahorrador_potasio": ["espironolactona", "eplerenona", "amilorida", "triamtereno"],
    "potasio": ["cloruro de potasio", "potasio"],
    "isrs": ["fluoxetina", "sertralina", "paroxetina", "citalopram", "escitalopram"],
    "tramadol": ["tramadol"],
    "opioide": FAMILIAS["opioide"],
    "benzodiacepina": ["diazepam", "clonazepam", "alprazolam", "lorazepam", "midazolam", "bromazepam"],
    "estatina": ["simvastatina", "lovastatina", "atorvastatina"],
    "macrolido_inhibidor": ["claritromicina", "eritromicina"],
    "quinolona": FAMILIAS["quinolona"],
    "quelante": ["sulfato ferroso", "hierro", "hidroxido de aluminio", "hidroxido de magnesio",
                 "carbonato de calcio", "calcio", "antiacido"],
    "nitrato": ["nitroglicerina", "dinitrato de isosorbida", "mononitrato de isosorbida", "isosorbida"],
    "sildenafil": ["sildenafil", "tadalafil", "vardenafil"],
    "digoxina": ["digoxina"],
    "amiodarona": ["amiodarona"],
    "metronidazol": ["metronidazol"],
    "corticoide": ["prednisona", "prednisolona", "dexametasona", "hidrocortisona", "metilprednisolona",
                   "betametasona"],
    "omeprazol": ["omeprazol", "esomeprazol"],
}
GRAVE, MODERADA = "grave", "moderada"
# (grupo, grupo) -> (severidad, qué puede pasar)
INTERACCIONES = {
    ("anticoagulante", "aine"): (GRAVE, "Riesgo alto de sangrado"),
    ("anticoagulante", "aspirina"): (GRAVE, "Riesgo alto de sangrado"),
    ("anticoagulante", "clopidogrel"): (GRAVE, "Riesgo alto de sangrado"),
    ("anticoagulante", "metronidazol"): (GRAVE, "Aumenta el efecto del anticoagulante (sangrado)"),
    ("anticoagulante", "isrs"): (MODERADA, "Aumenta el riesgo de sangrado"),
    ("isrs", "tramadol"): (GRAVE, "Riesgo de síndrome serotoninérgico y convulsiones"),
    ("opioide", "benzodiacepina"): (GRAVE, "Depresión respiratoria y sedación profunda"),
    ("sildenafil", "nitrato"): (GRAVE, "Caída grave de la presión arterial"),
    ("digoxina", "amiodarona"): (GRAVE, "Sube la digoxina en sangre (toxicidad, arritmias)"),
    ("estatina", "macrolido_inhibidor"): (GRAVE, "Riesgo de daño muscular (rabdomiólisis)"),
    ("ieca", "ahorrador_potasio"): (GRAVE, "Riesgo de potasio alto (hiperpotasemia)"),
    ("ara2", "ahorrador_potasio"): (GRAVE, "Riesgo de potasio alto (hiperpotasemia)"),
    ("ieca", "potasio"): (GRAVE, "Riesgo de potasio alto (hiperpotasemia)"),
    ("ara2", "potasio"): (GRAVE, "Riesgo de potasio alto (hiperpotasemia)"),
    ("ieca", "ara2"): (MODERADA, "Doble bloqueo: potasio alto, presión baja y daño renal"),
    ("aine", "ieca"): (MODERADA, "Menos efecto contra la presión y riesgo para el riñón"),
    ("aine", "ara2"): (MODERADA, "Menos efecto contra la presión y riesgo para el riñón"),
    ("aine", "aspirina"): (MODERADA, "Más riesgo de sangrado o úlcera en el estómago"),
    ("aine", "corticoide"): (MODERADA, "Más riesgo de úlcera y sangrado en el estómago"),
    ("aine", "isrs"): (MODERADA, "Más riesgo de sangrado digestivo"),
    ("clopidogrel", "omeprazol"): (MODERADA, "El omeprazol reduce el efecto del clopidogrel"),
    ("quinolona", "quelante"): (MODERADA, "Se absorbe menos el antibiótico: tomarlos con 2 a 4 horas de diferencia"),
}
# Dos medicamentos del mismo grupo en el paciente = duplicidad
DUPLICIDAD = {"aine": "dos antiinflamatorios (AINE)", "ieca": "dos IECA", "ara2": "dos ARA II",
              "isrs": "dos antidepresivos ISRS", "benzodiacepina": "dos benzodiacepinas",
              "anticoagulante": "dos anticoagulantes", "estatina": "dos estatinas", "opioide": "dos opioides"}


def grupos_de(nombre):
    """Grupos de interacción a los que pertenece un medicamento (por su nombre)."""
    texto = normalizar(nombre)
    return {g for g, miembros in GRUPOS.items() if any(_contiene(texto, m) for m in miembros)}


def interacciones(nuevos, activos=()):
    """Interacciones de los medicamentos `nuevos` (nombres) entre sí y con los `activos`
    (pares (nombre, origen), p. ej. ("Ibuprofeno", "receta #12 del 03/10")).
    Devuelve [{medicamento, con, origen, severidad, texto}], primero las graves."""
    nuevos = list(dict.fromkeys(nuevos))
    otros = [(n, "esta receta") for n in nuevos] + list(activos)
    hallados, vistos = [], set()
    for i, nombre in enumerate(nuevos):
        g1 = grupos_de(nombre)
        for j, (otro, origen) in enumerate(otros):
            if origen == "esta receta" and j <= i:      # cada par de la misma receta una sola vez
                continue
            if normalizar(otro) == normalizar(nombre):
                continue                                 # el mismo medicamento: no es interacción
            g2 = grupos_de(otro)
            for a in g1:
                for b in g2:
                    regla = INTERACCIONES.get((a, b)) or INTERACCIONES.get((b, a))
                    if not regla and a == b and a in DUPLICIDAD:
                        regla = (MODERADA, f"Duplicidad: {DUPLICIDAD[a]} a la vez")
                    clave = (normalizar(nombre), normalizar(otro), regla and regla[1])
                    if regla and clave not in vistos:
                        vistos.add(clave)
                        hallados.append({"medicamento": nombre, "con": otro, "origen": origen,
                                         "severidad": regla[0], "texto": regla[1]})
    return sorted(hallados, key=lambda h: h["severidad"] != GRAVE)
