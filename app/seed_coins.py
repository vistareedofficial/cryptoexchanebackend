import asyncio
import requests
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.models import Coin  # ✅ Absolute import

# Updated coin data including fallback values for rate-limiting protection
coin_data = [
    {"symbol": "TRX", "name": "Tron", "fallback": 0.14},
    {"symbol": "USDC", "name": "USD Coin", "fallback": 1.00},
    {"symbol": "BTC", "name": "Bitcoin", "fallback": 68500.00},
    {"symbol": "ETH", "name": "Ethereum", "fallback": 3450.00},
    {"symbol": "USDT", "name": "Tether", "fallback": 1.00},
]

# Combined API request structure to prevent 429 rate limit blocks
def get_all_prices_from_coingecko():
    url = "https://coingecko.com"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"⚠️ CoinGecko blocked the shared Render IP (429). Deploying fallback prices. Error: {e}")
        return {}

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

        # Fetch all live information in one network request
        live_prices = get_all_prices_from_coingecko()
        new_coins = []

        for coin in coin_data:
            if coin["symbol"] not in existing_symbols:
                coingecko_id = symbol_to_id.get(coin["symbol"])
                
                # Fetch live data safely; use default values if API fails
                price = live_prices.get(coingecko_id, {}).get("usd", 0) if live_prices else 0
                
                if price <= 0:
                    price = coin["fallback"]
                    print(f"💡 Using fallback price for {coin['symbol']}: ${price}")

                new_coins.append(Coin(
                    symbol=coin["symbol"],
                    name=coin["name"],
                    price_in_usd=price
                ))

        if new_coins:
            db.add_all(new_coins)
            await db.commit()
            print(f"✅ Successfully seeded {len(new_coins)} coins into the database!")
        else:
            print("ℹ️ Coins already exist. No need to seed.")
    except Exception as e:
        await db.rollback()
        print(f"❌ Error seeding coins: {e}")

# Async runtime wrapper with strict lifecycle connection control
async def main():
    from app.database import async_session
    async with async_session() as session:
        await seed_coins(session)

if __name__ == "__main__":
    asyncio.run(main())
