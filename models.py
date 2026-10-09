from extensions import db
from datetime import datetime

# Nota: no existe tabla de usuarios. Los usuarios viven en el Login Único
# (Keycloak) y aquí se referencian por su `sub` (UUID, único e inmutable).
SUB_LEN = 36


class Paciente(db.Model):
    __tablename__ = "pacientes"
    id = db.Column(db.Integer, primary_key=True)
    # `sub` del ciudadano en el Login Único, si el paciente tiene cuenta.
    # Es lo que permite que un ciudadano vea SOLO su propio registro.
    usuario_sub = db.Column(db.String(SUB_LEN), unique=True, nullable=True)
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
    medico_sub = db.Column(db.String(SUB_LEN))  # `sub` del médico en el Login Único
    fecha_hora = db.Column(db.DateTime, nullable=False)
    estado = db.Column(db.Enum("pendiente", "confirmada", "atendida", "cancelada"), default="pendiente")
    motivo = db.Column(db.String(300))
    costo = db.Column(db.Numeric(10, 2))
    pago_confirmado = db.Column(db.Boolean, default=False)
    fecha_creacion = db.Column(db.DateTime, default=datetime.utcnow)
    # Cobro en Tributario (obligación de pago). Ver docs/INTEGRACIONES.md
    numero_referencia = db.Column(db.String(20), unique=True)      # SAL-AAAA-NNNNNN
    estado_cobro = db.Column(db.String(20))                         # PENDIENTE, PAGADO, ANULADO
    fecha_vencimiento = db.Column(db.Date)
    numero_autorizacion = db.Column(db.String(60))
    fecha_pago = db.Column(db.DateTime)


class ExpedienteClinico(db.Model):
    __tablename__ = "expedientes_clinicos"
    id = db.Column(db.Integer, primary_key=True)
    paciente_id = db.Column(db.Integer, db.ForeignKey("pacientes.id"), nullable=False)
    cita_id = db.Column(db.Integer, db.ForeignKey("citas_medicas.id"), nullable=True)
    medico_sub = db.Column(db.String(SUB_LEN))  # `sub` del médico en el Login Único
    diagnostico = db.Column(db.Text)
    tratamiento = db.Column(db.Text)
    notas = db.Column(db.Text)
    # Hora local del servidor (TZ=America/Guatemala), igual que los turnos.
    fecha_atencion = db.Column(db.DateTime, default=datetime.now)


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

class BitacoraIntegracion(db.Model):
    """Registro de cada llamada entre Salud y otro módulo (en ambas direcciones).
    Los CUI se guardan enmascarados (solo los últimos 4 dígitos)."""
    __tablename__ = "bitacora_integraciones"
    id = db.Column(db.Integer, primary_key=True)
    fecha = db.Column(db.DateTime, default=datetime.now, nullable=False, index=True)
    direccion = db.Column(db.Enum("saliente", "entrante"), nullable=False)
    modulo = db.Column(db.String(30), nullable=False)
    operacion = db.Column(db.String(120), nullable=False)
    metodo = db.Column(db.String(10), nullable=False)
    ruta = db.Column(db.String(255), nullable=False)
    estado_http = db.Column(db.Integer)
    resultado = db.Column(db.String(30), nullable=False)
    duracion_ms = db.Column(db.Integer)
    simulado = db.Column(db.Boolean, default=False, nullable=False)
    usuario = db.Column(db.String(100))
    detalle = db.Column(db.String(255))


# ---------------------------------------------------------------------------
# Farmacia: medicamentos, recetas e inventario (tablas de salud_db)
# ---------------------------------------------------------------------------
class Medicamento(db.Model):
    __tablename__ = "medicamentos"
    id = db.Column("id_medicamento", db.Integer, primary_key=True)
    codigo = db.Column(db.String(50), unique=True, nullable=False)
    nombre = db.Column(db.String(100), nullable=False)
    presentacion = db.Column(db.String(100))           # "Tableta 500 mg", "Jarabe 120 ml"...
    descripcion = db.Column(db.Text)
    existencia = db.Column(db.Integer, nullable=False, default=0)
    stock_minimo = db.Column(db.Integer, default=10)
    precio = db.Column(db.Numeric(10, 2))


class Receta(db.Model):
    __tablename__ = "recetas"
    id = db.Column("id_receta", db.Integer, primary_key=True)
    paciente_id = db.Column("id_paciente", db.Integer, db.ForeignKey("pacientes.id"), nullable=False)
    id_medico = db.Column(db.Integer)                   # tabla medicos (opcional)
    medico_sub = db.Column(db.String(SUB_LEN))          # médico del Login Único que receta
    medico_nombre = db.Column(db.String(150))           # nombre del médico, para imprimir la receta
    expediente_id = db.Column(db.Integer)               # atención del expediente (opcional)
    fecha = db.Column(db.DateTime, default=datetime.now)
    indicaciones = db.Column(db.Text)
    estado = db.Column(db.String(20), default="PENDIENTE")   # PENDIENTE, DESPACHADA, ANULADA
    despachado_por = db.Column(db.String(SUB_LEN))      # sub de quien despachó (Farmacia)
    fecha_despacho = db.Column(db.DateTime)
    motivo_anulacion = db.Column(db.String(255))
    detalles = db.relationship("DetalleReceta", backref="receta", lazy="joined", order_by="DetalleReceta.id")


class DetalleReceta(db.Model):
    __tablename__ = "detalle_receta"
    id = db.Column("id_detalle", db.Integer, primary_key=True)
    receta_id = db.Column("id_receta", db.Integer, db.ForeignKey("recetas.id_receta"), nullable=False)
    medicamento_id = db.Column("id_medicamento", db.Integer, db.ForeignKey("medicamentos.id_medicamento"), nullable=False)
    cantidad = db.Column(db.Integer, nullable=False)
    dosis = db.Column(db.String(200))                   # "1 tableta cada 8 horas por 5 días"
    medicamento = db.relationship("Medicamento", lazy="joined")


class MovimientoInventario(db.Model):
    __tablename__ = "movimientos_inventario"
    id = db.Column("id_movimiento", db.Integer, primary_key=True)
    medicamento_id = db.Column("id_medicamento", db.Integer, db.ForeignKey("medicamentos.id_medicamento"), nullable=False)
    tipo_movimiento = db.Column(db.String(20), nullable=False)   # ENTRADA, SALIDA, AJUSTE
    cantidad = db.Column(db.Integer, nullable=False)
    fecha = db.Column(db.DateTime, default=datetime.now)
    observacion = db.Column(db.Text)
    receta_id = db.Column(db.Integer)                   # SALIDA por despacho de receta
    usuario = db.Column(db.String(100))
