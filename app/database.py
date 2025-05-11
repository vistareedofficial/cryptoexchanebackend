import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base

# Default for local development
DEFAULT_LOCAL_DB = "postgresql+asyncpg://postgres:eternity@localhost/Delevia"

# Get the DATABASE_URL from environment variable or fallback to local
raw_database_url = os.getenv("DATABASE_URL", DEFAULT_LOCAL_DB)

# Convert Railway's default Postgres format to asyncpg-compatible
if raw_database_url.startswith("postgresql://"):
    raw_database_url = raw_database_url.replace("postgresql://", "postgresql+asyncpg://", 1)

DATABASE_URL = raw_database_url

# Create the async engine and session
async_engine = create_async_engine(DATABASE_URL, echo=True, future=True)
async_session = sessionmaker(bind=async_engine, class_=AsyncSession, expire_on_commit=False)

Base = declarative_base()

# Dependency to get DB session
async def get_async_db():
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()
