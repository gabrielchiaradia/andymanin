from decimal import Decimal
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy import Text, DateTime, Numeric, ForeignKey, func, select

DB_PATH = "sqlite+aiosqlite:////data/db.sqlite"

engine = create_async_engine(DB_PATH, echo=False)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class Producto(Base):
    __tablename__ = "productos"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    nombre: Mapped[str] = mapped_column(Text, unique=True)
    stock: Mapped[float] = mapped_column(Numeric(10, 3), default=0)
    precio_promedio: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    costo_total: Mapped[float] = mapped_column(Numeric(14, 2), default=0)


class Contacto(Base):
    __tablename__ = "contactos"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    nombre: Mapped[str] = mapped_column(Text, unique=True)
    telefono: Mapped[str] = mapped_column(Text)
    activo: Mapped[bool] = mapped_column(default=True)


class Compra(Base):
    __tablename__ = "compras"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    fecha: Mapped[str] = mapped_column(DateTime, server_default=func.now())
    items: Mapped[list["CompraItem"]] = relationship(back_populates="compra")


class CompraItem(Base):
    __tablename__ = "compra_items"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    compra_id: Mapped[int] = mapped_column(ForeignKey("compras.id"))
    producto_id: Mapped[int] = mapped_column(ForeignKey("productos.id"))
    cantidad: Mapped[float] = mapped_column(Numeric(10, 3))
    precio_unitario: Mapped[float] = mapped_column(Numeric(12, 2))
    compra: Mapped["Compra"] = relationship(back_populates="items")


class Venta(Base):
    __tablename__ = "ventas"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    contacto_id: Mapped[int] = mapped_column(ForeignKey("contactos.id"))
    fecha: Mapped[str] = mapped_column(DateTime, server_default=func.now())
    # pendiente | confirmada | cancelada
    estado: Mapped[str] = mapped_column(Text, default="pendiente")
    mensaje_ticket: Mapped[str] = mapped_column(Text, nullable=True)
    items: Mapped[list["VentaItem"]] = relationship(back_populates="venta")
    contacto: Mapped["Contacto"] = relationship()


class VentaItem(Base):
    __tablename__ = "venta_items"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    venta_id: Mapped[int] = mapped_column(ForeignKey("ventas.id"))
    producto_id: Mapped[int] = mapped_column(ForeignKey("productos.id"))
    cantidad: Mapped[float] = mapped_column(Numeric(10, 3))
    precio_venta: Mapped[float] = mapped_column(Numeric(12, 2))
    precio_costo: Mapped[float] = mapped_column(Numeric(12, 2))
    venta: Mapped["Venta"] = relationship(back_populates="items")
    producto: Mapped["Producto"] = relationship()


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_producto_by_nombre(session, nombre: str) -> Producto | None:
    nombre_norm = nombre.strip().lower()
    result = await session.execute(
        select(Producto).where(func.lower(Producto.nombre) == nombre_norm)
    )
    return result.scalar_one_or_none()


async def get_contacto_by_nombre(session, nombre: str) -> Contacto | None:
    nombre_norm = nombre.strip().upper()
    result = await session.execute(
        select(Contacto).where(func.upper(Contacto.nombre) == nombre_norm)
    )
    return result.scalar_one_or_none()


async def get_venta_pendiente(session) -> Venta | None:
    result = await session.execute(
        select(Venta).where(Venta.estado == "pendiente").order_by(Venta.id.desc()).limit(1)
    )
    return result.scalar_one_or_none()


async def get_all_productos(session) -> list[Producto]:
    result = await session.execute(select(Producto).order_by(Producto.nombre))
    return list(result.scalars().all())


async def get_ventas_del_dia(session) -> list[Venta]:
    from sqlalchemy import cast, Date
    from datetime import date
    result = await session.execute(
        select(Venta)
        .where(Venta.estado == "confirmada")
        .where(cast(Venta.fecha, Date) == date.today())
    )
    return list(result.scalars().all())
