import os
import httpx
import tempfile

TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_WHATSAPP_NUMBER = os.getenv("TWILIO_WHATSAPP_NUMBER", "+14155238886")

BASE_URL = f"https://api.twilio.com/2010-04-01/Accounts/{TWILIO_ACCOUNT_SID}"


def _auth():
    return (TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)


def _to(number: str) -> str:
    if number.startswith("whatsapp:"):
        return number
    return f"whatsapp:{number}"


async def download_audio(media_url: str) -> str:
    async with httpx.AsyncClient() as client:
        resp = await client.get(media_url, auth=_auth())
        resp.raise_for_status()
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".ogg")
    tmp.write(resp.content)
    tmp.close()
    return tmp.name


async def send_text_message(to: str, text: str):
    if to == "SIMULADO":
        return
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{BASE_URL}/Messages.json",
            auth=_auth(),
            data={
                "From": _to(TWILIO_WHATSAPP_NUMBER),
                "To": _to(to),
                "Body": text,
            },
        )
        resp.raise_for_status()


async def send_document(to: str, file_path: str, filename: str):
    await send_text_message(to, f"📄 {filename} (reporte generado - PDF disponible próximamente)")
