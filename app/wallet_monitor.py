# wallet_monitor_async.py

import asyncio
from tronpy import Tron
from sqlalchemy import select
from database import async_session  # Ensure this is from your async SQLAlchemy setup
from models import Wallet

client = Tron()

async def get_transactions_async(address: str):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, client.get_transactions, address, 5)

async def check_wallet_transactions():
    async with async_session() as session:
        result = await session.execute(select(Wallet))
        wallets = result.scalars().all()

        for wallet in wallets:
            address = wallet.address
            try:
                txs = await get_transactions_async(address)
                if txs:
                    print(f"[+] Incoming tx found for {address}:")
                    for tx in txs:
                        amount = tx['raw_data']['contract'][0]['parameter']['value'].get('amount', 0)
                        print(f"    Hash: {tx['txID']}, Amount: {amount}")
                    wallet.is_active = True
                    session.add(wallet)
                    await session.commit()
                else:
                    print(f"[-] No transactions yet for {address}")
            except Exception as e:
                print(f"[!] Error checking wallet {address}: {e}")

async def start_monitoring():
    print("🟢 Monitoring wallets for incoming TRX or tokens (async)...")
    while True:
        await check_wallet_transactions()
        await asyncio.sleep(60)

if __name__ == "__main__":
    asyncio.run(start_monitoring())
