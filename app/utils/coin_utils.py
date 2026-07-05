import asyncio
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.models import  Coin, User
import httpx
from datetime import datetime
import uuid
from tronpy.keys import PrivateKey
from cryptography.fernet import Fernet
import os
from dotenv import load_dotenv
from .utils_dependencies_files import anext
# ------------------- DEPOSIT -------------------

load_dotenv()

FERNET_SECRET_KEY = os.getenv("FERNET_SECRET_KEY")
if not FERNET_SECRET_KEY:
    raise ValueError("FERNET_SECRET_KEY is not set in environment variables")

fernet = Fernet(FERNET_SECRET_KEY)

# ------------------- UPDATE COIN PRICES -------------------

async def fetch_price_from_coingecko(symbol: str):
    symbol_map = {
        "BTC": "bitcoin",
        "ETH": "ethereum",
        "USDT": "tether",
        "BNB": "binancecoin"
    }
    
    coin_id = symbol_map.get(symbol.upper())
    if not coin_id:
        return None

    url = f"https://api.coingecko.com/api/v3/simple/price?ids={coin_id}&vs_currencies=usd"
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()
            return data[coin_id]["usd"]
    except Exception as e:
        print(f"Error fetching {symbol} price: {e}")
        return None


async def update_coin_prices(db: AsyncSession):
    result = await db.execute(select(Coin))
    coins = result.scalars().all()

    for coin in coins:
        price = await fetch_price_from_coingecko(coin.symbol)
        if price is not None and price != coin.price_in_usd:
            coin.price_in_usd = price
            coin.updated_at = datetime.utcnow()
            db.add(coin)  # Important to mark it dirty

    await db.commit()
    print("✅ Coin prices updated!")


async def background_price_updater(get_db):
    while True:
        try:
            db_gen = get_db()
            db = await anext(db_gen)
            try:
                await update_coin_prices(db)
            finally:
                await db_gen.aclose()
        except Exception as e:
            print(f"Error in background updater: {e}")

        await asyncio.sleep(300)  # wait 5 minutes



async def create_crypto_wallet(user_id: int) -> str:
    # Simulate wallet creation — replace with actual blockchain logic
    return f"0x{uuid.uuid4().hex[:40]}"


def encrypt_private_key(private_key: str) -> str:
    return fernet.encrypt(private_key.encode()).decode()

def generate_tron_wallet():
    private_key = PrivateKey.random()
    public_key = private_key.public_key.hex()
    wallet_address = private_key.public_key.to_base58check_address()
    secret_key = private_key.hex()

    return {
        "wallet_address": wallet_address,
        "public_key": public_key,
        "secret_key": secret_key,
        "encrypted_private_key": encrypt_private_key(secret_key)
    }


def get_crypto_user_usdt_balance(user_id: int, db: AsyncSession):
    user = db.query(User).filter(User.id == user_id).first()
    if not user or not user.wallet:
        return {"balance_in_usdt": 0.0}

    total_balance = 0.0
    for coin_balance in user.wallet.coin_balances:
        coin = coin_balance.coin_data
        if coin:
            total_balance += coin_balance.balance * coin.price_in_usd
    
    return {"balance_in_usdt": round(total_balance, 2)}

