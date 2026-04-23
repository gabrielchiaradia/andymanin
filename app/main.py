import os
import logging
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from database import init_db
import database as db_module
from transcriber import transcribe_audio
from llm import parse_message
from tasks import (
    handle_compra,
    handle_venta_pendiente,
    handle_confirmacion,
    handle_agregar_contacto,
    handle_eliminar_contacto,
    handle_eliminar_producto,
    handle_limpiar_stock,
    handle_entrada_mercado,
    handle_gasto_mercado,
    handle_regreso_mercado,
    handle_cobro_cliente,
)
from reports import send_reporte_diario, send_saldo_caja, send_stock_actual, send_lista_clientes
from whatsapp import download_audio, send_text_message

logger = logging.getLogger(__name__)

app = FastAPI()

OWNER_NUMBER = os.getenv("OWNER_NUMBER")

TEXT_COMMANDS = {
    "SI": handle_confirmacion,
    "NO": lambda n: handle_confirmacion(n, confirmar=False),
    "REPORTE DIARIO": send_reporte_diario,
    "DAME EL SALDO": send_saldo_caja,
    "DAME EL STOCK": send_stock_actual,
    "DAME LOS CLIENTES": send_lista_clientes,
    "LIMPIAR STOCK": handle_limpiar_stock,
}


@app.on_event("startup")
async def startup():
    await init_db()


@app.post("/webhook")
async def receive_message(request: Request):
    form = await request.form()

    from_number = form.get("From", "").replace("whatsapp:", "")
    owner = OWNER_NUMBER.replace("whatsapp:", "").lstrip("+")
    from_clean = from_number.lstrip("+")

    if from_clean != owner:
        return PlainTextResponse("")

    num_media = int(form.get("NumMedia", 0))

    if num_media > 0:
        media_url = form.get("MediaUrl0", "")
        media_type = form.get("MediaContentType0", "")
        if "audio" in media_type:
            from whatsapp import download_audio
            audio_path = await download_audio(media_url)
            text = await transcribe_audio(audio_path)
            await route_voice(text, from_number)
    else:
        text = form.get("Body", "").strip().upper()
        await route_text(text, from_number)

    return PlainTextResponse("")


async def route_text(text: str, from_number: str):
    """Rutea comandos de texto del dueño."""

    # Comandos exactos
    if text in TEXT_COMMANDS:
        await TEXT_COMMANDS[text](from_number)
        return

    # AGREGAR NOMBRE TELEFONO
    if text.startswith("AGREGAR "):
        parts = text.split()
        if len(parts) == 3:
            await handle_agregar_contacto(parts[1], parts[2], from_number)
        else:
            await send_text_message(from_number, "❌ Formato: AGREGAR NOMBRE TELEFONO")
        return

    # ELIMINAR NOMBRE o ELIMINAR PRODUCTO NOMBRE
    if text.startswith("ELIMINAR "):
        parts = text.split()
        if len(parts) == 3 and parts[1] == "PRODUCTO":
            await handle_eliminar_producto(parts[2], from_number)
        elif len(parts) == 2:
            await handle_eliminar_contacto(parts[1], from_number)
        else:
            await send_text_message(from_number, "❌ Formato: ELIMINAR NOMBRE o ELIMINAR PRODUCTO NOMBRE")
        return

    await send_text_message(
        from_number,
        "❓ Comando no reconocido.\n\nComandos disponibles:\n• SI / NO\n• REPORTE DIARIO\n• DAME EL STOCK\n• DAME EL SALDO\n• DAME LOS CLIENTES\n• AGREGAR NOMBRE TELEFONO\n• ELIMINAR NOMBRE\n• ELIMINAR PRODUCTO NOMBRE",
    )


