import os
import httpx
import tempfile

WA_TOKEN = os.getenv("WA_TOKEN")
WA_PHONE_ID = os.getenv("WA_PHONE_ID")
BASE_URL = "https://graph.facebook.com/v20.0"

HEADERS = {"Authorization": f"Bearer {WA_TOKEN}"}


async def download_audio(media_id: str) -> str:
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{BASE_URL}/{media_id}", headers=HEADERS)
        resp.raise_for_status()
        media_url = resp.json()["url"]

        audio_resp = await client.get(media_url, headers=HEADERS)
        audio_resp.raise_for_status()

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".ogg")
    tmp.write(audio_resp.content)
    tmp.close()
    return tmp.name


async def send_text_message(to: str, text: str):
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": text},
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{BASE_URL}/{WA_PHONE_ID}/messages",
            headers=HEADERS,
            json=payload,
        )
        resp.raise_for_status()


async def send_document(to: str, file_path: str, filename: str):
    """Sube el PDF a Meta y lo envía como documento."""
    async with httpx.AsyncClient() as client:
        # 1. Upload del archivo
        with open(file_path, "rb") as f:
            upload_resp = await client.post(
                f"{BASE_URL}/{WA_PHONE_ID}/media",
                headers={"Authorization": f"Bearer {WA_TOKEN}"},
                files={"file": (filename, f, "application/pdf")},
                data={"messaging_product": "whatsapp"},
            )
        upload_resp.raise_for_status()
        media_id = upload_resp.json()["id"]

        # 2. Envío del documento
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "document",
            "document": {
                "id": media_id,
                "filename": filename,
            },
        }
        resp = await client.post(
            f"{BASE_URL}/{WA_PHONE_ID}/messages",
            headers=HEADERS,
            json=payload,
        )
        resp.raise_for_status()
