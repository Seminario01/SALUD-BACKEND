"""
Vigilancia epidemiológica: casos por municipio de residencia, para ver si una enfermedad se está
juntando en una zona (posible brote) y actuar a tiempo.

  GET /ubicaciones              departamentos y municipios (para los formularios)     (cualquier usuario)
  GET /vigilancia/grupos        grupos de enfermedades vigilados                     (vigilancia.ver)
  GET /vigilancia/casos         casos por municipio, tendencia semanal y alertas      (vigilancia.ver, solo cifras)
  GET /vigilancia/pacientes     quiénes son los casos (de un municipio)              (vigilancia.pacientes)

Un caso es una atención del expediente con código CIE-10, de un paciente con municipio registrado.
Alerta de posible brote: en los últimos 7 días del período hay al menos 3 casos y más del doble del
promedio semanal de las 4 semanas anteriores. Es un aviso para investigar, no un diagnóstico.
Quien no puede ver pacientes (Enfermería, Administración, Auditoría) no ve municipios con menos de
3 pacientes: solo cifras que no identifican a nadie.
"""
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta

from flask import Blueprint, jsonify, request

import cie10
import ubicaciones
from auth import puede, requiere_permiso, validar_token
from extensions import db
from models import ExpedienteClinico, Paciente
from validacion import ESCAPE_LIKE, contiene, empieza

vigilancia_bp = Blueprint("vigilancia", __name__)

# Grupos de vigilancia (como los eventos de notificación obligatoria): rangos de códigos CIE-10
GRUPOS = {
    "respiratorias": ("Infecciones respiratorias agudas", [("J00", "J22"), ("U07", "U07")]),
    "diarreicas": ("Enfermedades diarreicas", [("A00", "A09")]),
    "arbovirosis": ("Dengue, chikungunya y zika", [("A90", "A92")]),
    "paludismo": ("Paludismo (malaria)", [("B50", "B54")]),
    "hepatitis": ("Hepatitis A", [("B15", "B15")]),
    "exantematicas": ("Varicela, sarampión y mano-pie-boca", [("B01", "B01"), ("B05", "B05"), ("B08", "B08")]),
    "desnutricion": ("Desnutrición", [("E40", "E46")]),
    "hipertension": ("Hipertensión arterial", [("I10", "I15")]),
    "diabetes": ("Diabetes", [("E10", "E14")]),
}
MINIMO = 3                  # pacientes por municipio para mostrar la cifra a quien no ve pacientes
MAX_DIAS = 366


def _error(status, codigo, mensaje):
    return jsonify(success=False, error=codigo, message=mensaje), status


def grupo_de(codigo):
    c = (codigo or "")[:3]
    return next((g for g, (_, rangos) in GRUPOS.items() if any(a <= c <= b for a, b in rangos)), None)


def _edad(nacimiento, dia):
    if not nacimiento:
        return None
    return dia.year - nacimiento.year - ((dia.month, dia.day) < (nacimiento.month, nacimiento.day))


