from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
import os

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://postgres:eternity@localhost/Delevia")

async_engine = create_async_engine(DATABASE_URL, echo=True, future=True)

async_session = sessionmaker(bind=async_engine, class_=AsyncSession, expire_on_commit=False)

Base = declarative_base()

async def get_async_db():
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()
