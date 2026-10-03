"""
Datos FICTICIOS de los módulos simulados (Educación, Seguridad, Tributario).

Son coherentes con los pacientes de demostración de SALUD-DATABASE/datos_demo.sql:
mismos CUI, nombres y edades. Así, en la presentación, lo que "responde"
cada módulo tiene sentido con la ficha del paciente en Salud.

Cada módulo real tendría su propia base de datos; aquí cada uno tiene su
"padrón" en un diccionario. Para un CUI que no está en el padrón se aplica
una regla por el último dígito (ver app.py), para poder probar con
pacientes nuevos.
"""

# ---------------------------------------------------------------------------
# Educación: estudiantes (las edades cuadran con la fecha de nacimiento)
# ---------------------------------------------------------------------------
ESTUDIANTES = {
    "2502345670104": {"nombreCompleto": "Ana Lucía Morales Cifuentes", "nivel": "Diversificado",
                      "establecimiento": "INED Jornada Vespertina, Antigua Guatemala", "grado": "5to. Bachillerato en Ciencias y Letras",
                      "seccion": "B", "jornada": "Vespertina", "codigoEstablecimiento": "03-01-0145-46"},
    "2504567890106": {"nombreCompleto": "Sofía Alejandra Gómez Ruiz", "nivel": "Básico",
                      "establecimiento": "INEB Jornada Matutina, Antigua Guatemala", "grado": "3ro. Básico",
                      "seccion": "A", "jornada": "Matutina", "codigoEstablecimiento": "03-01-0112-45"},
    "2506789010108": {"nombreCompleto": "Gabriela Fernanda Díaz Mejía", "nivel": "Diversificado",
                      "establecimiento": "Escuela Normal Regional de Sacatepéquez", "grado": "6to. Magisterio de Educación Primaria",
                      "seccion": "A", "jornada": "Matutina", "codigoEstablecimiento": "03-01-0201-46"},
    "2509012340102": {"nombreCompleto": "Diego Alejandro Méndez Paz", "nivel": "Diversificado",
                      "establecimiento": "INED Jornada Vespertina, Antigua Guatemala", "grado": "4to. Bachillerato en Computación",
                      "seccion": "A", "jornada": "Vespertina", "codigoEstablecimiento": "03-01-0145-46"},
    "2512345670106": {"nombreCompleto": "Karla Beatriz Estrada Lemus", "nivel": "Diversificado",
                      "establecimiento": "Instituto Mixto de Ciudad Vieja", "grado": "6to. Perito Contador",
                      "seccion": "C", "jornada": "Vespertina", "codigoEstablecimiento": "03-04-0033-46"},
    "2514567890104": {"nombreCompleto": "Lucía Fernanda Tzul Ajú", "nivel": "Básico",
                      "establecimiento": "INEB Jornada Matutina, Antigua Guatemala", "grado": "1ro. Básico",
                      "seccion": "C", "jornada": "Matutina", "codigoEstablecimiento": "03-01-0112-45"},
    "2517890120108": {"nombreCompleto": "Kevin Estuardo Coyoy Pérez", "nivel": "Universitario",
                      "establecimiento": "Centro Universitario de Sacatepéquez", "grado": "3er. semestre, Ingeniería en Sistemas",
                      "seccion": "Única", "jornada": "Fin de semana", "codigoEstablecimiento": "U-03-0007"},
}

# Practicantes de medicina (WS-SALUD-07). Sus horas de práctica están en Salud
# (tabla horas_practica, datos_demo.sql) y Educación las consulta con WS-SALUD-06.
PRACTICANTES = {
    "2520123450106": {"nombreCompleto": "Daniela Sofía Paredes Lima", "universidad": "Universidad de San Carlos de Guatemala",
                      "carrera": "Médico y Cirujano", "nivel": "Externado (5to. año)", "estado": "ACTIVO"},
    "2521234560103": {"nombreCompleto": "Rodrigo Andrés Monterroso Gil", "universidad": "Universidad Mariano Gálvez de Guatemala",
                      "carrera": "Médico y Cirujano", "nivel": "Internado (6to. año)", "estado": "ACTIVO"},
    "2522345670100": {"nombreCompleto": "Valeria Isabel Cifuentes Arana", "universidad": "Universidad Rafael Landívar",
                      "carrera": "Licenciatura en Enfermería", "nivel": "4to. año", "estado": "ACTIVO"},
}

INDICADORES_EDUCACION = {
    "estudiantesInscritos": 18452, "establecimientosActivos": 214, "docentes": 1290,
    "tasaAsistencia": 93.4, "estudiantesConEsquemaVacunacionCompleto": 15102, "periodo": "Ciclo escolar 2026",
}