class _Filtros:
    """Lee y valida los filtros de la petición (lanza ValueError con el mensaje para el usuario)."""
    def __init__(self, args):
        hoy = date.today()
        try:
            self.hasta = datetime.strptime(args["hasta"], "%Y-%m-%d").date() if args.get("hasta") else hoy
            self.desde = datetime.strptime(args["desde"], "%Y-%m-%d").date() if args.get("desde") else self.hasta - timedelta(days=27)
        except ValueError:
            raise ValueError("Las fechas van como AAAA-MM-DD")
        if self.desde > self.hasta:
            raise ValueError("desde no puede ser después de hasta")
        if (self.hasta - self.desde).days >= MAX_DIAS:
            raise ValueError("El período puede ser de hasta un año")
        self.grupo = args.get("grupo") or ""
        if self.grupo and self.grupo not in GRUPOS:
            raise ValueError(f"grupo debe ser uno de: {', '.join(GRUPOS)}")
        self.codigo = cie10.normalizar_codigo(args.get("codigo"))[:6]
        if self.codigo and not cie10.FORMATO.match(self.codigo) and not (len(self.codigo) in (1, 2, 3) and self.codigo[0].isalpha()):
            raise ValueError("codigo debe ser un código CIE-10 o su inicio (por ejemplo A90 o J)")
        self.departamento = args.get("departamento") or ""
        if self.departamento and self.departamento not in ubicaciones.DEPARTAMENTOS:
            raise ValueError("departamento debe ser el código del INE de 2 dígitos (01 a 22)")
        self.genero = args.get("genero") or ""
        if self.genero and self.genero not in ("M", "F", "Otro"):
            raise ValueError("genero debe ser M, F u Otro")
        self.edad_min = self._entero(args, "edad_min", 0)
        self.edad_max = self._entero(args, "edad_max", 130)
        if self.edad_min > self.edad_max:
            raise ValueError("edad_min no puede ser mayor que edad_max")

    @staticmethod
    def _entero(args, nombre, defecto):
        valor = args.get(nombre, "")
        if valor == "":
            return defecto
        if not valor.isdigit() or int(valor) > 130:
            raise ValueError(f"{nombre} debe ser un número de 0 a 130")
        return int(valor)

    def casos(self, desde=None, municipio=None):
        """Atenciones con CIE-10 de pacientes con municipio, que cumplen los filtros.
        `desde` permite ir más atrás (para la comparación con semanas anteriores)."""
        inicio = datetime.combine(desde or self.desde, datetime.min.time())
        fin = datetime.combine(self.hasta + timedelta(days=1), datetime.min.time())
        q = (db.session.query(ExpedienteClinico.id, ExpedienteClinico.fecha_atencion, ExpedienteClinico.codigo_cie10,
                              ExpedienteClinico.diagnostico, Paciente.id, Paciente.municipio, Paciente.genero,
                              Paciente.fecha_nacimiento, Paciente.nombre_completo, Paciente.zona)
             .join(Paciente, Paciente.id == ExpedienteClinico.paciente_id)
             .filter(ExpedienteClinico.fecha_atencion >= inicio, ExpedienteClinico.fecha_atencion < fin,
                     ExpedienteClinico.codigo_cie10.isnot(None), Paciente.municipio.isnot(None)))
        if municipio:
            q = q.filter(Paciente.municipio == municipio)
        elif self.departamento:
            q = q.filter(Paciente.municipio.like(empieza(self.departamento), escape=ESCAPE_LIKE))
        if self.genero:
            q = q.filter(Paciente.genero == self.genero)
        if self.codigo:
            q = q.filter(ExpedienteClinico.codigo_cie10.like(empieza(self.codigo), escape=ESCAPE_LIKE))
        salida = []
        for (aid, fecha, codigo, diagnostico, pid, mun, genero, nacimiento, nombre, zona) in q.all():
            if self.grupo and grupo_de(codigo) != self.grupo:
                continue
            edad = _edad(nacimiento, fecha.date())
            if (self.edad_min or self.edad_max < 130) and (edad is None or not self.edad_min <= edad <= self.edad_max):
                continue
            salida.append({"atencion": aid, "fecha": fecha, "codigo": codigo, "diagnostico": diagnostico,
                           "paciente_id": pid, "municipio": mun, "genero": genero, "edad": edad,
                           "nombre": nombre, "zona": zona})
        return salida

    def como_dict(self):
        return {"desde": self.desde.isoformat(), "hasta": self.hasta.isoformat(), "grupo": self.grupo or None,
                "codigo": self.codigo or None, "departamento": self.departamento or None, "genero": self.genero or None,
                "edad_min": self.edad_min, "edad_max": self.edad_max}


