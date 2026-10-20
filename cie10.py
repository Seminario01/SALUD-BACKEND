"""
Catálogo CIE-10 (Clasificación Internacional de Enfermedades, 10.ª revisión, OMS/OPS) para los
diagnósticos del expediente. No es la lista completa (más de 12 000 códigos): son los diagnósticos
más frecuentes en consulta externa, emergencia y encamamiento de un hospital general.

  buscar(texto)        códigos que coinciden por código ("J0", "I10") o por palabras ("hiper arter")
  descripcion(codigo)  el nombre del código, o None si no está en el catálogo
  normalizar_codigo()  "j00", " J00 " -> "J00"; "E11.9" se queda igual
"""
import re

from alertas_clinicas import normalizar

CAPITULOS = [
    ("A00", "B99", "Infecciosas y parasitarias"), ("C00", "D48", "Tumores"),
    ("D50", "D89", "Sangre e inmunidad"), ("E00", "E90", "Endocrinas y metabólicas"),
    ("F00", "F99", "Mentales y del comportamiento"), ("G00", "G99", "Sistema nervioso"),
    ("H00", "H59", "Ojo"), ("H60", "H95", "Oído"), ("I00", "I99", "Circulatorio"),
    ("J00", "J99", "Respiratorio"), ("K00", "K93", "Digestivo"), ("L00", "L99", "Piel"),
    ("M00", "M99", "Osteomuscular"), ("N00", "N99", "Genitourinario"),
    ("O00", "O99", "Embarazo, parto y puerperio"), ("P00", "P96", "Perinatal"),
    ("Q00", "Q99", "Malformaciones congénitas"), ("R00", "R99", "Síntomas y signos"),
    ("S00", "T98", "Traumatismos y envenenamientos"), ("V01", "Y98", "Causas externas"),
    ("Z00", "Z99", "Contacto con los servicios de salud"), ("U00", "U85", "Códigos para situaciones especiales"),
]

