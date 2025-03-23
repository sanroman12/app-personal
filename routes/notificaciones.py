from fastapi import APIRouter, HTTPException, Query, Depends
from models.transaccion import Transaccion
from datetime import datetime, timedelta
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel
from typing import List, Optional
import re
from db_config import db, transacciones_collection
from bson import ObjectId
import requests

# Configuración de MongoDB
MONGO_URI = "mongodb://localhost:27017"
client = AsyncIOMotorClient(MONGO_URI)
db = client["base_central"]  # Nombre de la base de datos
coleccion = db["notificaciones"]  # Colección de notificaciones
transacciones = db["transacciones"]  # Colección donde guardaremos los movimientos
categorias_origen_collection = db["categorias_origen"]
origenes_pendientes_collection = db["origenes_pendientes"]

# Crear router de FastAPI
router = APIRouter()


MONTO_REGEX = re.compile(r'\$([\d,]+(?:\.\d{2})?)')

class NotificacionInput(BaseModel):
    mensaje: str


# Definir modelo de datos para la notificación
class Notificacion(BaseModel):
    tipo: str
    descripcion: str
    cantidad: float
    fecha: datetime

class TransaccionResponse(BaseModel):
    tipo: str
    descripcion: str
    cantidad: float
    fecha: datetime
    categoria: str

class CategoriaInput(BaseModel):
    origen: str
    categoria: str


class CategoriasMultiplesInput(BaseModel):
    categorias: List[CategoriaInput]


class PagoRequest(BaseModel):
    monto_pagado: float


def serialize_document(document):
    """Convierte todos los ObjectId a cadenas para evitar errores de serialización."""
    if isinstance(document, ObjectId):
        return str(document)
    elif isinstance(document, dict):
        return {key: serialize_document(value) for key, value in document.items()}
    elif isinstance(document, list):
        return [serialize_document(item) for item in document]
    return document


def obtener_origen(mensaje):
    palabras = mensaje.split()
    if "en" in palabras and "con" in palabras:
        try:
            indice_en = palabras.index("en")
            indice_con = palabras.index("con")
            return " ".join(palabras[indice_en + 1 : indice_con])
        except:
            return None
    return None

# 🔹 Buscar categoría de un origen
async def clasificar_origen(origen):
    categoria = await categorias_origen_collection.find_one({"origen": origen})
    if categoria:
        return categoria["categoria"]
    else:
        await origenes_pendientes_collection.update_one(
            {"origen": origen}, {"$set": {"origen": origen}}, upsert=True
        )
        return "pendiente"


@router.get("/notificaciones/transacciones")
async def obtener_transacciones(
    tipo: Optional[str] = Query(None, description="Filtrar por tipo de transacción"),
    origen: Optional[str] = Query(None, description="Filtrar por origen (cuenta_nu, tarjeta_credito)"),
    limite: Optional[int] = Query(10, description="Número máximo de transacciones a devolver")
):
    filtros = {}

    if tipo:
        filtros["tipo"] = tipo
    if origen:
        filtros["origen"] = origen

    # Obtener cursor de MongoDB
    documentos_cursor = transacciones_collection.find(filtros).sort("fecha", -1)

    # ✅ Aquí quitamos el `await`, ya que `to_list()` devuelve una lista directamente
    documentos = documentos_cursor.to_list(length=limite)

    # Convertir ObjectId a string para evitar errores de serialización
    documentos = [serialize_document(doc) for doc in documentos]

    return {"transacciones": documentos}




