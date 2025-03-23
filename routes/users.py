from fastapi import APIRouter, HTTPException, Depends
from db_config import db, transacciones_collection
from models.usuario import Usuario
from bson import ObjectId
from .auth import verificar_token, verificar_admin

router = APIRouter()

@router.get("/usuarios", dependencies=[Depends(verificar_admin)])
async def obtener_usuarios():
    usuarios = await database["usuarios"].find().to_list(100)
    return [{"id": str(u["_id"]), **u} for u in usuarios]
