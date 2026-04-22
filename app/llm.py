import os
import json
import logging
import anthropic

logger = logging.getLogger(__name__)
client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

SYSTEM_PROMPT = """Sos un asistente para una verdulería argentina. Analizás mensajes de voz transcriptos del dueño.

Determiná si el mensaje es una COMPRA (el dueño compró mercadería) o una VENTA (el dueño dejó mercadería a un cliente).

COMPRA - ejemplos:
- "10 papas a 5, 20 cebollas a 10"
- "compré 5 kilos de zanahoria a 3 y media docena de zapallo a 7"

VENTA - ejemplos:
- "le dejo a JOSE 10 papas a 7 y 5 cebollas a 15"
- "para MARIA 2 zapallos a 12"

REGLAS:
- Los precios son exactamente los que se dicen (10000 = 10000, 7500 = 7500)
- "media" = 0.5, "un cuarto" = 0.25, "docena" = 12, "media docena" = 6
- Los nombres de productos normalizalos en singular y minúsculas (papas → papa, cebollas → cebolla)
- Los nombres de clientes en MAYÚSCULAS

Respondé SOLO con JSON válido, sin texto adicional.

Para COMPRA:
{
  "tipo": "compra",
  "items": [
    {"producto": "papa", "cantidad": 10, "precio": 5000}
  ]
}

Para VENTA:
{
  "tipo": "venta",
  "cliente": "JOSE",
  "items": [
    {"producto": "papa", "cantidad": 10, "precio": 7000},
    {"producto": "cebolla", "cantidad": 5, "precio": 15000}
  ]
}

Si no podés determinar el tipo:
{
  "tipo": "desconocido"
}"""


async def parse_message(text: str) -> dict:
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=512,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": text}],
    )
    raw = message.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        logger.error("JSON decode error for: %s", raw)
        return {"tipo": "desconocido"}