CATALOGO = [
    # --- Infecciosas y parasitarias
    ("A01.0", "Fiebre tifoidea"), ("A04.9", "Infección intestinal bacteriana, no especificada"),
    ("A06.0", "Disentería amebiana aguda"), ("A08.4", "Infección intestinal viral, no especificada"),
    ("A09", "Diarrea y gastroenteritis de presunto origen infeccioso"), ("A15.0", "Tuberculosis del pulmón"),
    ("A16.2", "Tuberculosis de pulmón, sin confirmación bacteriológica"), ("A37.9", "Tos ferina, no especificada"),
    ("A46", "Erisipela"), ("A63.0", "Verrugas anogenitales (venéreas)"), ("A90", "Dengue clásico"),
    ("A91", "Fiebre del dengue hemorrágico"), ("A92.0", "Enfermedad por virus Chikungunya"),
    ("A92.5", "Enfermedad por virus Zika"), ("B00.9", "Infección debida al virus del herpes, no especificada"),
    ("B01.9", "Varicela sin complicaciones"), ("B02.9", "Herpes zóster sin complicaciones"),
    ("B05.9", "Sarampión sin complicaciones"), ("B07", "Verrugas víricas"), ("B08.4", "Enfermedad de manos, pies y boca"),
    ("B15.9", "Hepatitis aguda tipo A, sin coma hepático"), ("B20", "Enfermedad por VIH con enfermedades infecciosas"),
    ("B24", "Enfermedad por virus de la inmunodeficiencia humana (VIH), sin otra especificación"),
    ("B26.9", "Parotiditis sin complicaciones"), ("B34.9", "Infección viral, no especificada"),
    ("B35.3", "Tiña del pie"), ("B35.4", "Tiña del cuerpo"), ("B36.0", "Pitiriasis versicolor"),
    ("B37.0", "Estomatitis candidiásica"), ("B37.3", "Candidiasis de la vulva y de la vagina"),
    ("B50.9", "Paludismo por Plasmodium falciparum, sin otra especificación"), ("B54", "Paludismo, no especificado"),
    ("B77.9", "Ascariasis, no especificada"), ("B82.9", "Parasitosis intestinal, sin otra especificación"),
    ("B86", "Escabiosis"), ("U07.1", "COVID-19, virus identificado"), ("U07.2", "COVID-19, virus no identificado"),
    # --- Tumores
    ("C50.9", "Tumor maligno de la mama, parte no especificada"), ("C53.9", "Tumor maligno del cuello del útero"),
    ("C61", "Tumor maligno de la próstata"), ("C16.9", "Tumor maligno del estómago, parte no especificada"),
    ("D25.9", "Leiomioma del útero, sin otra especificación"),
    # --- Sangre
    ("D50.9", "Anemia por deficiencia de hierro, sin otra especificación"), ("D52.9", "Anemia por deficiencia de folatos"),
    ("D64.9", "Anemia de tipo no especificado"), ("D69.6", "Trombocitopenia, no especificada"),
    # --- Endocrinas y metabólicas
    ("E03.9", "Hipotiroidismo, no especificado"), ("E05.9", "Tirotoxicosis (hipertiroidismo), sin otra especificación"),
    ("E10.9", "Diabetes mellitus tipo 1, sin complicaciones"), ("E11.9", "Diabetes mellitus tipo 2, sin complicaciones"),
    ("E11.6", "Diabetes mellitus tipo 2, con otras complicaciones especificadas"),
    ("E11.5", "Diabetes mellitus tipo 2, con complicaciones circulatorias periféricas (pie diabético)"),
    ("E14.9", "Diabetes mellitus, no especificada, sin complicaciones"), ("E16.2", "Hipoglicemia, no especificada"),
    ("E43", "Desnutrición proteicocalórica severa, no especificada"), ("E44.0", "Desnutrición proteicocalórica moderada"),
    ("E44.1", "Desnutrición proteicocalórica leve"), ("E46", "Desnutrición proteicocalórica, no especificada"),
    ("E66.9", "Obesidad, no especificada"), ("E78.0", "Hipercolesterolemia pura"), ("E78.5", "Hiperlipidemia, no especificada"),
    ("E86", "Deshidratación"), ("E87.6", "Hipopotasemia"), ("E79.0", "Hiperuricemia sin signos de artritis"),
    # --- Mentales
    ("F10.2", "Trastornos por uso de alcohol: síndrome de dependencia"), ("F20.9", "Esquizofrenia, no especificada"),
    ("F32.9", "Episodio depresivo, no especificado"), ("F33.9", "Trastorno depresivo recurrente, no especificado"),
    ("F41.0", "Trastorno de pánico"), ("F41.1", "Trastorno de ansiedad generalizada"),
    ("F41.9", "Trastorno de ansiedad, no especificado"), ("F43.1", "Trastorno de estrés postraumático"),
    ("F51.0", "Insomnio no orgánico"), ("F90.0", "Trastorno de la actividad y de la atención (TDAH)"),
    # --- Sistema nervioso
    ("G40.9", "Epilepsia, tipo no especificado"), ("G43.9", "Migraña, no especificada"),
    ("G44.2", "Cefalea debida a tensión"), ("G45.9", "Isquemia cerebral transitoria, sin otra especificación"),
    ("G47.0", "Trastornos del inicio y del mantenimiento del sueño (insomnio)"), ("G51.0", "Parálisis de Bell"),
    ("G56.0", "Síndrome del túnel carpiano"), ("G62.9", "Polineuropatía, no especificada"),
    # --- Ojo y oído
    ("H10.9", "Conjuntivitis, no especificada"), ("H00.0", "Orzuelo y otras inflamaciones profundas del párpado"),
    ("H25.9", "Catarata senil, no especificada"), ("H40.9", "Glaucoma, no especificado"),
    ("H52.4", "Presbicia"), ("H60.9", "Otitis externa, sin otra especificación"),
    ("H61.2", "Cerumen impactado"), ("H65.9", "Otitis media no supurativa, sin otra especificación"),
    ("H66.9", "Otitis media, no especificada"), ("H81.1", "Vértigo paroxístico benigno"),
    # --- Circulatorio
    ("I10", "Hipertensión esencial (primaria)"), ("I11.9", "Enfermedad cardíaca hipertensiva sin insuficiencia cardíaca"),
    ("I20.9", "Angina de pecho, no especificada"), ("I21.9", "Infarto agudo del miocardio, sin otra especificación"),
    ("I25.9", "Enfermedad isquémica crónica del corazón, no especificada"), ("I48", "Fibrilación y aleteo auricular"),
    ("I50.0", "Insuficiencia cardíaca congestiva"), ("I50.9", "Insuficiencia cardíaca, no especificada"),
    ("I63.9", "Infarto cerebral, no especificado"), ("I64", "Accidente vascular encefálico agudo, no especificado"),
    ("I80.2", "Flebitis y tromboflebitis de vasos profundos de miembros inferiores"),
    ("I83.9", "Venas varicosas de los miembros inferiores sin úlcera ni inflamación"),
    ("I84.9", "Hemorroides no especificadas, sin complicación"), ("I95.9", "Hipotensión, no especificada"),
    # --- Respiratorio
    ("J00", "Rinofaringitis aguda (resfriado común)"), ("J01.9", "Sinusitis aguda, no especificada"),
    ("J02.9", "Faringitis aguda, no especificada"), ("J03.9", "Amigdalitis aguda, no especificada"),
    ("J04.0", "Laringitis aguda"), ("J05.0", "Laringitis obstructiva aguda (crup)"),
    ("J06.9", "Infección aguda de las vías respiratorias superiores, no especificada"),
    ("J10.1", "Influenza con otras manifestaciones respiratorias, virus identificado"),
    ("J11.1", "Influenza con otras manifestaciones respiratorias, virus no identificado"),
    ("J15.9", "Neumonía bacteriana, no especificada"), ("J18.0", "Bronconeumonía, no especificada"),
    ("J18.9", "Neumonía, no especificada"), ("J20.9", "Bronquitis aguda, no especificada"),
    ("J21.9", "Bronquiolitis aguda, no especificada"), ("J30.4", "Rinitis alérgica, no especificada"),
    ("J31.0", "Rinitis crónica"), ("J32.9", "Sinusitis crónica, no especificada"),
    ("J35.0", "Amigdalitis crónica"), ("J40", "Bronquitis, no especificada como aguda o crónica"),
    ("J44.9", "Enfermedad pulmonar obstructiva crónica (EPOC), no especificada"),
    ("J44.1", "EPOC con exacerbación aguda, no especificada"), ("J45.9", "Asma, no especificada"),
    ("J46", "Estado asmático"), ("J96.0", "Insuficiencia respiratoria aguda"),
    # --- Digestivo
    ("K02.9", "Caries dental, no especificada"), ("K04.7", "Absceso periapical sin fístula"),
    ("K05.1", "Gingivitis crónica"), ("K21.9", "Enfermedad del reflujo gastroesofágico sin esofagitis"),
    ("K25.9", "Úlcera gástrica, no especificada"), ("K29.7", "Gastritis, no especificada"),
    ("K30", "Dispepsia"), ("K35.8", "Apendicitis aguda, otras y las no especificadas"),
    ("K40.9", "Hernia inguinal unilateral, sin obstrucción ni gangrena"), ("K42.9", "Hernia umbilical sin obstrucción ni gangrena"),
    ("K52.9", "Colitis y gastroenteritis no infecciosas, no especificadas"), ("K57.3", "Enfermedad diverticular del intestino grueso"),
    ("K58.9", "Síndrome del colon irritable sin diarrea"), ("K59.0", "Constipación (estreñimiento)"),
    ("K70.3", "Cirrosis hepática alcohólica"), ("K74.6", "Otras cirrosis del hígado y las no especificadas"),
    ("K76.0", "Degeneración grasa del hígado (hígado graso)"), ("K80.2", "Cálculo de la vesícula biliar sin colecistitis"),
    ("K81.0", "Colecistitis aguda"), ("K85.9", "Pancreatitis aguda, no especificada"),
    ("K92.2", "Hemorragia gastrointestinal, no especificada"),
    # --- Piel
    ("L01.0", "Impétigo"), ("L02.9", "Absceso cutáneo, furúnculo y ántrax, de sitio no especificado"),
    ("L03.9", "Celulitis de sitio no especificado"), ("L20.9", "Dermatitis atópica, no especificada"),
    ("L23.9", "Dermatitis alérgica de contacto, de causa no especificada"), ("L22", "Dermatitis del pañal"),
    ("L30.9", "Dermatitis, no especificada"), ("L50.9", "Urticaria, no especificada"),
    ("L60.0", "Uña encarnada"), ("L70.0", "Acné vulgar"), ("L89.9", "Úlcera de decúbito, no especificada"),
    ("L40.9", "Psoriasis, no especificada"),
    # --- Osteomuscular
    ("M06.9", "Artritis reumatoide, no especificada"), ("M10.9", "Gota, no especificada"),
    ("M17.9", "Gonartrosis (artrosis de rodilla), no especificada"), ("M19.9", "Artrosis, no especificada"),
    ("M25.5", "Dolor en articulación"), ("M54.2", "Cervicalgia"), ("M54.4", "Lumbago con ciática"),
    ("M54.5", "Lumbago no especificado (lumbalgia)"), ("M62.6", "Distensión muscular"),
    ("M75.1", "Síndrome del manguito rotador"), ("M77.1", "Epicondilitis lateral (codo de tenista)"),
    ("M79.1", "Mialgia"), ("M81.9", "Osteoporosis, no especificada"),
    # --- Genitourinario
    ("N10", "Pielonefritis aguda"), ("N18.9", "Enfermedad renal crónica, no especificada"),
    ("N17.9", "Insuficiencia renal aguda, no especificada"), ("N20.0", "Cálculo del riñón"),
    ("N23", "Cólico renal, no especificado"), ("N30.0", "Cistitis aguda"),
    ("N39.0", "Infección de vías urinarias, sitio no especificado"), ("N40", "Hiperplasia de la próstata"),
    ("N63", "Masa no especificada en la mama"), ("N76.0", "Vaginitis aguda"),
    ("N91.2", "Amenorrea, sin otra especificación"), ("N92.0", "Menstruación excesiva y frecuente con ciclo regular"),
    ("N94.6", "Dismenorrea, no especificada"), ("N95.1", "Estados menopáusicos y climatéricos femeninos"),
    # --- Embarazo, parto y puerperio
    ("O03.9", "Aborto espontáneo completo o no especificado, sin complicación"),
    ("O13", "Hipertensión gestacional sin proteinuria significativa"), ("O14.9", "Preeclampsia, no especificada"),
    ("O15.9", "Eclampsia, en período no especificado"), ("O20.0", "Amenaza de aborto"),
    ("O21.0", "Hiperémesis gravídica leve"), ("O23.4", "Infección no especificada de las vías urinarias en el embarazo"),
    ("O24.4", "Diabetes mellitus que se origina con el embarazo"), ("O26.9", "Afección relacionada con el embarazo, no especificada"),
    ("O47.9", "Falso trabajo de parto, sin otra especificación"), ("O60.0", "Trabajo de parto prematuro sin parto"),
    ("O72.1", "Otras hemorragias postparto inmediatas"), ("O80", "Parto único espontáneo"),
    ("O82", "Parto único por cesárea"), ("O99.0", "Anemia que complica el embarazo, el parto y el puerperio"),
    # --- Perinatal
    ("P07.3", "Otros recién nacidos pretérmino"), ("P22.9", "Dificultad respiratoria del recién nacido, no especificada"),
    ("P36.9", "Sepsis bacteriana del recién nacido, no especificada"), ("P59.9", "Ictericia neonatal, no especificada"),
    # --- Síntomas y signos
    ("R05", "Tos"), ("R06.0", "Disnea"), ("R07.4", "Dolor en el pecho, no especificado"),
    ("R10.4", "Otros dolores abdominales y los no especificados"), ("R11", "Náusea y vómito"),
    ("R42", "Mareo y desvanecimiento"), ("R50.9", "Fiebre, no especificada"), ("R51", "Cefalea"),
    ("R52.9", "Dolor, no especificado"), ("R53", "Malestar y fatiga"), ("R55", "Síncope y colapso"),
    ("R56.0", "Convulsiones febriles"), ("R63.4", "Pérdida anormal de peso"), ("R73.9", "Hiperglicemia, no especificada"),
    # --- Traumatismos y envenenamientos
    ("S00.9", "Traumatismo superficial de la cabeza, parte no especificada"), ("S01.9", "Herida de la cabeza, parte no especificada"),
    ("S06.0", "Conmoción cerebral"), ("S09.9", "Traumatismo de la cabeza, no especificado"),
    ("S42.0", "Fractura de la clavícula"), ("S52.5", "Fractura de la epífisis inferior del radio"),
    ("S61.9", "Herida de la muñeca y de la mano, parte no especificada"), ("S62.6", "Fractura de otro dedo de la mano"),
    ("S72.0", "Fractura del cuello del fémur"), ("S82.6", "Fractura del maléolo externo"),
    ("S83.6", "Esguince de otras partes de la rodilla"), ("S93.4", "Esguince del tobillo"),
    ("T14.0", "Traumatismo superficial de región no especificada del cuerpo"),
    ("T14.1", "Herida de región no especificada del cuerpo"), ("T15.9", "Cuerpo extraño en parte externa del ojo"),
    ("T30.0", "Quemadura de región del cuerpo y grado no especificados"),
    ("T63.4", "Efecto tóxico del veneno de otros artrópodos (picadura de insecto)"),
    ("T63.0", "Efecto tóxico del veneno de serpiente"), ("T78.4", "Alergia no especificada"),
    ("T78.2", "Choque anafiláctico, no especificado"), ("T62.9", "Efecto tóxico de sustancia nociva ingerida como alimento"),
    ("T50.9", "Envenenamiento por otras drogas y medicamentos, y los no especificados"),
    ("T60.0", "Efecto tóxico de plaguicidas organofosforados y carbamatos"), ("W54", "Mordedura o ataque de perro"),
    # --- Contacto con los servicios de salud (controles)
    ("Z00.0", "Examen médico general"), ("Z00.1", "Control de salud de rutina del niño"),
    ("Z01.4", "Examen ginecológico general o de rutina"), ("Z02.7", "Extensión de certificado médico"),
    ("Z23", "Necesidad de inmunización (vacunación)"), ("Z30.0", "Consejo y asesoramiento general sobre la anticoncepción"),
    ("Z30.4", "Supervisión del uso de drogas anticonceptivas"), ("Z34.9", "Supervisión de embarazo normal, no especificado"),
    ("Z39.2", "Seguimiento postparto, de rutina"), ("Z48.0", "Atención de los apósitos y suturas (curación)"),
    ("Z71.3", "Consulta para instrucción y vigilancia de la dieta"), ("Z76.0", "Consulta para repetición de receta"),
    ("Z09.9", "Examen de seguimiento consecutivo a tratamiento"),
]

