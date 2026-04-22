import logging
from datetime import date
from database import (
    SessionLocal,
    Producto,
    Contacto,
    Compra,
    CompraItem,
    Venta,
    VentaItem,
    MovimientoCaja,
    get_producto_by_nombre,
    get_contacto_by_nombre,
    get_venta_pendiente,
    get_ultimo_entrada_mercado_hoy,
    normalizar,
)
import whatsapp

logger = logging.getLogger(__name__)

EMOJIS = {
    "papa": "🥔", "cebolla": "🧅", "zanahoria": "🥕", "zapallo": "🎃",
    "brocoli": "🥦", "lechuga": "🥬", "rucula": "🌿", "puerro": "🌱",
    "acelga": "🌿", "tomate": "🍅", "ajo": "🧄", "choclo": "🌽",
}

def _emoji(nombre: str) -> str:
    return EMOJIS.get(nombre.lower(), "🥦")

def _fmt(valor: float) -> str:
    return f"${int(valor):,}".replace(",", ".")


# ── Proceso 1: Compra ──────────────────────────────────────────────────────────

async def handle_compra(items: list[dict], owner_number: str):
    async with SessionLocal() as session:
        compra = Compra()
        session.add(compra)
        await session.flush()

        lines = [f"✅ *Compra registrada*\n"]
        for item in items:
            nombre = item["producto"].lower()
            cantidad = float(item["cantidad"])
            precio = float(item["precio"])

            producto = await get_producto_by_nombre(session, nombre)
            if producto is None:
                producto = Producto(nombre=nombre, stock=0, precio_promedio=0, costo_total=0)
                session.add(producto)
                await session.flush()

            stock_actual = float(producto.stock)
            costo_actual = float(producto.costo_total)

            nuevo_costo = costo_actual + cantidad * precio
            nuevo_stock = stock_actual + cantidad
            nuevo_precio_prom = nuevo_costo / nuevo_stock

            producto.stock = nuevo_stock
            producto.costo_total = nuevo_costo
            producto.precio_promedio = nuevo_precio_prom

            compra_item = CompraItem(
                compra_id=compra.id,
                producto_id=producto.id,
                cantidad=cantidad,
                precio_unitario=precio,
            )
            session.add(compra_item)
            lines.append(
                f"{_emoji(nombre)} {nombre.capitalize()}: {cantidad:g} uds  →  precio prom: {_fmt(nuevo_precio_prom)}"
            )

        await session.commit()

    await whatsapp.send_text_message(owner_number, "\n".join(lines))


# ── Proceso 2: Venta pendiente ─────────────────────────────────────────────────

async def handle_venta_pendiente(cliente_nombre: str, items: list[dict], owner_number: str):
    async with SessionLocal() as session:
        contacto = await get_contacto_by_nombre(session, cliente_nombre)
        if contacto is None:
            await whatsapp.send_text_message(
                owner_number,
                f"❌ Cliente *{cliente_nombre}* no encontrado.\nAgregalo con: AGREGAR {cliente_nombre} TELEFONO",
            )
            return

        # Verificar stock suficiente
        for item in items:
            producto = await get_producto_by_nombre(session, item["producto"])
            if producto is None or float(producto.stock) < float(item["cantidad"]):
                disponible = float(producto.stock) if producto else 0
                await whatsapp.send_text_message(
                    owner_number,
                    f"❌ Stock insuficiente de *{item['producto']}*.\nDisponible: {disponible:g} uds",
                )
                return

        # Crear venta en estado pendiente (sin tocar stock todavía)
        venta = Venta(contacto_id=contacto.id, estado="pendiente")
        session.add(venta)
        await session.flush()

        ticket_lines = [
            f"🧾 *Boleta — {contacto.nombre}*",
            f"📅 {date.today().strftime('%d/%m/%Y')}\n",
        ]
        total = 0.0

        for item in items:
            nombre = item["producto"].lower()
            cantidad = float(item["cantidad"])
            precio_venta = float(item["precio"])
            subtotal = cantidad * precio_venta
            total += subtotal

            producto = await get_producto_by_nombre(session, nombre)
            precio_costo = float(producto.precio_promedio)

            venta_item = VentaItem(
                venta_id=venta.id,
                producto_id=producto.id,
                cantidad=cantidad,
                precio_venta=precio_venta,
                precio_costo=precio_costo,
            )
            session.add(venta_item)
            ticket_lines.append(
                f"{_emoji(nombre)} {nombre.capitalize()}: x{cantidad:g}  {_fmt(precio_venta)} c/u  →  {_fmt(subtotal)}"
            )

        ticket_lines.append(f"\n💰 *Total: {_fmt(total)}*")
        ticket_text = "\n".join(ticket_lines)
        venta.mensaje_ticket = ticket_text

        await session.commit()
        venta_id = venta.id

    confirmacion = (
        f"📋 Se enviará este ticket a *{contacto.nombre}*:\n\n"
        f"{ticket_text}\n\n"
        f"¿Está ok? Respondé *SI* o *NO*"
    )
    await whatsapp.send_text_message(owner_number, confirmacion)


