from extensions import db
from datetime import datetime

class UsuarioRol(db.Model):
    __tablename__ = "usuarios_roles"
    id = db.Column(db.Integer, primary_key=True)
    cognito_sub = db.Column(db.String(100), unique=True, nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)
    rol = db.Column(db.Enum("admin", "medico", "paciente", "recepcion"), nullable=False)
    nombre_completo = db.Column(db.String(200))
    cui = db.Column(db.String(20))
    activo = db.Column(db.Boolean, default=True)
    fecha_creacion = db.Column(db.DateTime, default=datetime.utcnow)


class Paciente(db.Model):
    __tablename__ = "pacientes"
    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuarios_roles.id"), nullable=True)
    cui = db.Column(db.String(20))
    nombre_completo = db.Column(db.String(200), nullable=False)
    fecha_nacimiento = db.Column(db.Date)
    genero = db.Column(db.String(20))
    telefono = db.Column(db.String(20))
    tipo_seguro = db.Column(db.String(50))
    cuidador = db.Column(db.String(200))
    fecha_registro = db.Column(db.DateTime, default=datetime.utcnow)


class CitaMedica(db.Model):
    __tablename__ = "citas_medicas"
    id = db.Column(db.Integer, primary_key=True)
    paciente_id = db.Column(db.Integer, db.ForeignKey("pacientes.id"), nullable=False)
    medico_id = db.Column(db.Integer, db.ForeignKey("usuarios_roles.id"))
    fecha_hora = db.Column(db.DateTime, nullable=False)
    estado = db.Column(db.Enum("pendiente", "confirmada", "atendida", "cancelada"), default="pendiente")
    motivo = db.Column(db.String(300))
    costo = db.Column(db.Numeric(10, 2))
    pago_confirmado = db.Column(db.Boolean, default=False)
    fecha_creacion = db.Column(db.DateTime, default=datetime.utcnow)


class ExpedienteClinico(db.Model):
    __tablename__ = "expedientes_clinicos"
    id = db.Column(db.Integer, primary_key=True)
    paciente_id = db.Column(db.Integer, db.ForeignKey("pacientes.id"), nullable=False)
    cita_id = db.Column(db.Integer, db.ForeignKey("citas_medicas.id"), nullable=True)
    medico_id = db.Column(db.Integer, db.ForeignKey("usuarios_roles.id"))
    diagnostico = db.Column(db.Text)
    tratamiento = db.Column(db.Text)
    notas = db.Column(db.Text)
    fecha_atencion = db.Column(db.DateTime, default=datetime.utcnow)


class RecursoHospitalario(db.Model):
    __tablename__ = "recursos_hospitalarios"
    id = db.Column(db.Integer, primary_key=True)
    tipo = db.Column(db.Enum("cama", "ambulancia", "cupo_consulta"), nullable=False)
    descripcion = db.Column(db.String(200))
    disponible = db.Column(db.Integer, default=0)
    total = db.Column(db.Integer, default=0)
    ultima_actualizacion = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Turno(db.Model):
    __tablename__ = "turnos"
    id = db.Column(db.Integer, primary_key=True)
    paciente_id = db.Column(db.Integer, db.ForeignKey("pacientes.id"), nullable=False)
    tipo_atencion = db.Column(db.Enum("consulta_general", "emergencia", "especialidad"), nullable=False)
    numero_turno = db.Column(db.Integer, nullable=False)
    estado = db.Column(db.Enum("en_espera", "llamado", "en_atencion", "atendido", "ausente"), default="en_espera")
    prioridad = db.Column(db.Enum("normal", "urgente"), default="normal")
    fecha_hora_ingreso = db.Column(db.DateTime, default=datetime.utcnow)
    fecha_hora_llamado = db.Column(db.DateTime, nullable=True)
    fecha_hora_atencion = db.Column(db.DateTime, nullable=True)
    modulo_asignado = db.Column(db.String(50), nullable=True)


class PresupuestoHospitalario(db.Model):
    __tablename__ = "presupuesto_hospitalario"
    id = db.Column(db.Integer, primary_key=True)
    periodo = db.Column(db.String(20), nullable=False)
    monto_asignado = db.Column(db.Numeric(12, 2), nullable=False)
    monto_ejecutado_servicio_social = db.Column(db.Numeric(12, 2), default=0)
    descripcion = db.Column(db.String(300))
    fecha_actualizacion = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Vacunacion(db.Model):
    __tablename__ = "vacunacion"
    id = db.Column(db.Integer, primary_key=True)
    paciente_id = db.Column(db.Integer, db.ForeignKey("pacientes.id"), nullable=False)
    es_estudiante = db.Column(db.Boolean, default=False)
    esquema_completo = db.Column(db.Boolean, default=False)
    vacunas_pendientes = db.Column(db.Text)
    fecha_actualizacion = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Establecimiento(db.Model):
    __tablename__ = "establecimientos"
    id_establecimiento = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(150), nullable=False)
    tipo = db.Column(db.String(50))
    direccion = db.Column(db.String(250))
    departamento = db.Column(db.String(100))
    municipio = db.Column(db.String(100))
    telefono = db.Column(db.String(20))
    estado_servicio = db.Column(db.String(50), default="ACTIVO")
    tipo_atencion_disponible = db.Column(db.String(150))


class Practicante(db.Model):
    __tablename__ = "practicantes"
    id_practicante = db.Column(db.Integer, primary_key=True)
    dpi = db.Column(db.String(20), unique=True, nullable=False)
    nombres = db.Column(db.String(100), nullable=False)
    apellidos = db.Column(db.String(100), nullable=False)
    universidad = db.Column(db.String(100))
    carrera = db.Column(db.String(100))
    fecha_inicio = db.Column(db.Date)
    fecha_fin = db.Column(db.Date)
    supervisor = db.Column(db.String(100))
    estado = db.Column(db.String(20), default="ACTIVO")


class HorasPractica(db.Model):
    __tablename__ = "horas_practica"
    id_hora = db.Column(db.Integer, primary_key=True)
    id_practicante = db.Column(db.Integer, db.ForeignKey("practicantes.id_practicante"), nullable=False)
    fecha = db.Column(db.Date, nullable=False)
    horas = db.Column(db.Integer, nullable=False)
    actividad = db.Column(db.Text)