# Cómo lo dice la gente o se abrevia en la consulta (solo para encontrarlo; se guarda el nombre oficial)
SINONIMOS = {
    "I10": "hipertension arterial hta presion alta", "J00": "resfriado catarro gripe comun",
    "J11.1": "gripe influenza", "J10.1": "gripe influenza", "E11.9": "dm2 dm tipo 2 azucar",
    "E14.9": "azucar", "A09": "diarrea gastroenteritis ega", "N39.0": "ivu infeccion urinaria orina",
    "N30.0": "ivu infeccion urinaria", "K29.7": "dolor de estomago", "R50.9": "calentura temperatura",
    "M54.5": "dolor de espalda baja", "R51": "dolor de cabeza", "G44.2": "dolor de cabeza tensional",
    "K59.0": "estrenimiento", "D50.9": "anemia ferropenica", "H10.9": "ojo rojo",
    "J02.9": "dolor de garganta", "J03.9": "anginas", "T78.4": "reaccion alergica",
    "J18.9": "neumonia nac", "J44.9": "epoc", "K21.9": "erge reflujo agruras", "E78.5": "colesterol alto trigliceridos dislipidemia",
    "F41.1": "nervios ansiedad", "F32.9": "depresion", "B82.9": "lombrices parasitos", "S93.4": "torcedura tobillo",
    "R10.4": "dolor de estomago dolor abdominal", "Z00.0": "chequeo control general", "Z34.9": "control prenatal embarazo",
    "Z00.1": "control nino sano crecimiento", "Z23": "vacuna vacunacion", "O80": "parto normal eutocico",
    "O82": "cesarea", "I50.9": "ic falla cardiaca", "N18.9": "erc insuficiencia renal cronica",
    "E46": "desnutricion", "U07.1": "coronavirus sars cov 2", "W54": "mordida perro",
}
_POR_CODIGO = {c: d for c, d in CATALOGO}
assert len(_POR_CODIGO) == len(CATALOGO), "Hay códigos repetidos en el catálogo CIE-10"
assert set(SINONIMOS) <= set(_POR_CODIGO), "Hay sinónimos de códigos que no están en el catálogo"
_INDICE = [(c, d, normalizar(f"{c} {d} {SINONIMOS.get(c, '')}")) for c, d in CATALOGO]
FORMATO = re.compile(r"^[A-Z]\d{2}(\.\d{1,2})?$")