@router.post("/notificaciones/registrar")
async def registrar_notificacion(data: NotificacionInput):
    mensaje = data.mensaje
    monto_match = MONTO_REGEX.search(mensaje)

    if not monto_match:
        return {"mensaje": "No se encontró monto en el mensaje"}

    monto = float(monto_match.group(1).replace(",", ""))
    fecha_actual = datetime.utcnow()

    if "Compra aprobada" in mensaje:
        tipo = "compra"
        cuenta = "cuenta_credito" if "tarjeta con terminación" in mensaje else "cuenta_debito"
    elif "Recibiste una transferencia" in mensaje:
        tipo = "pago_recibido"
        cuenta = "cuenta_debito"
    elif "Transferencia exitosa" in mensaje:
        tipo = "transferencia"
        cuenta = "cuenta_debito"
    elif "Recibimos tu pago" in mensaje:
        tipo = "pago_tarjeta"
        cuenta = "cuenta_credito"

        origen = obtener_origen(mensaje)
        categoria = await clasificar_origen(origen) if origen else "pendiente"

        # Registrar el pago con la función existente
        resultado_pago = await registrar_pago_credito(monto)

        monto *= -1

        # Guardar ambas transacciones (afectando débito y crédito)
        transaccion = {
            "tipo": tipo,
            "descripcion": mensaje,
            "cantidad": monto,
            "fecha": fecha_actual,
            "categoria": categoria,
            "cuenta": "cuenta_debito",
            "origen": origen
        }


        resultado = await transacciones.insert_one(transaccion)
        transaccion["_id"] = str(resultado.inserted_id)

        return {"mensaje": "Pago registrado", "transacciones": transaccion}

    else:
        raise HTTPException(status_code=400, detail="Tipo de notificación no reconocido.")

    # Ajustar monto según el tipo de transacción
    if tipo in ["compra", "transferencia"]:
        monto *= -1  # Hacerlo negativo porque es un gasto

    origen = obtener_origen(mensaje)
    categoria = await clasificar_origen(origen) if origen else "pendiente"

    if cuenta == "cuenta_credito":
        credito_temporal = await calcular_credito_extra()
        monto_temp = monto * -1
        if credito_temporal > 0:
            if credito_temporal > monto_temp:  #si el credito temporal es mayor a la compra
                await db.credito_extra.update_one(
                    {"_id": "credito_temporal"},
                    {"$inc": {"monto": monto }})

                transaccion = {
                    "tipo": tipo,
                    "descripcion": mensaje,
                    "cantidad": 0,
                    "fecha": fecha_actual,
                    "categoria": categoria,
                    "cuenta": cuenta,
                    "origen": origen
                }

            else:
                temp = credito_temporal + monto
                credito_temporal *= -1
                await db.credito_extra.update_one(
                    {"_id": "credito_temporal"},
                    {"$inc": {"monto": credito_temporal }})


                transaccion = {
                    "tipo": tipo,
                    "descripcion": mensaje,
                    "cantidad": temp,
                    "fecha": fecha_actual,
                    "categoria": categoria,
                    "cuenta": cuenta,
                    "origen": origen
                }

        else:
            transaccion = {
                "tipo": tipo,
                "descripcion": mensaje,
                "cantidad": monto,
                "fecha": fecha_actual,
                "categoria": categoria,
                "cuenta": cuenta,
                "origen": origen
            }

    else:
        # Guardar una sola transacción
        transaccion = {
            "tipo": tipo,
            "descripcion": mensaje,
            "cantidad": monto,
            "fecha": fecha_actual,
            "categoria": categoria,
            "cuenta": cuenta,
            "origen": origen
        }

    # Guardar la transacción en MongoDB
    resultado = await transacciones.insert_one(transaccion)
    transaccion["_id"] = str(resultado.inserted_id)  # Convertir ObjectId a string

    return {"mensaje": "Transacción registrada", "transaccion": transaccion}





@router.get("/api/transacciones", response_model=List[TransaccionResponse])
async def obtener_transacciones_api(
    fecha_inicio: Optional[str] = Query(None, description="Fecha de inicio en formato YYYY-MM-DD"),
    fecha_fin: Optional[str] = Query(None, description="Fecha de fin en formato YYYY-MM-DD"),
    categoria: Optional[str] = Query(None, description="Filtrar por categoría (debito/credito)")
):
    """
    Obtiene transacciones registradas en MongoDB con opción de filtrar por fecha y categoría.
    """
    try:
        query = {}

        # Filtrar por fecha si se proporciona
        if fecha_inicio or fecha_fin:
            query["fecha"] = {}
            if fecha_inicio:
                query["fecha"]["$gte"] = datetime.strptime(fecha_inicio, "%Y-%m-%d")
            if fecha_fin:
                query["fecha"]["$lte"] = datetime.strptime(fecha_fin, "%Y-%m-%d")

        # Filtrar por categoría si se proporciona
        if categoria:
            query["categoria"] = categoria

        # Obtener transacciones filtradas
        transacciones_cursor = transacciones.find(query).sort("fecha", -1)
        transacciones_lista = await transacciones_cursor.to_list(length=100)

        if not transacciones_lista:
            return []

        # Serializar los documentos
        transacciones_lista = serialize_document(transacciones_lista)

        return transacciones_lista

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al obtener transacciones: {str(e)}")

