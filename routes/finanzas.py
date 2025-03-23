from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from database import database
from datetime import datetime

router = APIRouter()

# Modelo para recibir la notificación
class Notificacion(BaseModel):
    mensaje: str

@router.post("/notificaciones")
async def recibir_notificacion(data: Notificacion):
    """
    Recibe una notificación de Nu y la almacena en MongoDB.
    """
    mensaje = data.mensaje

    # Extraer información de la notificación (Ejemplo: "Compra de $150 en Amazon")
    try:
        tipo, monto, descripcion = procesar_mensaje(mensaje)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error al procesar mensaje: {str(e)}")

    # Guardar en MongoDB
    transaccion = {
        "tipo": tipo,  # "ingreso" o "gasto"
        "monto": monto,
        "descripcion": descripcion,
        "fecha": datetime.utcnow()
    }
    await database["finanzas"].insert_one(transaccion)

    return {"mensaje": "Notificación recibida y procesada con éxito"}


import re

def procesar_mensaje(mensaje: str):
    """
    Extrae el tipo de transacción, monto y descripción desde el mensaje de Nu.
    """
    # Expresión regular para capturar transacciones (Ejemplo: "Compra de $150 en Amazon")
    match = re.search(r"(\w+) de \$(\d+(\.\d{1,2})?) en (.+)", mensaje)

    if match:
        tipo = match.group(1).lower()  # "compra", "retiro", etc.
        monto = float(match.group(2))  # Convertir a número
        descripcion = match.group(4)   # "Amazon", "OXXO", etc.

        # Convertir tipo a "ingreso" o "gasto"
        if tipo in ["compra", "retiro", "pago"]:
            tipo = "gasto"
        else:
            tipo = "ingreso"

        return tipo, monto, descripcion

    raise ValueError("Formato de mensaje no reconocido")

