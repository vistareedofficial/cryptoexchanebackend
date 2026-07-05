# app/utils/coin_schema.py

from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from typing import List


class InvestmentRequest(BaseModel):
    user_id: int
    token_symbol: str
    amount: float
    duration_days: int


class InvestmentResponse(BaseModel):
    user_id: int
    token_symbol: str
    amount: float
    duration_days: int
    expected_return: float


class InvestmentOut(BaseModel):
    id: int                         # ← Add this
    token_symbol: str
    amount: float
    duration_days: int
    invested_at: datetime
    expected_return: float


class UserInvestmentsResponse(BaseModel):
    user_id: int
    investments: List[InvestmentOut]



class RedeemRequest(BaseModel):
    user_id: int
    investment_id: int


class RedeemResponse(BaseModel):
    investment_id: int
    redeemed_amount: float
    penalty_applied: bool
    penalty_amount: Optional[float] = 0
    redeemed_at: datetime
    message: str