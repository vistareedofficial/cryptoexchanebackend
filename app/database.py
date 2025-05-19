import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Fallback for local development
DEFAULT_LOCAL_DB = "postgresql+asyncpg://postgres:eternity@localhost/Delevia"

# Fallback for AWS RDS (as psycopg2 is sync, we must convert to asyncpg)
DEFAULT_RDS_DB = "postgresql+psycopg2://postgres:2_Eternitydorcas@database-1.ca9i4ieoek17.us-east-1.rds.amazonaws.com:5432/Cryptobackend"

# Get the DATABASE_URL from environment variable or fallback
raw_database_url = os.getenv("DATABASE_URL", DEFAULT_RDS_DB or DEFAULT_LOCAL_DB)

# Ensure the driver is asyncpg (convert if needed)
if raw_database_url.startswith("postgresql://"):
    raw_database_url = raw_database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
elif raw_database_url.startswith("postgresql+psycopg2://"):
    raw_database_url = raw_database_url.replace("postgresql+psycopg2://", "postgresql+asyncpg://", 1)

DATABASE_URL = raw_database_url

# Create the async SQLAlchemy engine
async_engine = create_async_engine(
    DATABASE_URL,
    echo=True,  # Set to False in production
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
