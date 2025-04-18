from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from models import Coin

# Example coin data
coin_data = [
    {"symbol": "BTC", "name": "Bitcoin", "price_in_usd": 70000},
    {"symbol": "ETH", "name": "Ethereum", "price_in_usd": 3000},
    {"symbol": "USDT", "name": "Tether", "price_in_usd": 1},
    {"symbol": "BNB", "name": "Binance Coin", "price_in_usd": 400},
    {"symbol": "SNY", "name": "SannyCoin", "price_in_usd": 0.5},
]

async def seed_coins(db: AsyncSession):
    existing = await db.execute(select(Coin))
    existing_symbols = {coin.symbol for coin in existing.scalars().all()}

    for coin in coin_data:
        if coin["symbol"] not in existing_symbols:
            db.add(Coin(**coin))
    
    await db.commit()