def _es_brote(semana, previo_4_semanas):
    """3 o más casos en los últimos 7 días y más del doble del promedio semanal de las 4 semanas antes."""
    promedio = round(previo_4_semanas / 4, 1)
    return semana >= 3 and semana > 2 * promedio, promedio


def alertas_por_enfermedad(f, todos):
    """Posibles brotes por municipio Y grupo de enfermedad (más preciso que mezclar todo):
    un aumento de dengue no queda escondido entre las infecciones respiratorias de siempre."""
    ultima = f.hasta - timedelta(days=6)
    semana, previo = Counter(), Counter()
    for c in todos:
        g = grupo_de(c["codigo"])
        if not g:
            continue
        dia = c["fecha"].date()
        if dia >= ultima:
            semana[(c["municipio"], g)] += 1
        elif dia >= ultima - timedelta(days=28):
            previo[(c["municipio"], g)] += 1
    alertas = []
    for (mun, g), n in semana.items():
        brote, promedio = _es_brote(n, previo[(mun, g)])
        if brote:
            alertas.append({"municipio": mun, "nombre": ubicaciones.nombre_municipio(mun),
                            "departamento_nombre": ubicaciones.nombre_departamento(mun),
                            "grupo": g, "enfermedad": GRUPOS[g][0], "ultimos_7_dias": n, "promedio_semanal_previo": promedio,
                            "texto": f"{GRUPOS[g][0]}: {n} casos en los últimos 7 días (promedio anterior: {promedio} por semana)"})
    return sorted(alertas, key=lambda a: -a["ultimos_7_dias"])


def brotes_recientes():
    """Para la pantalla de inicio: posibles brotes por enfermedad hasta hoy (sin filtros)."""
    f = _Filtros({})
    return alertas_por_enfermedad(f, f.casos(desde=f.hasta - timedelta(days=34)))


@vigilancia_bp.route("/api/v1/salud/ubicaciones", methods=["GET"])
@validar_token
def ubicaciones_gt():
    """
    Departamentos y municipios de Guatemala (códigos del INE, los del DPI)
    ---
    tags:
      - Vigilancia
    security:
      - BearerAuth: []
    responses:
      200:
        description: "{fuente, departamentos: [{codigo, nombre}], municipios: [{codigo, nombre, departamento}]}"
    description: Datos públicos (INE/CONRED); también los usa el ciudadano para su residencia.
    """
    return jsonify(success=True, data=ubicaciones.catalogo()), 200


@vigilancia_bp.route("/api/v1/salud/vigilancia/grupos", methods=["GET"])
@validar_token
@requiere_permiso("vigilancia.ver")
def grupos_vigilancia():
    """
    Grupos de enfermedades vigilados (con sus rangos CIE-10)
    ---
    tags:
      - Vigilancia
    security:
      - BearerAuth: []
    responses:
      200:
        description: "[{grupo, nombre, codigos}]"
    """
    return jsonify(success=True, data=[{"grupo": g, "nombre": n, "codigos": [a if a == b else f"{a}-{b}" for a, b in r]}
                                       for g, (n, r) in GRUPOS.items()]), 200


