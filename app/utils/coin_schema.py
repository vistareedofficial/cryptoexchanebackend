# schemas.py
from datetime import datetime

from pydantic import BaseModel
from typing import List, Optional
from pydantic import BaseModel, Field
from typing import Literal

class CoinBase(BaseModel):
    id: int
    symbol: str
    name: str
    price_in_usd: float

    class Config:
        from_attributes = True


class WalletCoinBalanceBase(BaseModel):
    coin: CoinBase
    balance: float

    class Config:
        from_attributes = True


class WithdrawalRequest(BaseModel):
    user_id: int
    token_symbol: str
    amount: float
    recipient_address: str


class CreditRequest(BaseModel):
    user_id: int  # The ID of the user to whom the wallet belongs
    token_symbol: str  # The symbol of the token to be credited (e.g., BTC, ETH)
    amount: float  # The amount of tokens to credit
    recipient_address: str  # The address of the wallet where tokens are credited (can be the user's address)


class TokenAssetResponse(BaseModel):
    token_symbol: str
    balance: float
    public_address: str


class CoinAsset(BaseModel):
    balance: Optional[float]  # or balance: float | None in Python 3.10+
    coin_name: str


class TokenCreditResponse(BaseModel):
    wallet_id: int
    credited_amount: float
    new_balance: float

class WithdrawalResponseModel(BaseModel):
    message: str
    from_address: str
    recipient_address: str  # instead of 'to_address'

class TokenWithdraw(BaseModel):
    user_id: int
    token_symbol: str
    amount: float = Field(gt=0, description="Amount to withdraw, must be greater than 0")
    recipient_address: str



class UserInfo(BaseModel):
    id: int
    full_name: str
    email: str
    phone_number: str
    created_at: datetime

    model_config = {"from_attributes": True}


class CryptoUserProfile(BaseModel):
    id: int
    wallet_address: Optional[str] = None
    kyc_verified: bool
    referral_code: Optional[str] = None
    public_key: Optional[str] = None
    user: UserInfo  # Nested

    model_config = {"from_attributes": True}
