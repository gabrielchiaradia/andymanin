import os
from datetime import date
from database import SessionLocal, get_all_productos, get_ventas_del_dia, get_saldo_caja_hoy, get_all_contactos, VentaItem
import whatsapp
from sqlalchemy import select
from sqlalchemy.orm import selectinload

EMOJIS = {
    "papa": "🥔", "cebolla": "🧅", "zanahoria": "🥕", "zapallo": "🎃",
    "brocoli": "🥦", "lechuga": "🥬", "rucula": "🌿", "puerro": "🌱",
    "acelga": "🌿", "tomate": "🍅", "ajo": "🧄", "choclo": "🌽",
}


def _fmt(valor: float) -> str:
    return f"${int(valor):,}".replace(",", ".")


async def send_reporte_diario(owner_number: str):
    async with SessionLocal() as session:
        productos = await get_all_productos(session)
        ventas = await get_ventas_del_dia(session)
        saldo_caja = await get_saldo_caja_hoy(session)

        # Cargar items de ventas con producto
        venta_ids = [v.id for v in ventas]
        items_result = await session.execute(
            select(VentaItem)
            .where(VentaItem.venta_id.in_(venta_ids))
            .options(selectinload(VentaItem.producto))
        )
        venta_items = list(items_result.scalars().all())

    # ── Mensaje de stock por WhatsApp ──
    hoy = date.today().strftime("%d/%m/%Y")
    lines = [f"📦 *Stock restante — {hoy}*\n"]

    for p in productos:
        if float(p.stock) > 0:
            lines.append(
                f"• {p.nombre.capitalize()}: *{float(p.stock):g}* uds  |  costo prom: {_fmt(float(p.precio_promedio))}"
            )

    if len(lines) == 1:
        lines.append("_Sin stock registrado_")

    lines.append(f"\n💰 *Caja del día: {_fmt(saldo_caja)}*")
    await whatsapp.send_text_message(owner_number, "\n".join(lines))

    # ── Ganancias por WhatsApp ──
    ganancia_lines = [f"📊 *Ganancias del día — {hoy}*\n"]
    ganancia_total = 0.0
    resumen: dict[str, dict] = {}

    for item in venta_items:
        nombre = item.producto.nombre.capitalize()
        cant = float(item.cantidad)
        ganancia = (float(item.precio_venta) - float(item.precio_costo)) * cant
        if nombre not in resumen:
            resumen[nombre] = {"cantidad": 0, "ganancia": 0}
        resumen[nombre]["cantidad"] += cant
        resumen[nombre]["ganancia"] += ganancia
        ganancia_total += ganancia

    if resumen:
        for nombre, data in sorted(resumen.items()):
            emoji = EMOJIS.get(nombre.lower(), "🥦")
            ganancia_lines.append(f"{emoji} *{nombre}*: {data['cantidad']:g} uds  →  {_fmt(data['ganancia'])}")
        ganancia_lines.append(f"\n💵 *Total: {_fmt(ganancia_total)}*")
    else:
        ganancia_lines.append("_Sin ventas registradas hoy_")

    await whatsapp.send_text_message(owner_number, "\n".join(ganancia_lines))


async def send_lista_clientes(owner_number: str):
    async with SessionLocal() as session:
        contactos = await get_all_contactos(session)
    if not contactos:
        await whatsapp.send_text_message(owner_number, "📋 No hay clientes registrados.")
        return
    lines = ["📋 *Clientes registrados*\n"]
    for c in contactos:
        lines.append(f"• *{c.nombre}* — {c.telefono}")
    await whatsapp.send_text_message(owner_number, "\n".join(lines))


def _generar_pdf_ganancias(items: list[VentaItem], fecha: str) -> str:
    ganancia_total = 0.0
    resumen: dict[str, dict] = {}

    for item in items:
        nombre = item.producto.nombre.capitalize()
        cant = float(item.cantidad)
        venta = float(item.precio_venta)
        costo = float(item.precio_costo)
        ganancia = (venta - costo) * cant

        if nombre not in resumen:
            resumen[nombre] = {"cantidad": 0, "ganancia": 0}
        resumen[nombre]["cantidad"] += cant
        resumen[nombre]["ganancia"] += ganancia
        ganancia_total += ganancia

    pdf = FPDF()
    pdf.add_page()
    pdf.set_margins(15, 15, 15)

    # Título
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, f"Reporte de Ganancias - {fecha}", ln=True, align="C")
    pdf.ln(6)

    # Encabezado tabla
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_fill_color(60, 120, 60)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(80, 9, "Producto", border=1, fill=True)
    pdf.cell(30, 9, "Cant.", border=1, fill=True, align="C")
    pdf.cell(50, 9, "Ganancia", border=1, fill=True, align="R")
    pdf.ln()

    # Filas
    pdf.set_font("Helvetica", "", 11)
    pdf.set_text_color(0, 0, 0)
    fill = False
    for nombre, data in sorted(resumen.items()):
        pdf.set_fill_color(235, 245, 235) if fill else pdf.set_fill_color(255, 255, 255)
        pdf.cell(80, 8, nombre, border=1, fill=True)
        pdf.cell(30, 8, f"{data['cantidad']:g}", border=1, fill=True, align="C")
        pdf.cell(50, 8, _fmt(data["ganancia"]), border=1, fill=True, align="R")
        pdf.ln()
        fill = not fill

    # Total
    pdf.ln(3)
    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(110, 10, "GANANCIA TOTAL DEL DÍA", border=0)
    pdf.cell(50, 10, _fmt(ganancia_total), border=0, align="R")

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    pdf.output(tmp.name)
    return tmp.name


async def send_saldo_caja(owner_number: str):
    async with SessionLocal() as session:
        saldo = await get_saldo_caja_hoy(session)
    await whatsapp.send_text_message(owner_number, f"💰 *Saldo de caja — {date.today().strftime('%d/%m/%Y')}*\n\n{_fmt(saldo)}")


async def send_stock_actual(owner_number: str):
    async with SessionLocal() as session:
        productos = await get_all_productos(session)
    hoy = date.today().strftime("%d/%m/%Y")
    lines = [f"📦 *Stock actual — {hoy}*\n"]
    for p in productos:
        if float(p.stock) > 0:
            lines.append(f"• {p.nombre.capitalize()}: *{float(p.stock):g}* uds  |  costo prom: {_fmt(float(p.precio_promedio))}")
    if len(lines) == 1:
        lines.append("_Sin stock registrado_")
    await whatsapp.send_text_message(owner_number, "\n".join(lines))
