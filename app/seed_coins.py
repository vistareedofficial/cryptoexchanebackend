from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.models import Coin  # ✅ Absolute import
import requests


# Updated coin data including TRX and USDC
coin_data = [
    {"symbol": "TRX", "name": "Tron"},
    {"symbol": "USDC", "name": "USD Coin"},
    {"symbol": "BTC", "name": "Bitcoin"},
    {"symbol": "ETH", "name": "Ethereum"},
    {"symbol": "USDT", "name": "Tether"},
]

# Function to get price from CoinGecko
def get_price_from_coingecko(symbol):
    url = f"https://api.coingecko.com/api/v3/simple/price?ids={symbol.lower()}&vs_currencies=usd"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        return data[symbol.lower()]["usd"]
    except requests.exceptions.RequestException as e:
        print(f"Error fetching price for {symbol}: {e}")
        return 0

# CoinGecko symbol mapping
symbol_to_id = {
    "TRX": "tron",
    "USDC": "usd-coin",
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "USDT": "tether"
}

# Seeder function
async def seed_coins(db: AsyncSession):
    try:
        result = await db.execute(select(Coin))
        existing_coins = result.scalars().all()
        existing_symbols = {coin.symbol for coin in existing_coins}

        new_coins = []
        for coin in coin_data:
            if coin["symbol"] not in existing_symbols:
                coingecko_id = symbol_to_id.get(coin["symbol"])
                if not coingecko_id:
                    print(f"⚠️ No Coingecko ID for {coin['symbol']}")
                    continue

                price = get_price_from_coingecko(coingecko_id)
                if price > 0:
                    new_coins.append(Coin(
                        symbol=coin["symbol"],
                        name=coin["name"],
                        price_in_usd=price
                    ))

        if new_coins:
            db.add_all(new_coins)
            await db.commit()
            print("✅ Coins seeded successfully with real-time prices.")
        else:
            print("ℹ️ Coins already exist. No need to seed.")
    except Exception as e:
        await db.rollback()
        print(f"❌ Error seeding coins: {e}")

# Script execution
if __name__ == "__main__":
    import asyncio
    from app.database import async_session  # Ensure your async session is correctly set up

    asyncio.run(seed_coins(async_session()))
