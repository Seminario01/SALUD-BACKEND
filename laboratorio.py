"""
Laboratorio clínico: catálogo de exámenes, sus parámetros y la interpretación de cada resultado
(sin base de datos: pruebas/prueba_laboratorio.py lo revisa sin servidor).

Cada parámetro es numérico (con unidad, rango de referencia de un adulto y límites de lo posible,
para rechazar errores de digitación) o cualitativo (opciones fijas y cuáles son normales).

  EXAMENES                       codigo -> {nombre, categoria, parametros: [...]}
  validar_valor(parametro, v)    el valor limpio, o DatoInvalido si no sirve
  interpretar(parametro, v)      "normal" | "alto" | "bajo" | "anormal"  (None si no hay valor)
"""
from validacion import DatoInvalido


def _num(clave, nombre, unidad, minimo, maximo, posible, decimales=1):
    return {"clave": clave, "nombre": nombre, "tipo": "numero", "unidad": unidad, "min": minimo, "max": maximo,
            "posible": posible, "decimales": decimales}


def _cual(clave, nombre, opciones, normales):
    return {"clave": clave, "nombre": nombre, "tipo": "opcion", "opciones": opciones, "normales": normales}


NEG = ["Negativo", "Trazas", "+", "++", "+++"]
REACTIVO = ["No reactivo", "Reactivo"]
POS = ["Negativo", "Positivo"]

EXAMENES = {
    # --- Hematología
    "HEMATO": {"nombre": "Hematología completa", "categoria": "Hematología", "parametros": [
        _num("hemoglobina", "Hemoglobina", "g/dL", 12.0, 17.5, (1, 25)),
        _num("hematocrito", "Hematocrito", "%", 36, 52, (5, 75), 0),
        _num("leucocitos", "Glóbulos blancos", "×10³/µL", 4.5, 11.0, (0.1, 200)),
        _num("neutrofilos", "Neutrófilos", "%", 40, 75, (0, 100), 0),
        _num("linfocitos", "Linfocitos", "%", 20, 45, (0, 100), 0),
        _num("plaquetas", "Plaquetas", "×10³/µL", 150, 450, (1, 2000), 0),
    ]},
    "GRUPO_RH": {"nombre": "Grupo sanguíneo y factor Rh", "categoria": "Hematología", "parametros": [
        _cual("grupo", "Grupo", ["O", "A", "B", "AB"], ["O", "A", "B", "AB"]),
        _cual("rh", "Factor Rh", ["Positivo", "Negativo"], ["Positivo", "Negativo"]),
    ]},
    # --- Química sanguínea
    "GLUCOSA": {"nombre": "Glucosa en ayunas", "categoria": "Química sanguínea", "parametros": [
        _num("glucosa", "Glucosa", "mg/dL", 70, 100, (10, 1500), 0)]},
    "HBA1C": {"nombre": "Hemoglobina glicosilada (HbA1c)", "categoria": "Química sanguínea", "parametros": [
        _num("hba1c", "HbA1c", "%", 4.0, 5.6, (2, 20))]},
    "RENAL": {"nombre": "Función renal", "categoria": "Química sanguínea", "parametros": [
        _num("creatinina", "Creatinina", "mg/dL", 0.6, 1.3, (0.1, 30), 2),
        _num("bun", "Nitrógeno de urea (BUN)", "mg/dL", 7, 20, (1, 300), 0),
        _num("acido_urico", "Ácido úrico", "mg/dL", 2.5, 7.0, (0.5, 25)),
    ]},
    "LIPIDOS": {"nombre": "Perfil de lípidos", "categoria": "Química sanguínea", "parametros": [
        _num("colesterol", "Colesterol total", "mg/dL", None, 199, (40, 1000), 0),
        _num("hdl", "Colesterol HDL", "mg/dL", 40, None, (5, 200), 0),
        _num("ldl", "Colesterol LDL", "mg/dL", None, 129, (5, 800), 0),
        _num("trigliceridos", "Triglicéridos", "mg/dL", None, 149, (10, 5000), 0),
    ]},
    "HEPATICO": {"nombre": "Pruebas hepáticas", "categoria": "Química sanguínea", "parametros": [
        _num("tgo", "TGO (AST)", "U/L", 0, 40, (0, 10000), 0),
        _num("tgp", "TGP (ALT)", "U/L", 0, 41, (0, 10000), 0),
        _num("bilirrubina", "Bilirrubina total", "mg/dL", 0.2, 1.2, (0, 40)),
    ]},
    # --- Orina y heces
    "ORINA": {"nombre": "Examen general de orina", "categoria": "Orina y heces", "parametros": [
        _num("ph", "pH", "", 4.5, 8.0, (4, 9.5)),
        _num("densidad", "Densidad", "", 1.005, 1.030, (1.000, 1.060), 3),
        _cual("proteinas", "Proteínas", NEG, ["Negativo"]),
        _cual("glucosa_orina", "Glucosa", NEG, ["Negativo"]),
        _cual("nitritos", "Nitritos", POS, ["Negativo"]),
        _num("leucocitos_campo", "Leucocitos", "por campo", 0, 5, (0, 200), 0),
        _num("eritrocitos_campo", "Eritrocitos", "por campo", 0, 3, (0, 200), 0),
        _cual("bacterias", "Bacterias", ["Escasas", "Moderadas", "Abundantes"], ["Escasas"]),
    ]},
    "HECES": {"nombre": "Examen de heces", "categoria": "Orina y heces", "parametros": [
        _cual("consistencia", "Consistencia", ["Formada", "Pastosa", "Líquida"], ["Formada", "Pastosa"]),
        _cual("parasitos", "Parásitos", ["No se observan", "Quistes de Entamoeba histolytica", "Quistes de Giardia lamblia",
                                          "Huevos de Ascaris lumbricoides", "Otros"], ["No se observan"]),
        _cual("sangre_oculta", "Sangre oculta", POS, ["Negativo"]),
    ]},
    # --- Inmunología y pruebas rápidas
    "EMBARAZO": {"nombre": "Prueba de embarazo (hCG)", "categoria": "Inmunología", "parametros": [
        _cual("hcg", "hCG en orina", POS, ["Negativo", "Positivo"])]},
    "VIH": {"nombre": "Prueba rápida de VIH", "categoria": "Inmunología", "parametros": [
        _cual("vih", "Anticuerpos VIH 1/2", REACTIVO, ["No reactivo"])]},
    "VDRL": {"nombre": "VDRL (sífilis)", "categoria": "Inmunología", "parametros": [
        _cual("vdrl", "VDRL", REACTIVO, ["No reactivo"])]},
    "DENGUE": {"nombre": "Dengue NS1 / IgM", "categoria": "Inmunología", "parametros": [
        _cual("ns1", "Antígeno NS1", POS, ["Negativo"]), _cual("igm", "IgM", POS, ["Negativo"])]},
    "PCR": {"nombre": "Proteína C reactiva", "categoria": "Inmunología", "parametros": [
        _num("pcr", "PCR", "mg/L", 0, 5, (0, 500))]},
}
CATEGORIAS = ["Hematología", "Química sanguínea", "Orina y heces", "Inmunología"]
assert {e["categoria"] for e in EXAMENES.values()} <= set(CATEGORIAS)


