"""Validación común de los datos que llegan en el cuerpo JSON.

Cada función devuelve el valor limpio (o None si el campo viene vacío y no es
obligatorio) y lanza DatoInvalido si el dato no sirve. app.py convierte
DatoInvalido en una respuesta 400 con el mismo formato del resto de la API.
"""
import re
from datetime import date
from decimal import Decimal, InvalidOperation


class DatoInvalido(Exception):
    """400 datos_invalidos; con status=409, 409 ya_existe (duplicados)."""
    def __init__(self, mensaje, status=400):
        super().__init__(mensaje)
        self.mensaje = mensaje
        self.status = status


def texto(data, campo, maximo, obligatorio=False, minimo=1, etiqueta=None):
    """Texto de 1..maximo caracteres, sin espacios a los lados."""
    nombre = etiqueta or campo
    valor = data.get(campo)
    if valor is None or (isinstance(valor, str) and not valor.strip()):
        if obligatorio:
            raise DatoInvalido(f"{nombre} es obligatorio")
        return None
    if not isinstance(valor, str):
        raise DatoInvalido(f"{nombre} debe ser texto")
    valor = valor.strip()
    if len(valor) < minimo:
        raise DatoInvalido(f"{nombre} debe tener al menos {minimo} caracteres")
    if len(valor) > maximo:
        raise DatoInvalido(f"{nombre} admite como máximo {maximo} caracteres")
    return valor


def opcion(data, campo, opciones, obligatorio=False, etiqueta=None):
    """Uno de los valores permitidos (comparación exacta)."""
    valor = texto(data, campo, 100, obligatorio, etiqueta=etiqueta)
    if valor is not None and valor not in opciones:
        raise DatoInvalido(f"{etiqueta or campo} debe ser uno de: {', '.join(opciones)}")
    return valor


def cui(data, campo="cui", obligatorio=False):
    """CUI (DPI) de Guatemala: exactamente 13 dígitos."""
    valor = texto(data, campo, 13, obligatorio, etiqueta="CUI")
    if valor is not None and not re.fullmatch(r"\d{13}", valor):
        raise DatoInvalido("El CUI debe tener exactamente 13 dígitos, sin espacios ni guiones")
    return valor


def telefono(data, campo="telefono"):
    """8 a 15 dígitos; se permiten +, espacios y guiones como separadores."""
    valor = texto(data, campo, 20, etiqueta="Teléfono")
    if valor is not None and not (re.fullmatch(r"\+?[\d\s-]+", valor) and 8 <= len(re.sub(r"\D", "", valor)) <= 15):
        raise DatoInvalido("El teléfono debe tener entre 8 y 15 dígitos")
    return valor


def fecha_pasada(data, campo, etiqueta=None):
    """Fecha AAAA-MM-DD que no está en el futuro ni antes de 1900."""
    nombre = etiqueta or campo
    valor = texto(data, campo, 10, etiqueta=nombre)
    if valor is None:
        return None
    try:
        dia = date.fromisoformat(valor)
    except ValueError:
        raise DatoInvalido(f"{nombre} inválida (AAAA-MM-DD)")
    if dia > date.today() or dia.year < 1900:
        raise DatoInvalido(f"{nombre} no puede estar en el futuro ni ser anterior a 1900")
    return dia


def monto(valor, etiqueta="El monto", minimo=Decimal("0"), maximo=Decimal("99999999.99")):
    """Cantidad en quetzales con 2 decimales, dentro de [minimo, maximo].
    Rechaza texto, booleanos, NaN, infinito y números que no caben en la columna."""
    if isinstance(valor, bool) or not isinstance(valor, (int, float, str)):
        raise DatoInvalido(f"{etiqueta} debe ser un número")
    try:
        cantidad = Decimal(str(valor).strip())
    except InvalidOperation:
        raise DatoInvalido(f"{etiqueta} debe ser un número")
    if not cantidad.is_finite() or not (minimo <= cantidad <= maximo):
        raise DatoInvalido(f"{etiqueta} debe estar entre Q{minimo} y Q{maximo}")
    return cantidad.quantize(Decimal("0.01"))


def booleano(data, campo, defecto=False):
    """true/false de JSON; cualquier otro tipo se rechaza."""
    valor = data.get(campo, defecto)
    if not isinstance(valor, bool):
        raise DatoInvalido(f"{campo} debe ser true o false")
    return valor
