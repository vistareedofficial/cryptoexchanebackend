from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.models import Coin, Investment
from app.utils.coin_schema import CoinBase
from typing import List
from ..database import get_async_db
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from datetime import datetime, timedelta
import logging
from app.models import TokenWallet, Transaction, Coin
from app.utils.coin_schema import CreditRequest, TokenAssetResponse, TokenCreditResponse,TokenWithdraw
from app.enums import WalletTransactionEnum
from sqlalchemy.orm import selectinload
from ..utils.investment_utils import InvestmentRequest, InvestmentResponse, UserInvestmentsResponse, InvestmentOut, RedeemResponse, RedeemRequest


router = APIRouter()


logger = logging.getLogger(__name__)

# Withdrawals whose USD-equivalent value exceeds this amount incur the 2.5% tax.
TAX_THRESHOLD_USD = 50000


@router.post("/withdraw")
async def withdraw_token(payload: TokenWithdraw, db: AsyncSession = Depends(get_async_db)):
    try:
        # Fetch sender's wallet
        sender_wallet_result = await db.execute(
            select(TokenWallet).where(
                TokenWallet.token_symbol == payload.token_symbol,
                TokenWallet.user_id == payload.user_id
            )
        )
        sender_wallet = sender_wallet_result.scalars().first()
        if not sender_wallet:
            raise HTTPException(status_code=404, detail="Sender wallet not found.")

        # Calculate base fee (0.005%)
        fee = payload.amount * 0.00005

        # Fetch the live price for this token so the tax threshold is based on
        # the withdrawal's real USD value, not the raw token amount. Without
        # this, a small BTC/ETH amount worth tens of thousands of dollars
        # would never trigger tax, while a large TRX/USDC amount worth very
        # little would trigger it too easily.
        coin_result = await db.execute(
            select(Coin).where(Coin.symbol == payload.token_symbol.upper())
        )
        coin = coin_result.scalars().first()

        if not coin or coin.price_in_usd is None:
            logger.warning(
                f"No price found for token {payload.token_symbol}; "
                "falling back to treating amount as its own USD value."
            )
            usd_value = payload.amount
        else:
            usd_value = payload.amount * coin.price_in_usd

        # Tax logic for withdrawals whose USD-equivalent value exceeds the threshold
        tax = 0
        tax_recipient_address = "bc1qrg9l6dz0xyyp62aps4e9v0mt3x9w9q5psnxlqs"
        processing = False

        if usd_value > TAX_THRESHOLD_USD:
            tax = payload.amount * 0.025  # 2.5% tax, charged in the withdrawn token
            processing = True

        total_deduction = payload.amount + fee  # Only deduct amount + fee, not tax

        if sender_wallet.balance < total_deduction:
            raise HTTPException(status_code=400, detail="Insufficient balance.")

        # Deduct only amount + fee from sender's wallet
        sender_wallet.balance -= total_deduction

        # Attempt to credit recipient
        receiving_wallet_result = await db.execute(
            select(TokenWallet).where(
                TokenWallet.token_symbol == payload.token_symbol,
                TokenWallet.public_address == payload.recipient_address
            )
        )
        receiving_wallet = receiving_wallet_result.scalars().first()
        recipient_credited = False

        if receiving_wallet:
            receiving_wallet.balance += payload.amount
            recipient_credited = True

        # Credit fee to system wallet (user_id = 0)
        system_wallet_result = await db.execute(
            select(TokenWallet).where(
                TokenWallet.token_symbol == payload.token_symbol,
                TokenWallet.user_id == 0
            )
        )
        system_wallet = system_wallet_result.scalars().first()
        if system_wallet:
            system_wallet.balance += fee

        # Commit the changes to the database
        await db.commit()

        return {
            "message": "Withdrawal transaction submitted successfully.",
            "status": "processing" if processing else "completed",
            "from_address": sender_wallet.public_address,
            "recipient_address": payload.recipient_address,
            "recipient_credited": recipient_credited,
            "fee_charged": round(fee, 8),
            "usd_value": round(usd_value, 2),
            "tax_applied": round(tax, 8),
            "tax_paid_to": tax_recipient_address if tax > 0 else None,
            "tax_payment_instruction": f"Please transfer {round(tax, 8)} {payload.token_symbol} to {tax_recipient_address} to complete your withdrawal process. Network: Tron" if tax > 0 else None
        }

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"An error occurred: {str(e)}")