# Función para clasificar notificaciones
def clasificar_notificacion(notificacion: Notificacion):
    tipo = notificacion.tipo.lower()
    descripcion = notificacion.descripcion.lower()

    if "compra aprobada" in tipo:
        if "cuenta nu" in descripcion:
            return "debito"
        elif "tarjeta con terminación" in descripcion:
            return "credito"

    elif "recibiste una transferencia" in tipo:
        return "debito"

    elif "transferencia exitosa" in tipo:
        return "debito"

    elif "recibimos tu pago" in tipo:
        return "credito"

    return None  # No guardar si es una compra rechazada u otro caso no relevante

@router.post("/api/notificaciones")
async def recibir_notificacion(notificacion: Notificacion):
    """
    Recibe una notificación desde el celular, la clasifica y la almacena en MongoDB.
    """
    try:
        categoria = clasificar_notificacion(notificacion)
        if categoria is None:
            return {"mensaje": "Notificación ignorada"}

        # Guardar en MongoDB
        nueva_transaccion = {
            "tipo": notificacion.tipo,
            "descripcion": notificacion.descripcion,
            "cantidad": notificacion.cantidad,
            "fecha": notificacion.fecha,
            "categoria": categoria
        }

        resultado = await transacciones.insert_one(nueva_transaccion)
        nueva_transaccion["_id"] = str(resultado.inserted_id)  # Convertir ObjectId a string

        return {
            "mensaje": "Transacción guardada",
            "transaccion": nueva_transaccion
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al guardar la notificación: {str(e)}")









"""
funciones de datos fincieros
"""

@router.get("/finanzas/balance/debito")
async def obtener_balance_debito():
    """
    Calcula el balance total de la cuenta de débito sumando todas las transacciones registradas.
    """

    # Consultar transacciones de la cuenta de débito en MongoDB
    transacciones_debito = await db.transacciones.find({
        "cuenta": "cuenta_debito"
    }).to_list(None)

    # Calcular balance sumando los montos
    balance_debito = sum(t["cantidad"] for t in transacciones_debito)

    return balance_debito



@router.get("/finanzas/credito/saldo_actual")
async def calcular_saldo_actual():
    fecha_actual = datetime.utcnow()

    # 📌 Determinar la fecha de corte actual
    if fecha_actual.day < 24:
        fecha_corte_actual = datetime(fecha_actual.year, fecha_actual.month - 1, 24)
    else:
        fecha_corte_actual = datetime(fecha_actual.year, fecha_actual.month, 24)

    # 📌 Determinar la fecha de corte siguiente
    if fecha_corte_actual.month == 12:
        fecha_corte_siguiente = datetime(fecha_corte_actual.year + 1, 1, 24)
    else:
        fecha_corte_siguiente = datetime(fecha_corte_actual.year, fecha_corte_actual.month + 1, 24)

    # 📌 Consultar el saldo de la cuenta de **crédito** en MongoDB
    saldo_actual_pipeline = [
        {"$match": {
            "fecha": {"$gte": fecha_corte_actual, "$lt": fecha_corte_siguiente},
            "cuenta": "cuenta_credito"  # 🔥 Filtrar solo por la cuenta de crédito
        }},
        {"$group": {
            "_id": None,
            "total": {"$sum": "$cantidad"}  # 🔥 Sumar solo los montos de la cuenta de crédito
        }}
    ]

    saldo_actual_result = await transacciones.aggregate(saldo_actual_pipeline).to_list(length=1)
    saldo_actual = saldo_actual_result[0]["total"] if saldo_actual_result else 0

    return saldo_actual





@router.get("/finanzas/credito/saldo_a_pagar")
async def calcular_saldo_a_pagar():
    fecha_actual = datetime.utcnow()

    # Determinar la fecha de corte del mes anterior
    if fecha_actual.day < 24:
        fecha_corte_anterior = datetime(fecha_actual.year, fecha_actual.month - 2, 24)
        fecha_corte_pasado = datetime(fecha_actual.year, fecha_actual.month - 1, 24)
    else:
        fecha_corte_anterior = datetime(fecha_actual.year, fecha_actual.month - 1, 24)
        fecha_corte_pasado = datetime(fecha_actual.year, fecha_actual.month, 24)

    # Consulta para obtener el saldo a pagar
    saldo_a_pagar_pipeline = [
        {"$match": {
            "fecha": {"$gte": fecha_corte_anterior, "$lt": fecha_corte_pasado},
            "cuenta": "cuenta_credito"
        }},
        {"$group": {"_id": None, "total": {"$sum": "$cantidad"}}}
    ]

    saldo_a_pagar_result = await transacciones.aggregate(saldo_a_pagar_pipeline).to_list(1)
    saldo_a_pagar = saldo_a_pagar_result[0]["total"] if saldo_a_pagar_result else 0

    return saldo_a_pagar





@router.get("/finanzas/credito/saldo_a_meses")
async def obtener_saldo_mensual_total():
    """ Suma el total de saldo pendiente a meses. """
    pipeline = [
        {"$group": {"_id": None, "total": {"$sum": "$monto"}}}
    ]

    resultado = await db.saldo_mensual.aggregate(pipeline).to_list(length=1)

    saldo_total = resultado[0]["total"] if resultado else 0

    return saldo_total




@router.get("/finanzas/credito/total_a_pagar")
async def calcular_total_a_pagar():

    
    saldo_a_pagar = await calcular_saldo_a_pagar()
    saldo_actual = await calcular_saldo_actual()
    saldo_mensual_total = await obtener_saldo_mensual_total()

    
    a_pagar_total = saldo_a_pagar + saldo_actual - saldo_mensual_total

    return a_pagar_total



@router.get("/finanzas/credito/credito_disponible")
async def calcular_credito_disponible():
    saldo_credito = 15000.00  # Crédito base
    credito_temporal = await calcular_credito_extra()
    saldo_credito += credito_temporal
    return saldo_credito




@router.get("/finanzas/credito/balance_credito")
async def calcular_balance_credito():
    """Calcula el balance de crédito disponible"""

    total_credito = await calcular_credito_disponible()  # Límite de crédito
    total_a_pagar = await calcular_total_a_pagar()


    balance_credito = total_credito + total_a_pagar

    return balance_credito


@router.get("/finanzas/credito/credito_extra")
async def calcular_credito_extra():
    credito_temporal = await db.credito_extra.find_one({"_id": "credito_temporal"})
    return credito_temporal["monto"]









"""
funciones de automaticacion
"""


@router.post("/finanzas/credito/auto_meses")
async def cobrar_saldo_mensual():
    """ Cobra el saldo mensual del próximo mes y lo registra como una compra. """

    fecha_actual = datetime.utcnow()

    # Determinar el próximo mes
    if fecha_actual.month == 12:  
        mes_siguiente = f"{fecha_actual.year + 1}-01"
    else:
        mes_siguiente = f"{fecha_actual.year}-{fecha_actual.month + 1:02d}"

    # Buscar el saldo a cobrar del próximo mes
    saldo_pendiente = await db.saldo_mensual.find_one({"mes": mes_siguiente})

    if not saldo_pendiente:
        return {"mensaje": f"No hay saldo a meses para {mes_siguiente}."}

    monto = saldo_pendiente["monto"]

    # Registrar la transacción como si fuera una compra
    nueva_transaccion = {
        "tipo": "compra",
        "descripcion": f"Cobro automático de saldo a meses ({mes_siguiente})",
        "cantidad": -monto,  # Se descuenta el monto
        "fecha": fecha_actual,
        "categoria": "saldo_mensual",
        "cuenta": "cuenta_credito",
        "origen": "Cobro Automático"
    }

    # Insertar la transacción
    await db.transacciones.insert_one(nueva_transaccion)

    # Eliminar el saldo a meses cobrado
    await db.saldo_mensual.delete_one({"_id": saldo_pendiente["_id"]})

    return {
        "mensaje": f"Saldo a meses de {mes_siguiente} cobrado y registrado.",
        "monto": monto
    }



@router.post("/finanzas/credito/registrar_pago")
async def registrar_pago_credito(monto):
    """Distribuye un pago recibido en saldo a pagar, saldo actual y pagos a meses"""

    monto_pagado = monto  # 🔹 Extraer correctamente desde un diccionario

    # 1️⃣ Obtener los saldos actuales
    saldo_a_pagar = (await calcular_saldo_a_pagar())   # 🟥 Es negativo
    saldo_actual = (await calcular_saldo_actual())   # 🟥 Es negativo
    saldo_a_meses = await obtener_saldo_mensual_total()  # 🟩 Es positivo

    fecha_actual = datetime.utcnow()

    # 🟢 1. Si hay saldo a pagar, registramos el pago en transacciones con fecha del mes pasado
    if saldo_a_pagar < 0:
        monto_a_pagar = min(abs(saldo_a_pagar), abs(monto_pagado))
        monto_pagado -= monto_a_pagar  # Reducimos el monto que queda por pagar

        pago_a_pagar = {
            "tipo": "pago_tarjeta",
            "descripcion": "Pago de saldo a pagar",
            "cantidad": monto_a_pagar,  # 🟢 Se registra positivo para compensar el saldo a pagar
            "fecha": fecha_actual - timedelta(days=30),  # 🕒 Fecha en el mes pasado
            "categoria": "pago_tarjeta",
            "cuenta": "cuenta_credito",
            "origen": "Banco"
        }
        await db.transacciones.insert_one(pago_a_pagar)

    # 🟢 2. Si hay saldo actual, registramos el pago en transacciones con fecha actual
    if saldo_actual < 0 and monto_pagado > 0:
        monto_a_pagar = min(abs(saldo_actual), abs(monto_pagado))
        monto_pagado -= monto_a_pagar  # Reducimos el monto que queda por pagar

        pago_actual = {
            "tipo": "pago_tarjeta",
            "descripcion": "Pago de saldo actual",
            "cantidad": monto_a_pagar,  # 🟢 Se registra positivo para compensar saldo actual
            "fecha": fecha_actual,  # 📅 Fecha actual
            "categoria": "pago_tarjeta",
            "cuenta": "cuenta_credito",
            "origen": "Banco"
        }
        await db.transacciones.insert_one(pago_actual)

    # 🟢 3. Si aún queda monto por pagar, se distribuye en pagos a meses
    if monto_pagado > 0:
        pagos_mensuales = await db.saldo_mensual.find().sort("mes", 1).to_list(length=None)
        for pago_mensual in pagos_mensuales:
            if monto_pagado >= pago_mensual["monto"]:  # 🔹 Si el pago cubre todo el mes
                monto_pagado -= pago_mensual["monto"]  # 🏷️ Restamos del monto pagado
                await db.saldo_mensual.delete_one({"_id": pago_mensual["_id"]})  # ✅ Eliminamos mes pagado
            else:  # 🔹 Si no cubre todo, solo reduce lo que puede
                await db.saldo_mensual.update_one(
                    {"_id": pago_mensual["_id"]},
                    {"$inc": {"monto": -monto_pagado}}  # ✅ Restar la cantidad pagada del mes actual
                )
                monto_pagado = 0  # ✅ Se aplicó todo el pago
                break  # 🔹 No seguimos con más meses porque ya se usó todo el dinero


    if monto_pagado > 0:

        credito_extra = abs(monto_pagado)  # Convertimos en positivo para sumarlo
        await db.credito_extra.update_one(
            {"_id": "credito_temporal"},
            {"$inc": {"monto": credito_extra}},
            upsert=True  # 🔹 Si no existe, lo crea automáticamente
        )
        monto_pagado = 0


    return {"mensaje": "Pago registrado correctamente"}














"""
funciones de origen
"""


@router.get("/origenes_pendientes")
async def obtener_origenes_pendientes():
    pendientes = await origenes_pendientes_collection.find().to_list(100)
    return [{"origen": p["origen"]} for p in pendientes]

# 🔹 Agregar una categoría (sin importar si está pendiente o no)
@router.post("/categorizar_origen")
async def categorizar_origen(data: CategoriaInput):
    # Guardar en la base de datos de categorías
    await categorias_origen_collection.update_one(
        {"origen": data.origen},
        {"$set": {"origen": data.origen, "categoria": data.categoria}},
        upsert=True
    )

    # Eliminar de los pendientes si existe
    await origenes_pendientes_collection.delete_one({"origen": data.origen})

    return {"mensaje": f"Origen '{data.origen}' categorizado como '{data.categoria}'"}

# 🔹 Agregar múltiples categorías de una sola vez
@router.post("/categorizar_multiples")
async def categorizar_multiples(data: CategoriasMultiplesInput):
    for item in data.categorias:
        await categorias_origen_collection.update_one(
            {"origen": item.origen},
            {"$set": {"origen": item.origen, "categoria": item.categoria}},
            upsert=True
        )
        await origenes_pendientes_collection.delete_one({"origen": item.origen})

    return {"mensaje": "Categorías agregadas correctamente"}

