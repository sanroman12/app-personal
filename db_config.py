from pymongo import MongoClient
from bson import ObjectId

client = MongoClient("mongodb://localhost:27017")
db = client["finanzas"]
transacciones_collection = db["transacciones"]

def serialize_document(document):
    """Convierte todos los ObjectId a cadenas para evitar errores de serialización."""
    if isinstance(document, ObjectId):
        return str(document)  # Convertir ObjectId a string
    elif isinstance(document, dict):
        return {key: serialize_document(value) for key, value in document.items()}
    elif isinstance(document, list):
        return [serialize_document(item) for item in document]
    return document
