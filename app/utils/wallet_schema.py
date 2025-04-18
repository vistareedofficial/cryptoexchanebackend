from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from pydantic import BaseModel, Field



# Response model to return wallet details
class WalletResponse(BaseModel):
    user_id: int
    balance: float
    account_number: str

    class Config:
        from_attributes = True


class TransactionCreate(BaseModel):
    amount: float
    transaction_type: str  # Should be either 'CREDIT' or 'DEBIT'

class TransactionResponse(BaseModel):
    amount: float
    transaction_type: str
    account_number: str  
    created_at: datetime

    class Config:
        from_attributes = True


# Response model for transaction details
class TransactionHistoryResponse(BaseModel):
    id: int
    amount: float
    transaction_type: str
    created_at: datetime

    class Config:
        from_attributes = True


class WithdrawalRequest(BaseModel):
    user_id: int = Field(..., description="ID of the user initiating the withdrawal")
    amount: float = Field(..., gt=0, description="Amount to withdraw")
    destination_account_number: str = Field(..., description="Destination account number")