# ---------------------------------------------------------------------------
# Seguridad: antecedentes (contrato WS-SALUD-08) y alertas
# ---------------------------------------------------------------------------
ANTECEDENTES = {
    "2501234560109": {"nombreCompleto": "José Antonio Pérez García", "tieneAntecedentes": True,
                      "tipoAntecedente": "Robo agravado", "nivelRiesgo": "ALTO", "requiereCustodia": True,
                      "detalle": "Sentencia condenatoria (2019); cumple pena en régimen de libertad condicional.",
                      "expediente": "MP001-2019-21874", "fechaRegistro": "2019-08-14"},
    "2511234560109": {"nombreCompleto": "Juan Carlos Ixcoy Batz", "tieneAntecedentes": True,
                      "tipoAntecedente": "Lesiones graves", "nivelRiesgo": "ALTO", "requiereCustodia": True,
                      "detalle": "Proceso penal abierto; bajo medida de coerción.",
                      "expediente": "MP001-2025-04412", "fechaRegistro": "2025-03-02"},
    "2503456780107": {"nombreCompleto": "Carlos Enrique Ramírez Solís", "tieneAntecedentes": True,
                      "tipoAntecedente": "Falta contra el orden público", "nivelRiesgo": "BAJO", "requiereCustodia": False,
                      "detalle": "Falta resuelta con multa (2021).",
                      "expediente": "JPZ-0301-2021-0388", "fechaRegistro": "2021-11-20"},
    "2515678900107": {"nombreCompleto": "Fernando José Barrios Ochoa", "tieneAntecedentes": True,
                      "tipoAntecedente": "Conducir en estado de ebriedad", "nivelRiesgo": "BAJO", "requiereCustodia": False,
                      "detalle": "Falta de tránsito resuelta (2023).",
                      "expediente": "JPZ-0301-2023-1105", "fechaRegistro": "2023-06-09"},
}

ALERTAS = [
    {"id": "ALR-2026-0912", "tipo": "Accidente de tránsito", "zona": "Antigua Guatemala", "departamento": "Sacatepéquez",
     "nivel": "ALTO", "descripcion": "Colisión múltiple en RN-10, km 42. Posibles heridos.", "estado": "ACTIVA"},
    {"id": "ALR-2026-0915", "tipo": "Incendio", "zona": "Ciudad Vieja", "departamento": "Sacatepéquez",
     "nivel": "MEDIO", "descripcion": "Incendio forestal controlado en la ladera del Volcán de Agua.", "estado": "ACTIVA"},
    {"id": "ALR-2026-0917", "tipo": "Evento masivo", "zona": "Antigua Guatemala", "departamento": "Sacatepéquez",
     "nivel": "BAJO", "descripcion": "Actividad cultural en el Parque Central; se solicita ambulancia en espera.", "estado": "ACTIVA"},
    {"id": "ALR-2026-0921", "tipo": "Accidente de tránsito", "zona": "Zona 11", "departamento": "Guatemala",
     "nivel": "MEDIO", "descripcion": "Percance vial en Calzada Roosevelt.", "estado": "ACTIVA"},
]

INDICADORES_SEGURIDAD = {
    "alertasActivas": len(ALERTAS), "incidentesMes": 63, "patrullajesActivos": 18,
    "consultasAntecedentesMes": 412, "tiempoRespuestaPromedioMin": 11.5, "periodo": "Octubre 2026",
}

# ---------------------------------------------------------------------------
# Tributario: contribuyentes y pagos (contrato WS-SALUD-09)
# ---------------------------------------------------------------------------
# Personas cuyo pago todavía no aparece registrado (para mostrar el caso negativo).
PAGO_NO_REGISTRADO = {"2507890120103", "2510123450103", "2518901230103"}

CONTRIBUYENTES_INSOLVENTES = {"2513456780101"}

INDICADORES_TRIBUTARIO = {
    "recaudacionMes": 1845230.75, "pagosVerificadosMes": 3921, "contribuyentesSolventes": 0.87,
    "pagosServiciosSaludMes": 638, "periodo": "Octubre 2026", "moneda": "GTQ",
}

# Nombres de todos los pacientes de demostración (para respuestas que lo incluyen)
NOMBRES = {
    "2501123450102": "María José López Hernández", "2501234560109": "José Antonio Pérez García",
    "2502345670104": "Ana Lucía Morales Cifuentes", "2503456780107": "Carlos Enrique Ramírez Solís",
    "2504567890106": "Sofía Alejandra Gómez Ruiz", "2505678900101": "Luis Fernando Castillo Ortiz",
    "2506789010108": "Gabriela Fernanda Díaz Mejía", "2507890120103": "Pedro Pablo Juárez Chávez",
    "2508901230105": "Andrea Paola Reyes Monzón", "2509012340102": "Diego Alejandro Méndez Paz",
    "2510123450103": "Rosa Elena Velásquez Toj", "2511234560109": "Juan Carlos Ixcoy Batz",
    "2512345670106": "Karla Beatriz Estrada Lemus", "2513456780101": "Mario Roberto Aguilar Cano",
    "2514567890104": "Lucía Fernanda Tzul Ajú", "2515678900107": "Fernando José Barrios Ochoa",
    "2516789010105": "Claudia María Sandoval Rivas", "2517890120108": "Kevin Estuardo Coyoy Pérez",
    "2518901230103": "Marta Julia Orellana Cruz", "2519012340101": "Oscar Iván Hernández Toc",
}
