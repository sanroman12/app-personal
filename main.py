from fastapi import FastAPI
from routes.users import router as users_router
from routes.auth import router as auth_router
from routes import notificaciones
from routes.notificaciones import router as notificaciones_router

app = FastAPI()

app.include_router(users_router, prefix="/api")
app.include_router(auth_router, prefix="/auth")
app.include_router(notificaciones.router)

@app.get("/")
async def root():
    return {"mensaje": "API funcionando"}