async def handle_confirmacion(owner_number: str, confirmar: bool = True):
    async with SessionLocal() as session:
        venta = await get_venta_pendiente(session)
        if venta is None:
            await whatsapp.send_text_message(owner_number, "❌ No hay ninguna venta pendiente de confirmación.")
            return

        if not confirmar:
            venta.estado = "cancelada"
            await session.commit()
            await whatsapp.send_text_message(owner_number, "❌ Venta cancelada.")
            return

        # Confirmar: descontar stock
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload
        result = await session.execute(
            select(Venta).where(Venta.id == venta.id).options(
                selectinload(Venta.items).selectinload(VentaItem.producto),
                selectinload(Venta.contacto),
            )
        )
        venta = result.scalar_one()

        for item in venta.items:
            item.producto.stock = float(item.producto.stock) - float(item.cantidad)
            nuevo_costo_total = float(item.producto.stock) * float(item.producto.precio_promedio)
            item.producto.costo_total = nuevo_costo_total

        venta.estado = "confirmada"
        ticket = venta.mensaje_ticket
        telefono = venta.contacto.telefono
        await session.commit()

    await whatsapp.send_text_message(owner_number, "✅ Venta confirmada. Enviando ticket al cliente...")
    await whatsapp.send_text_message(telefono, ticket)


# ── Caja ──────────────────────────────────────────────────────────────────────

async def handle_entrada_mercado(monto: float, owner_number: str):
    async with SessionLocal() as session:
        session.add(MovimientoCaja(tipo="entrada_mercado", monto=monto, descripcion=f"Salida al mercado con {_fmt(monto)}"))
        await session.commit()
    await whatsapp.send_text_message(owner_number, f"💼 Registrado: salís al mercado con *{_fmt(monto)}*")


async def handle_gasto_mercado(monto: float, owner_number: str):
    async with SessionLocal() as session:
        session.add(MovimientoCaja(tipo="gasto_mercado", monto=monto, descripcion=f"Gasto en mercado: {_fmt(monto)}"))
        await session.commit()
    await whatsapp.send_text_message(owner_number, f"🛒 Registrado: gastaste *{_fmt(monto)}* en el mercado")


async def handle_regreso_mercado(monto_regreso: float, owner_number: str):
    async with SessionLocal() as session:
        ultima = await get_ultimo_entrada_mercado_hoy(session)
        if ultima is None:
            await whatsapp.send_text_message(owner_number, "❌ No encontré ninguna salida al mercado registrada hoy.")
            return
        gastado = float(ultima.monto) - monto_regreso
        if gastado < 0:
            await whatsapp.send_text_message(owner_number, f"❌ El monto de regreso ({_fmt(monto_regreso)}) es mayor al que llevaste ({_fmt(float(ultima.monto))}).")
            return
        session.add(MovimientoCaja(tipo="gasto_mercado", monto=gastado, descripcion=f"Regresaste con {_fmt(monto_regreso)}, gastaste {_fmt(gastado)}"))
        await session.commit()
    await whatsapp.send_text_message(owner_number, f"🏠 Registrado: volviste con *{_fmt(monto_regreso)}*, gastaste *{_fmt(gastado)}* en el mercado")


async def handle_cobro_cliente(cliente: str, monto: float, owner_number: str):
    async with SessionLocal() as session:
        session.add(MovimientoCaja(tipo="cobro_cliente", monto=monto, descripcion=f"Cobro de {cliente}: {_fmt(monto)}"))
        await session.commit()
    await whatsapp.send_text_message(owner_number, f"💰 Registrado: *{cliente}* te pagó *{_fmt(monto)}*")


# ── Gestión de contactos ───────────────────────────────────────────────────────

async def handle_agregar_contacto(nombre: str, telefono: str, owner_number: str):
    async with SessionLocal() as session:
        existente = await get_contacto_by_nombre(session, nombre)
        if existente:
            existente.nombre = normalizar(nombre)
            existente.telefono = telefono
            existente.activo = True
            await session.commit()
            await whatsapp.send_text_message(owner_number, f"✅ Contacto *{normalizar(nombre)}* actualizado.")
        else:
            contacto = Contacto(nombre=normalizar(nombre), telefono=telefono)
            session.add(contacto)
            await session.commit()
            await whatsapp.send_text_message(owner_number, f"✅ Contacto *{nombre}* agregado.")


async def handle_eliminar_contacto(nombre: str, owner_number: str):
    async with SessionLocal() as session:
        contacto = await get_contacto_by_nombre(session, nombre)
        if contacto is None:
            await whatsapp.send_text_message(owner_number, f"❌ Contacto *{nombre}* no encontrado.")
            return
        contacto.activo = False
        await session.commit()
        await whatsapp.send_text_message(owner_number, f"✅ Contacto *{nombre}* eliminado.")
