from routes.pacientes import pacientes_bp
from routes.citas import citas_bp
from routes.expedientes import expedientes_bp
from routes.recursos import recursos_bp
from routes.turnos import turnos_bp
from routes.presupuesto import presupuesto_bp
from routes.externos import externos_bp
from routes.vacunacion import vacunacion_bp
from routes.panel import panel_bp
from routes.integraciones import integraciones_bp
from routes.farmacia import farmacia_bp
from routes.hospitalizacion import hospitalizacion_bp
from routes.caja import caja_bp
from routes.auditoria import auditoria_bp
from routes.accesos import accesos_bp
from routes.reportes import reportes_bp
from routes.constancias import constancias_bp
from routes.laboratorio import laboratorio_bp

def registrar_rutas(app):
    app.register_blueprint(pacientes_bp)
    app.register_blueprint(citas_bp)
    app.register_blueprint(expedientes_bp)
    app.register_blueprint(recursos_bp)
    app.register_blueprint(turnos_bp)
    app.register_blueprint(presupuesto_bp)
    app.register_blueprint(externos_bp)
    app.register_blueprint(vacunacion_bp)
    app.register_blueprint(panel_bp)
    app.register_blueprint(integraciones_bp)
    app.register_blueprint(farmacia_bp)
    app.register_blueprint(hospitalizacion_bp)
    app.register_blueprint(caja_bp)
    app.register_blueprint(auditoria_bp)
    app.register_blueprint(accesos_bp)
    app.register_blueprint(reportes_bp)
    app.register_blueprint(constancias_bp)
    app.register_blueprint(laboratorio_bp)