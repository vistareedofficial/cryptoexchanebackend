import requests
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from models import Wallet, Transaction, WalletCoinBalance, Coin
from enums import WalletTransactionEnum  # Assuming you defined this Enum

# ------------------- DEPOSIT -------------------

async def deposit_to_wallet(db: AsyncSession, wallet_id: int, coin_symbol: str, amount: float):
    result = await db.execute(select(Coin).where(Coin.symbol == coin_symbol))
    coin = result.scalars().first()
    if not coin:
        raise HTTPException(status_code=404, detail="Coin not found")

    result = await db.execute(select(Wallet).where(Wallet.id == wallet_id))
    wallet = result.scalars().first()
    if not wallet:
        raise HTTPException(status_code=404, detail="Wallet not found")

    result = await db.execute(
        select(WalletCoinBalance).where(
            WalletCoinBalance.wallet_id == wallet_id,
            WalletCoinBalance.coin_id == coin.id
        )
    )
    wallet_balance = result.scalars().first()

    if wallet_balance:
        wallet_balance.balance += amount
    else:
        wallet_balance = WalletCoinBalance(wallet_id=wallet_id, coin_id=coin.id, balance=amount)
        db.add(wallet_balance)

    transaction = Transaction(
        wallet_id=wallet_id,
        amount=amount,
        transaction_type=WalletTransactionEnum.DEPOSIT,
        coin_id=coin.id
    )
    db.add(transaction)
    await db.commit()
    await db.refresh(transaction)

    return {"message": "Deposit successful", "transaction_id": transaction.id}

# ------------------- WITHDRAW -------------------

async def withdraw_from_wallet(db: AsyncSession, wallet_id: int, coin_symbol: str, amount: float):
    result = await db.execute(select(Coin).where(Coin.symbol == coin_symbol))
    coin = result.scalars().first()
    if not coin:
        raise HTTPException(status_code=404, detail="Coin not found")

    result = await db.execute(select(Wallet).where(Wallet.id == wallet_id))
    wallet = result.scalars().first()
    if not wallet:
        raise HTTPException(status_code=404, detail="Wallet not found")

    result = await db.execute(
        select(WalletCoinBalance).where(
            WalletCoinBalance.wallet_id == wallet_id,
            WalletCoinBalance.coin_id == coin.id
        )
    )
    wallet_balance = result.scalars().first()

    if not wallet_balance or wallet_balance.balance < amount:
        raise HTTPException(status_code=400, detail="Insufficient balance")

    wallet_balance.balance -= amount

    transaction = Transaction(
        wallet_id=wallet_id,
        amount=amount,
        transaction_type=WalletTransactionEnum.WITHDRAWAL,
        coin_id=coin.id
    )
    db.add(transaction)
    await db.commit()
    await db.refresh(transaction)

    return {"message": "Withdrawal successful", "transaction_id": transaction.id}

# ------------------- UPDATE COIN PRICES -------------------

async def fetch_coin_prices(db: AsyncSession):
    url = "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,ethereum,tether,binancecoin,sannycoin&vs_currencies=usd"
    response = requests.get(url)

    if response.status_code != 200:
        raise HTTPException(status_code=500, detail="Failed to fetch coin prices")

    coin_prices = response.json()

    # Mapping from CoinGecko name to your system's symbol
    cg_to_symbol = {
        "bitcoin": "BTC",
        "ethereum": "ETH",
        "tether": "USDT",
        "binancecoin": "BNB",
        "sannycoin": "SNY"
    }

    for cg_name, symbol in cg_to_symbol.items():
        price = coin_prices.get(cg_name, {}).get("usd")
        if price is not None:
            result = await db.execute(select(Coin).where(Coin.symbol == symbol))
            coin = result.scalars().first()
            if coin:
                coin.price_in_usd = price
                db.add(coin)

    await db.commit()
