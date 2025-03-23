from pydantic import BaseModel
from datetime import datetime

class Transaccion(BaseModel):
    tipo: str
    descripcion: str
    cantidad: float
    fecha: datetime
    categoria: str
    cuenta: str  # Asegúrate de que este campo existe en el modelo