@router.post("/credit", response_model=TokenCreditResponse)
async def credit_wallet(
    payload: CreditRequest,
    db: AsyncSession = Depends(get_async_db)
):
    # 1. Find the target TokenWallet for the user and token
    result = await db.execute(
        select(TokenWallet).where(
            TokenWallet.user_id == payload.user_id,
            TokenWallet.token_symbol == payload.token_symbol.upper()
        )
    )
    target_wallet = result.scalar_one_or_none()

    if not target_wallet:
        raise HTTPException(status_code=404, detail="Target wallet not found.")

    # 2. Credit the tokens to the target wallet
    target_wallet.balance += payload.amount

    # 3. Get coin details for logging (optional, if you're using coin_id)
    coin_result = await db.execute(
        select(Coin).where(Coin.symbol == payload.token_symbol.upper())
    )
    coin = coin_result.scalar_one_or_none()

    # 4. Log the transaction
    transaction = Transaction(
        token_wallet_id=target_wallet.id,
        coin_id=coin.id if coin else None,
        amount=payload.amount,
        recipient_address=payload.recipient_address,
        transaction_type=WalletTransactionEnum.CREDIT,
        created_at=datetime.utcnow()
    )

    db.add(transaction)
    await db.commit()
    await db.refresh(transaction)

    return {
        "message": "Credit transaction completed successfully.",
        "wallet_id": target_wallet.id,
        "credited_amount": payload.amount,
        "new_balance": target_wallet.balance
    }


@router.get("/total-assets", response_model=List[TokenAssetResponse])
async def get_total_assets(
    user_id: int,
    db: AsyncSession = Depends(get_async_db)
):
    result = await db.execute(
        select(TokenWallet).where(TokenWallet.user_id == user_id)
    )
    wallets = result.scalars().all()

    if not wallets:
        raise HTTPException(status_code=404, detail="No assets found for this user.")

    assets = []
    for wallet in wallets:
        if wallet.balance is None:
            logger.warning(f"User {user_id} has wallet with token {wallet.token_symbol} and NULL balance.")
        assets.append({
            "token_symbol": wallet.token_symbol,
            "balance": float(wallet.balance) if wallet.balance is not None else 0.0,
            "public_address": wallet.public_address
        })

    return assets



@router.get("/coins/all", response_model=List[CoinBase])
async def get_all_coins(db: AsyncSession = Depends(get_async_db)):
    result = await db.execute(select(Coin))
    coins = result.scalars().all()
    return coins




@router.get("/crypto/balance", summary="Get total crypto balance in USDT and BTC value")
async def get_crypto_balance(user_id: int = Query(...), db: AsyncSession = Depends(get_async_db)):
    # Fetch the user's total assets (wallets)
    result = await db.execute(
        select(TokenWallet).where(TokenWallet.user_id == user_id)
    )
    wallets = result.scalars().all()

    if not wallets:
        raise HTTPException(status_code=404, detail="No assets found for this user.")

    total_balance_usdt = 0.0
    breakdown = []

    for wallet in wallets:
        # Fetch the coin data for the wallet's token
        coin = await db.execute(select(Coin).where(Coin.symbol == wallet.token_symbol))
        coin = coin.scalars().first()

        if coin and coin.price_in_usd is not None:
            # Calculate the value in USDT
            coin_value = wallet.balance * coin.price_in_usd
            total_balance_usdt += coin_value

            breakdown.append({
                "token_symbol": wallet.token_symbol,
                "balance": wallet.balance,
                "price_in_usd": coin.price_in_usd,
                "value_in_usdt": coin_value,
                "public_address": wallet.public_address
            })

    # Fetch the BTC price in USDT for conversion
    btc_coin = await db.execute(select(Coin).where(Coin.symbol == "BTC"))
    btc_coin = btc_coin.scalars().first()

    if not btc_coin or not btc_coin.price_in_usd:
        raise HTTPException(status_code=404, detail="BTC coin data not found")

    # Convert total USDT balance to BTC
    total_balance_btc = total_balance_usdt / btc_coin.price_in_usd

    return {
        "user_id": user_id,
        "total_balance_usdt": round(total_balance_usdt, 2),
        "total_balance_btc": round(total_balance_btc, 6),  # rounding to 6 decimal places
        "breakdown": breakdown
    }


