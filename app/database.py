import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

# Fallback for local development
DEFAULT_LOCAL_DB = "postgresql+asyncpg://postgres:eternity@localhost/Delevia"

# Get the DATABASE_URL from environment variable or fallback to local
raw_database_url = os.getenv("DATABASE_URL", DEFAULT_LOCAL_DB)

# Convert standard Postgres URL to asyncpg-compatible for SQLAlchemy
if raw_database_url.startswith("postgresql://"):
    raw_database_url = raw_database_url.replace("postgresql://", "postgresql+asyncpg://", 1)

DATABASE_URL = raw_database_url

# Create the async SQLAlchemy engine
async_engine = create_async_engine(
    DATABASE_URL,
    echo=True,  # Turn off in production
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
