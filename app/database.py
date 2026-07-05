import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base

# Read from environment variables in production, fallback to local string for development
DATABASE_URL = os.getenv(
    "DATABASE_URL", 
    "postgresql+asyncpg://postgres:eternity@localhost/Cryptowallet"
)

# Create the async SQLAlchemy engine
async_engine = create_async_engine(
    DATABASE_URL,
    echo=False,  # Set to False to keep production logs clean
    future=True
)

# Create the async session factory
async_session = sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False
)

# SQLAlchemy base class
Base = declarative_base()

# Dependency for FastAPI routes
async def get_async_db():
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()
