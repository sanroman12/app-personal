from pydantic import BaseModel
from typing import Optional

class Usuario(BaseModel):
    nombre: str
    edad: int
    correo: str
    password: str
    rol: str = "usuario"
    telefono: Optional[str] = None