async def route_voice(text: str, from_number: str):
    """Parsea el mensaje de voz y lo rutea al handler correspondiente."""
    logger.info("Texto transcripto: %s", text)
    result = await parse_message(text)

    if result["tipo"] == "compra":
        await handle_compra(result["items"], from_number)
    elif result["tipo"] == "venta":
        await handle_venta_pendiente(result["cliente"], result["items"], from_number)
    elif result["tipo"] == "entrada_mercado":
        await handle_entrada_mercado(result["monto"], from_number)
    elif result["tipo"] == "gasto_mercado":
        await handle_gasto_mercado(result["monto"], from_number)
    elif result["tipo"] == "regreso_mercado":
        await handle_regreso_mercado(result["monto"], from_number)
    elif result["tipo"] == "cobro_cliente":
        await handle_cobro_cliente(result["cliente"], result["monto"], from_number)
    elif result["tipo"] == "consulta_saldo":
        await send_saldo_caja(from_number)
    elif result["tipo"] == "consulta_stock":
        await send_stock_actual(from_number)
    else:
        await send_text_message(from_number, f"❓ No entendí el mensaje.\nTranscripción: _{text}_")


@app.get("/health")
async def health():
    return {"status": "ok"}


# ── Modo de prueba ─────────────────────────────────────────────────────────────

class SimularRequest(BaseModel):
    texto: str


_mensajes_simulados: list[str] = []


async def _send_simulado(to: str, text: str):
    _mensajes_simulados.append(f"[→ {to}]\n{text}")


@app.post("/simular")
async def simular(req: SimularRequest):
    """
    Simula un mensaje del dueño sin usar WhatsApp ni persistir datos.
    Devuelve en la respuesta los mensajes que se habrían enviado.
    Ejemplo: {"texto": "10 papas a 5000, 20 cebollas a 3000"}
    """
    import whatsapp as wa_module
    _original_send = wa_module.send_text_message
    wa_module.send_text_message = _send_simulado
    _mensajes_simulados.clear()

    async with db_module.engine.connect() as conn:
        await conn.begin()
        _orig_session = db_module.SessionLocal
        db_module.SessionLocal = async_sessionmaker(conn, expire_on_commit=False, class_=AsyncSession)
        try:
            texto = req.texto.strip()
            texto_upper = texto.upper()

            if texto_upper in TEXT_COMMANDS:
                await TEXT_COMMANDS[texto_upper]("SIMULADO")
            elif texto_upper.startswith("AGREGAR "):
                parts = texto_upper.split()
                if len(parts) == 3:
                    await handle_agregar_contacto(parts[1], parts[2], "SIMULADO")
            elif texto_upper.startswith("ELIMINAR "):
                parts = texto_upper.split()
                if len(parts) == 2:
                    await handle_eliminar_contacto(parts[1], "SIMULADO")
            else:
                result = await parse_message(texto)
                if result["tipo"] == "compra":
                    await handle_compra(result["items"], "SIMULADO")
                elif result["tipo"] == "venta":
                    await handle_venta_pendiente(result["cliente"], result["items"], "SIMULADO")
                elif result["tipo"] == "entrada_mercado":
                    await handle_entrada_mercado(result["monto"], "SIMULADO")
                elif result["tipo"] == "gasto_mercado":
                    await handle_gasto_mercado(result["monto"], "SIMULADO")
                elif result["tipo"] == "regreso_mercado":
                    await handle_regreso_mercado(result["monto"], "SIMULADO")
                elif result["tipo"] == "cobro_cliente":
                    await handle_cobro_cliente(result["cliente"], result["monto"], "SIMULADO")
                elif result["tipo"] == "consulta_saldo":
                    await send_saldo_caja("SIMULADO")
                elif result["tipo"] == "consulta_stock":
                    await send_stock_actual("SIMULADO")
                else:
                    return {"error": "No se pudo interpretar el mensaje", "llm": result}

            return {"mensajes": _mensajes_simulados}
        finally:
            await conn.rollback()
            db_module.SessionLocal = _orig_session
            wa_module.send_text_message = _original_send