@vigilancia_bp.route("/api/v1/salud/vigilancia/casos", methods=["GET"])
@validar_token
@requiere_permiso("vigilancia.ver")
def casos_vigilancia():
    """
    Casos por municipio de residencia, tendencia semanal y alertas de posible brote
    ---
    tags:
      - Vigilancia
    security:
      - BearerAuth: []
    description: >
      Solo cifras. Quien no puede ver pacientes no ve municipios con menos de 3 pacientes
      (salen como "pocos"). La alerta compara los últimos 7 días del período con el promedio
      semanal de las 4 semanas anteriores.
    parameters:
      - {name: desde, in: query, type: string, format: date, description: "Por defecto, 28 días antes de hasta"}
      - {name: hasta, in: query, type: string, format: date, description: "Por defecto, hoy"}
      - {name: grupo, in: query, type: string, enum: [respiratorias, diarreicas, arbovirosis, paludismo, hepatitis, exantematicas, desnutricion, hipertension, diabetes]}
      - {name: codigo, in: query, type: string, description: "Código CIE-10 o su inicio (A90, J)"}
      - {name: departamento, in: query, type: string, description: "Código de 2 dígitos (01 a 22)"}
      - {name: genero, in: query, type: string, enum: [M, F, Otro]}
      - {name: edad_min, in: query, type: integer}
      - {name: edad_max, in: query, type: integer}
    responses:
      200:
        description: "municipios, departamentos, semanas, matriz, alertas, sin_ubicacion"
      400:
        description: Algún filtro no sirve
    """
    try:
        f = _Filtros(request.args)
    except ValueError as error:
        return _error(400, "datos_invalidos", str(error))
    ve_pacientes = puede("vigilancia.pacientes")
    inicio_comparacion = min(f.desde, f.hasta - timedelta(days=34))
    todos = f.casos(desde=inicio_comparacion)
    periodo = [c for c in todos if c["fecha"].date() >= f.desde]
    ultima_semana = f.hasta - timedelta(days=6)

    por_mun, pacientes_mun = Counter(), defaultdict(set)
    semana_mun, previo_mun = Counter(), Counter()
    for c in todos:
        dia = c["fecha"].date()
        if dia >= f.desde:
            por_mun[c["municipio"]] += 1
            pacientes_mun[c["municipio"]].add(c["paciente_id"])
        if dia >= ultima_semana:
            semana_mun[c["municipio"]] += 1
        elif dia >= ultima_semana - timedelta(days=28):
            previo_mun[c["municipio"]] += 1

    def oculto(mun):
        return not ve_pacientes and len(pacientes_mun[mun]) < MINIMO

    municipios, alertas = [], []
    for mun, casos in por_mun.most_common():
        info = ubicaciones.municipio(mun) or {}
        brote, promedio = _es_brote(semana_mun[mun], previo_mun[mun])
        fila = {"codigo": mun, "nombre": info.get("nombre"), "departamento": mun[:2],
                "departamento_nombre": ubicaciones.nombre_departamento(mun),
                "lat": info.get("lat"), "lon": info.get("lon")}
        if oculto(mun):
            fila.update(pocos=True, casos=None, pacientes=None, ultimos_7_dias=None, promedio_semanal_previo=None, alerta=False)
        else:
            fila.update(pocos=False, casos=casos, pacientes=len(pacientes_mun[mun]), ultimos_7_dias=semana_mun[mun],
                        promedio_semanal_previo=promedio, alerta=brote)
            if brote:
                alertas.append({"municipio": mun, "nombre": info.get("nombre"),
                                "departamento_nombre": ubicaciones.nombre_departamento(mun),
                                "ultimos_7_dias": semana_mun[mun], "promedio_semanal_previo": promedio,
                                "texto": f"{semana_mun[mun]} casos en los últimos 7 días (promedio anterior: {promedio} por semana)"})
        municipios.append(fila)

    por_depto = Counter(c["municipio"][:2] for c in periodo)
    departamentos = [{"codigo": d, "nombre": ubicaciones.nombre_departamento(d), "casos": n} for d, n in por_depto.most_common()]

    # Tendencia: casos por semana (de 7 días que terminan en "hasta"), las últimas 12 semanas del período
    semanas = []
    for i in range(min(12, (f.hasta - f.desde).days // 7 + 1) - 1, -1, -1):
        fin = f.hasta - timedelta(days=7 * i)
        ini = fin - timedelta(days=6)
        semanas.append({"desde": ini.isoformat(), "hasta": fin.isoformat(),
                        "casos": sum(1 for c in todos if ini <= c["fecha"].date() <= fin)})

    # Tabla de calor: municipios con más casos × grupos de enfermedades
    grupos_periodo = Counter((c["municipio"], grupo_de(c["codigo"]) or "otros") for c in periodo)
    principales = [m["codigo"] for m in municipios if not m["pocos"]][:12]
    matriz = [{"municipio": mun, "nombre": ubicaciones.nombre_municipio(mun),
               "grupos": {g: grupos_periodo[(mun, g)] for g in [*GRUPOS, "otros"] if grupos_periodo[(mun, g)]}}
              for mun in principales]

    sin_ubicacion = (db.session.query(db.func.count(ExpedienteClinico.id))
                     .join(Paciente, Paciente.id == ExpedienteClinico.paciente_id)
                     .filter(ExpedienteClinico.fecha_atencion >= datetime.combine(f.desde, datetime.min.time()),
                             ExpedienteClinico.fecha_atencion < datetime.combine(f.hasta + timedelta(days=1), datetime.min.time()),
                             ExpedienteClinico.codigo_cie10.isnot(None), Paciente.municipio.is_(None)).scalar())
    return jsonify(success=True, filtros=f.como_dict(), total_casos=len(periodo),
                   total_pacientes=len({c["paciente_id"] for c in periodo}),
                   municipios=municipios, departamentos=departamentos, semanas=semanas, matriz=matriz,
                   grupos={g: n for g, (n, _) in GRUPOS.items()}, alertas=alertas,
                   # Sin filtro de enfermedad, además se revisa cada enfermedad por separado
                   alertas_por_enfermedad=[] if f.grupo else alertas_por_enfermedad(f, todos),
                   sin_ubicacion=sin_ubicacion, minimo_para_mostrar=None if ve_pacientes else MINIMO,
                   fuente_mapa=ubicaciones.FUENTE), 200


@vigilancia_bp.route("/api/v1/salud/vigilancia/pacientes", methods=["GET"])
@validar_token
@requiere_permiso("vigilancia.pacientes")
def pacientes_vigilancia():
    """
    Los casos de un municipio (quiénes son), con los mismos filtros
    ---
    tags:
      - Vigilancia
    security:
      - BearerAuth: []
    description: Solo Médico y Jefatura. Queda en la bitácora de accesos.
    parameters:
      - {name: municipio, in: query, type: string, required: true, description: "Código del INE de 4 dígitos"}
      - {name: desde, in: query, type: string, format: date}
      - {name: hasta, in: query, type: string, format: date}
      - {name: grupo, in: query, type: string}
      - {name: codigo, in: query, type: string}
      - {name: genero, in: query, type: string}
      - {name: edad_min, in: query, type: integer}
      - {name: edad_max, in: query, type: integer}
    responses:
      200:
        description: "[{paciente_id, nombre, edad, genero, zona, fecha, codigo, diagnostico, grupo}] (los 300 más recientes)"
      400:
        description: Municipio o filtro inválido
    """
    mun = request.args.get("municipio", "")
    if not ubicaciones.municipio(mun):
        return _error(400, "datos_invalidos", "municipio debe ser un código del INE de 4 dígitos que exista")
    try:
        f = _Filtros(request.args)
    except ValueError as error:
        return _error(400, "datos_invalidos", str(error))
    casos = sorted(f.casos(municipio=mun), key=lambda c: c["fecha"], reverse=True)[:300]
    return jsonify(success=True, municipio={"codigo": mun, "nombre": ubicaciones.nombre_municipio(mun),
                                             "departamento_nombre": ubicaciones.nombre_departamento(mun)},
                   data=[{"paciente_id": c["paciente_id"], "nombre": c["nombre"], "edad": c["edad"], "genero": c["genero"],
                          "zona": c["zona"], "fecha": c["fecha"].isoformat(timespec="minutes"), "codigo": c["codigo"],
                          "cie10": cie10.descripcion(c["codigo"]), "diagnostico": c["diagnostico"],
                          "grupo": grupo_de(c["codigo"])} for c in casos]), 200
