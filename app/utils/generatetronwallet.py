from tronpy import Tron
from tronpy.keys import PrivateKey
from ..models import TokenWallet, CryptoUser
from sqlalchemy.ext.asyncio import AsyncSession
from .coin_utils import generate_tron_wallet
from cryptography.fernet import Fernet
import os
from sqlalchemy.future import select


FERNET_SECRET_KEY = os.getenv("FERNET_SECRET_KEY")

FERNET_KEY = FERNET_SECRET_KEY
fernet = Fernet(FERNET_KEY)

async def create_crypto_wallets(user_id: int, crypto_user_id: int, db: AsyncSession):
    wallet_data = generate_tron_wallet()  # should return wallet_address, encrypted_private_key, public_key, and private_key

    tokens = [
        {"symbol": "TRX", "contract": None},
        {"symbol": "USDT", "contract": "TXLAQ63Xg1NAzckPwKHvzw7CSEmLMEqcdj"},
        {"symbol": "USDC", "contract": "TC4HnCuwfW4R8EjfP8d3ZMtweqdu8zmgxJ"},
        {"symbol": "BTC", "contract": "TBhEStRzX1UCpuo9Gj16ZLZ8it7k7N3cst"},
        {"symbol": "ETH", "contract": "T9yD14Nj9j7xAB4dbGeiX9h8unkKHxuWwb"},
    ]

    async with db as session:
        # Create token wallets
        for token in tokens:
            token_wallet = TokenWallet(
                user_id=user_id,
                crypto_user_id=crypto_user_id,
                token_symbol=token["symbol"],
                public_address=wallet_data["wallet_address"],
                private_key_encrypted=wallet_data["encrypted_private_key"],
                contract_address=token["contract"]
            )
            session.add(token_wallet)

        # Update CryptoUser with wallet address and keys
        result = await session.execute(
            select(CryptoUser).where(CryptoUser.id == crypto_user_id)
        )
        crypto_user = result.scalar_one_or_none()
        if crypto_user:
            crypto_user.wallet_address = wallet_data["wallet_address"]
            crypto_user.public_key = wallet_data["public_key"]
            crypto_user.secret_key = wallet_data["encrypted_private_key"]

        await session.commit()

    return wallet_data["wallet_address"]