def referencia(p):
    """Texto del rango normal para imprimir: "12.0 – 17.5 g/dL", "< 200 mg/dL", "Negativo"."""
    if p["tipo"] == "opcion":
        return " / ".join(p["normales"]) if p["normales"] != p["opciones"] else "—"
    fmt = lambda v: f"{v:.{p['decimales']}f}"  # noqa: E731
    u = f" {p['unidad']}" if p["unidad"] else ""
    if p["min"] is None:
        return f"< {fmt(p['max'] + (10 ** -p['decimales']))}{u}"
    if p["max"] is None:
        return f"≥ {fmt(p['min'])}{u}"
    return f"{fmt(p['min'])} – {fmt(p['max'])}{u}"


def validar_valor(p, valor):
    """Número dentro de lo posible (rechaza errores de digitación como 1400 de hemoglobina) u opción válida."""
    if valor is None or valor == "":
        return None
    if p["tipo"] == "opcion":
        if not isinstance(valor, str) or valor not in p["opciones"]:
            raise DatoInvalido(f"{p['nombre']}: debe ser una de: {', '.join(p['opciones'])}")
        return valor
    if isinstance(valor, bool) or not isinstance(valor, (int, float, str)):
        raise DatoInvalido(f"{p['nombre']} debe ser un número")
    try:
        numero = float(str(valor).replace(",", ".").strip())
    except ValueError:
        raise DatoInvalido(f"{p['nombre']} debe ser un número")
    bajo, alto = p["posible"]
    if not bajo <= numero <= alto:
        raise DatoInvalido(f"{p['nombre']}: {numero:g} {p['unidad']} no es un valor posible (revise la digitación)".replace("  ", " "))
    return round(numero, p["decimales"])


def interpretar(p, valor):
    if valor is None or valor == "":
        return None
    if p["tipo"] == "opcion":
        return "normal" if valor in p["normales"] else "anormal"
    v = float(valor)
    if p["min"] is not None and v < p["min"]:
        return "bajo"
    if p["max"] is not None and v > p["max"]:
        return "alto"
    return "normal"


def catalogo():
    """Para la pantalla: exámenes con sus parámetros y el texto del rango de referencia."""
    return [{"codigo": c, "nombre": e["nombre"], "categoria": e["categoria"],
             "parametros": [{**{k: v for k, v in p.items() if k != "posible"}, "referencia": referencia(p)}
                            for p in e["parametros"]]}
            for c, e in EXAMENES.items()]


def resultados_interpretados(codigo, valores):
    """valores {clave: valor} -> [{clave, nombre, valor, unidad, referencia, nivel}] en el orden del examen."""
    examen = EXAMENES.get(codigo)
    if not examen:
        return []
    valores = valores or {}
    return [{"clave": p["clave"], "nombre": p["nombre"], "valor": valores.get(p["clave"]),
             "unidad": p.get("unidad", ""), "referencia": referencia(p), "nivel": interpretar(p, valores.get(p["clave"]))}
            for p in examen["parametros"]]
