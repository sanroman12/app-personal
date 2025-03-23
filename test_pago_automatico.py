import asyncio
from datetime import datetime
from routes.notificaciones import registrar_pago_automatico

async def test_pago():
    # Simula que hoy es 24 de marzo de 2025
    fecha_simulada = datetime(2025, 3, 24)

    # Llamar la función de pago automático
    saldo_actual = await registrar_pago_automatico()

    print(f"Saldo después del pago automático: {saldo_actual}")

# Ejecutar la prueba
asyncio.run(test_pago())
