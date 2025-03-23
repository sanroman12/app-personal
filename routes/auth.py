import jwt
from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException, Security, Depends
from fastapi.security import HTTPBearer
from pydantic import BaseModel

# Configuración de seguridad
SECRET_KEY = "3b4f1b9acbc08af27dfcbc9c4488807a97bf47c880af36b8b26a39e5d50e9a11"  # Usa una clave más segura en producción
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30
security = HTTPBearer()
router = APIRouter()  # Asegura que el router esté definido correctamente

# Modelo de datos para autenticación
class TokenResponse(BaseModel):
    access_token: str
    token_type: str

def generar_token(data: dict, expires_delta: timedelta):
    """Genera un token JWT con los datos del usuario."""
    to_encode = data.copy()
    expire = datetime.utcnow() + expires_delta
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def verificar_token(token: str = Security(security)):
    """Verifica la validez del token JWT."""
    try:
        payload = jwt.decode(token.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        return payload  # Devuelve la información del usuario si es válido
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expirado")
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Token inválido")

def verificar_admin(token: str = Security(security)):
    """Verifica si el usuario es administrador."""
    payload = verificar_token(token)
    if payload.get("rol") != "admin":
        raise HTTPException(status_code=403, detail="Acceso denegado")
    return payload["sub"]

@router.post("/login", response_model=TokenResponse)
async def login(correo: str, password: str):
    """Simulación de login, en producción esto consultaría la base de datos."""
    if correo == "admin@example.com" and password == "adminpass":
        access_token = generar_token({"sub": correo, "rol": "admin"}, timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
        return {"access_token": access_token, "token_type": "bearer"}
    elif correo == "user@example.com" and password == "userpass":
        access_token = generar_token({"sub": correo, "rol": "usuario"}, timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
        return {"access_token": access_token, "token_type": "bearer"}
    else:
        raise HTTPException(status_code=401, detail="Credenciales incorrectas")