def normalizar_codigo(codigo):
    return (codigo or "").strip().upper()


def descripcion(codigo):
    return _POR_CODIGO.get(normalizar_codigo(codigo))


def capitulo(codigo):
    c = normalizar_codigo(codigo)[:3]
    return next((nombre for desde, hasta, nombre in CAPITULOS if desde <= c <= hasta), None)


def buscar(texto, limite=15):
    """Por código ("J0" -> J00, J01.9...) o por palabras en cualquier orden y sin tildes
    ("hiper arter" -> I10). Primero los que empiezan con lo buscado."""
    q = normalizar(texto)
    if not q:
        return []
    palabras = q.split()
    codigo = normalizar_codigo(texto).replace(" ", "")
    hallados = []
    for c, d, indice in _INDICE:
        if c.startswith(codigo) or c.replace(".", "").startswith(codigo.replace(".", "")):
            hallados.append((0, c, d))
        elif all(any(p_i.startswith(p) for p_i in indice.split()) for p in palabras):
            hallados.append((1 if normalizar(d).startswith(palabras[0]) else 2, c, d))
    hallados.sort(key=lambda h: (h[0], h[1]))
    return [{"codigo": c, "descripcion": d, "capitulo": capitulo(c)} for _, c, d in hallados[:limite]]