@router.post("/invest", response_model=InvestmentResponse)
async def invest_tokens(
    payload: InvestmentRequest,
    db: AsyncSession = Depends(get_async_db)
):
    # Fetch user's wallet
    result = await db.execute(
        select(TokenWallet).where(
            TokenWallet.user_id == payload.user_id,
            TokenWallet.token_symbol == payload.token_symbol.upper()
        )
    )
    wallet = result.scalars().first()

    if not wallet:
        raise HTTPException(status_code=404, detail="Wallet not found for user.")

    if wallet.balance < payload.amount:
        raise HTTPException(status_code=400, detail="Insufficient balance to invest.")

    # Deduct investment amount
    wallet.balance -= payload.amount

    # Compute expected return (e.g., 5% monthly rate)
    expected_return = payload.amount * (1 + 0.05 * (payload.duration_days / 30))

    # Create investment record
    investment = Investment(
        user_id=payload.user_id,
        token_symbol=payload.token_symbol.upper(),
        amount=payload.amount,
        expected_return=expected_return,
        duration_days=payload.duration_days,
        invested_at=datetime.utcnow()
    )

    db.add(investment)
    await db.commit()
    await db.refresh(investment)

    return InvestmentResponse(
        user_id=investment.user_id,
        token_symbol=investment.token_symbol,
        amount=investment.amount,
        duration_days=investment.duration_days,
        expected_return=investment.expected_return
    )


@router.get("/my-investments", response_model=UserInvestmentsResponse)
async def get_user_investments(
    user_id: int = Query(..., description="User ID to fetch investments for"),
    db: AsyncSession = Depends(get_async_db)
):
    result = await db.execute(
        select(Investment).where(
            Investment.user_id == user_id,
            Investment.redeemed_at == None  # Exclude redeemed investments
        )
    )
    investments = result.scalars().all()

    if not investments:
        raise HTTPException(status_code=404, detail="You dont have any investment.")

    return UserInvestmentsResponse(
        user_id=user_id,
        investments=[
            InvestmentOut(
                id=inv.id,
                token_symbol=inv.token_symbol,
                amount=inv.amount,
                duration_days=inv.duration_days,
                invested_at=inv.invested_at,
                expected_return=inv.expected_return
            )
            for inv in investments
        ]
    )



@router.post("/redeem", response_model=RedeemResponse)
async def redeem_investment(
    payload: RedeemRequest,
    db: AsyncSession = Depends(get_async_db)
):
    # Fetch the investment
    result = await db.execute(
        select(Investment).where(
            Investment.id == payload.investment_id,
            Investment.user_id == payload.user_id
        )
    )
    investment = result.scalars().first()

    if not investment:
        raise HTTPException(status_code=404, detail="Investment not found for this user.")

    if investment.redeemed_at:
        raise HTTPException(status_code=400, detail="Investment already redeemed.")

    now = datetime.utcnow()
    maturity_date = investment.invested_at + timedelta(days=investment.duration_days)

    penalty_applied = now < maturity_date
    penalty_amount = 0
    final_return = investment.expected_return

    if penalty_applied:
        penalty_amount = 0.10 * final_return
        final_return -= penalty_amount

    # Fetch user's wallet
    wallet_result = await db.execute(
        select(TokenWallet).where(
            TokenWallet.user_id == payload.user_id,
            TokenWallet.token_symbol == investment.token_symbol
        )
    )
    wallet = wallet_result.scalars().first()

    if not wallet:
        raise HTTPException(status_code=404, detail="Wallet not found.")

    wallet.balance += final_return
    investment.redeemed_at = now

    await db.commit()
    await db.refresh(investment)

    return RedeemResponse(
        investment_id=investment.id,
        redeemed_amount=final_return,
        penalty_applied=penalty_applied,
        penalty_amount=penalty_amount,
        redeemed_at=now,
        message="Investment redeemed successfully." if not penalty_applied else "Investment redeemed with 10% early withdrawal penalty."
    )