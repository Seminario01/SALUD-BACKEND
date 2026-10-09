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