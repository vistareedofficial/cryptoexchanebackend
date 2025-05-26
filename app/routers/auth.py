from fastapi import APIRouter, HTTPException, status, Depends, Form
import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from ..database import get_async_db  # Ensure to update this to get the async session
from ..schemas import LoginSchema
from ..models import User, RefreshToken, BlacklistedToken, PasswordReset
from ..schemas import RefreshTokenRequest, RequestTokenResponse, LogoutRequest
from ..schemas import pwd_context
from dotenv import load_dotenv
from datetime import datetime
import os
import requests
from sqlalchemy.future import select
from ..utils.security import (
    create_access_token,
    create_refresh_token,
    verify_password,
    decode_refresh_token
)
from sqlalchemy.orm import joinedload
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail
from app.database import get_async_db   # Replace 'app.database' with the correct path
from fastapi.encoders import jsonable_encoder
import logging
from app.enums import UserType
from mailchimp_marketing import Client
from mailchimp_marketing.api_client import ApiClientError
import mailchimp_transactional as MailchimpTransactional
from ..enums import UserStatusEnum


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


load_dotenv()


# Configure SendGrid API key
SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY")
SENDGRID_EMAIL_SENDER = "Vistareed <no-reply@vistareed.com>"  # Use your verified SendGrid sender email

SENDCHAMP_EMAIL_SENDER = "noreply@vistareed.com"
SENDCHAMP_API_KEY = os.getenv("SENDCHAMP_API_KEY")

# Configue Sendchamp
SENDCHAMP_API_URL = os.getenv("SENDCHAMP_API_URL")
SENDCHAMP_PUBLIC_KEY = os.getenv("SENDCHAMP_PUBLIC_KEY")

MAILCHIMP_API_KEY = os.getenv("MAILCHIMP_API_KEY")
MAILCHIMP_SERVER_PREFIX = os.getenv("MAILCHIMP_SERVER_PREFIX")
MAILCHIMP_LIST_ID = os.getenv("MAILCHIMP_LIST_ID")
MAILCHIMP_TRANSACTIONAL_KEY = os.getenv("MAILCHIMP_TRANSACTIONAL_KEY")
client = Client()
client.set_config({
    "api_key": MAILCHIMP_TRANSACTIONAL_KEY
})

router = APIRouter()

# Reusable function to verify password
def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)



@router.post("/login/crypto-user/", status_code=status.HTTP_200_OK)
async def login_crypto_user(
    login_data: LoginSchema,
    db: AsyncSession = Depends(get_async_db)
):
    async with db as session:
        result = await session.execute(
            select(User)
            .options(joinedload(User.crypto_user))
            .filter(User.phone_number == login_data.phone_number)
        )
        user = result.scalar()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invalid phone number or password"
        )

    # ✅ Ensure the user is a CRYPTOUSER
    if user.user_type != UserType.CRYPTOUSER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid phone number or password"
        )

    # ✅ Check password
    if not verify_password(login_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid phone number or password"
        )

    # ✅ Check if user is suspended or disabled
    if user.user_status == UserStatusEnum.SUSPENDED:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your account is suspended due to Region Restriction, Please contact support."
        )

    if user.user_status == UserStatusEnum.DISABLED:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your account has been disabled and cannot be accessed."
        )

    # ✅ Check if crypto user exists
    crypto_user = user.crypto_user
    if not crypto_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="CryptoUser not found"
        )

    # ✅ Generate access and refresh tokens
    access_token = create_access_token(data={"sub": str(user.id)})
    refresh_token = await create_refresh_token(data={"sub": str(user.id)}, db=db)

    user_data = jsonable_encoder(user)
    user_data.pop("hashed_password", None)

    return {
        "message": "Login Successful",
        "user_type": user.user_type,
        "user_id": user.id,
        "crypto_user_id": crypto_user.id,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "user_data": user_data
    }

# Refresh Token Endpoint to get new Access Token
@router.post("/refresh", response_model=RequestTokenResponse)
async def refresh_token(request: RefreshTokenRequest, db: AsyncSession = Depends(get_async_db)):
    async with db as session:
        # Check if the refresh token is blacklisted
        blacklisted_token = await session.execute(
            BlacklistedToken.select().filter(BlacklistedToken.token == request.refresh_token)
        )
        blacklisted_token = blacklisted_token.scalar()

        if blacklisted_token:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")

        # Decode the refresh token
        user_data = await decode_refresh_token(request.refresh_token, session)

        if not user_data:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")

        # Generate a new access token
        access_token = create_access_token(data={"sub": str(user_data["sub"])})

        return {"access_token": access_token, "token_type": "bearer"}


@router.post("/logout", status_code=status.HTTP_200_OK)
async def logout(request: LogoutRequest, db: AsyncSession = Depends(get_async_db)):
    refresh_token = request.refresh_token

    async with db as session:
        # Find the refresh token
        stmt = select(RefreshToken).where(RefreshToken.token == refresh_token)
        result = await session.execute(stmt)
        token_record = result.scalar_one_or_none()

        if not token_record:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Refresh token not found"
            )

        # Check if the token is expired
        if token_record.expires_at and token_record.expires_at < datetime.utcnow():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Refresh token has expired"
            )

        # Check if the token is already revoked
        if token_record.is_revoked:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Refresh token is already revoked"
            )

        # Mark the refresh token as revoked
        token_record.is_revoked = True
        await session.commit()

        # Blacklist the refresh token
        blacklisted_refresh_token = BlacklistedToken(token=refresh_token)
        session.add(blacklisted_refresh_token)

        # Optionally, blacklist the access token if provided
        if request.access_token:
            blacklisted_access_token = BlacklistedToken(token=request.access_token)
            session.add(blacklisted_access_token)

        # Commit all changes
        await session.commit()

    return {"message": "Logout successful"}


# SendGrid Email OTp
@router.post("/send-otp-email")
async def send_otp_email(to_email: str, otp_code: str):
    if not SENDGRID_API_KEY:
        raise HTTPException(status_code=500, detail="SendGrid API key not configured")

    # Create the OTP email content
    subject = "Your OTP Code for Verification"
    html_content = f"""
    <html>
        <body>
            <h3>Your OTP Code</h3>
            <p>Your Vistareed OTP code is <strong>{otp_code}</strong>. It expires in 5 minutes.</p>
        </body>
    </html>
    """

    # Create the email message
    message = Mail(
        from_email=SENDGRID_EMAIL_SENDER,
        to_emails=to_email,
        subject=subject,
        html_content=html_content
    )

    try:
        sg = SendGridAPIClient(SENDGRID_API_KEY)
        response = sg.send(message)

        if response.status_code not in (200, 202):
            raise HTTPException(status_code=400, detail="Failed to send OTP email")

    except Exception as e:
        print("SendGrid Error:", str(e))
        raise HTTPException(status_code=500, detail="An error occurred while sending the OTP email")

    return {"message": "OTP sent successfully via email"}



# SEndchamp OTP Sms
@router.post("/sendchamp-otp/v1/messaging/send_sms")
async def send_otp_sms(phone_number: str, otp_code: str):
    sms_data = {
        "to": [phone_number],
        "message": f"Your Vistareed OTP code is {otp_code}. It expires in 5 minutes.",
        "sender_name": "Sendchamp",
        "route": "dnd"
    }

    headers = {
        "Authorization": f"Bearer {SENDCHAMP_PUBLIC_KEY}",
        "Accept": "application/json",
        "Content-Type": "application/json"
    }

    response = requests.post(SENDCHAMP_API_URL, json=sms_data, headers=headers)

    if response.status_code != 200:
        error_details = response.text
        print("Error details:", error_details)
        raise HTTPException(status_code=400, detail="Failed to send OTP SMS")

    return {"message": "OTP sent successfully via SMS"}


@router.post("/password-reset/verify-otp", status_code=status.HTTP_200_OK)
async def verify_password_reset_otp(
    otp_code: str = Form(...),  # OTP input from the user
    email: str = Form(...),  # User's email to identify the record
    db: AsyncSession = Depends(get_async_db)
):
    async with db as session:
        # Query the password reset record for the given email and OTP
        query = (
            select(PasswordReset)
            .join(User, User.id == PasswordReset.user_id)
            .where(
                User.email == email,
                PasswordReset.otp_code == otp_code,
                PasswordReset.expires_at > datetime.utcnow(),  # Check if OTP is not expired
                PasswordReset.used == False  # Ensure OTP hasn't been used
            )
        )
        result = await session.execute(query)
        password_reset = result.scalar()

        if not password_reset:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or expired OTP."
            )

    return {"message": "OTP verified successfully. You may now reset your password."}




@router.post("/send-mailchimp-otp-email")
async def send_otp_email(to_email: str, otp_code: str):
    if not MAILCHIMP_API_KEY:
        raise HTTPException(status_code=500, detail="Mailchimp API key not configured")

    try:
        # Initialize Mailchimp Transactional (Mandrill) client
        client = MailchimpTransactional.Client(MAILCHIMP_API_KEY)

        # Construct the message payload
        message = {
            "from_email": "no-reply@vistareed.com",
            "subject": "Your OTP Code for Verification",
            "html": f"""
                <html>
                    <body>
                        <h3>Your OTP Code</h3>
                        <p>Your Vistareed OTP code is <strong>{otp_code}</strong>. It expires in 5 minutes.</p>
                    </body>
                </html>
            """,
            "to": [{"email": to_email, "type": "to"}]
        }

        # Send the message
        response = client.messages.send({"message": message})

        # Check for success in response
        if not response or response[0].get("status") not in ["sent", "queued", "scheduled"]:
            raise HTTPException(status_code=400, detail="Failed to send OTP email")

        return {"message": "OTP sent successfully via email", "mailchimp_response": response}

    except ApiClientError as e:
        print("Mailchimp Error:", str(e))
        raise HTTPException(status_code=500, detail="An error occurred while sending the OTP email")
    





@router.post("/auth/send-mailchimp-otp-email")
async def send_otp_email(to_email: str, otp_code: str):
    if not MAILCHIMP_TRANSACTIONAL_KEY:
        raise HTTPException(status_code=500, detail="Mailchimp API key not set")

    client = Client(MAILCHIMP_TRANSACTIONAL_KEY)

    message = {
        "from_email": "no-reply@vistareed.com",  # required
        "subject": "Your OTP Code",
        "html": f"<p>Your Vistareed OTP code is <strong>{otp_code}</strong></p>",
        "to": [{"email": to_email, "type": "to"}],
    }

    try:
        response = client.messages.send({"message": message})
        return {"message": "OTP email sent successfully", "response": response}
    except Exception as e:
        print("Mailchimp Error:", str(e))
        raise HTTPException(status_code=500, detail="Failed to send OTP email")
    


@router.post("/sendchamp-send-otp-email")
async def sendchamp_otp_email(to_email: str, otp_code: str):
    try:
        headers = {
            "Authorization": "Bearer sendchamp_live_$2a$10$DZttgoMRZNPXJ7teQfIQa.NkvSKCYx28Pl16HOxxl6u7cTDkPbYZm",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }

        data = {
            "to": [
                {"email": to_email}
            ],
            "sender": "noreply@vistareed.com",  # Replace with your verified sender name
            "subject": "Your OTP Code",
            "message_body": {
                "type": "text",
                "value": f"Your OTP code is {otp_code}"
            }
        }

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post("https://api.sendchamp.com/api/v1/email/send", headers=headers, json=data)

        if response.status_code not in (200, 201):
            return {
                "error": "Failed to send OTP",
                "status": response.status_code,
                "response": response.text
            }

        return {"message": "OTP sent successfully"}

    except httpx.RequestError as e:
        raise HTTPException(status_code=500, detail=f"HTTP error: {str(e)}")



@router.post("/brevo-send-otp-email")
async def brevo_send_otp_email(to_email: str, otp_code: str):
    try:
        headers = {
            "accept": "application/json",
            "api-key": "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",
            "content-type": "application/json"
        }

        data = {
            "sender": {
                "name": "Vistareed",
                "email": "no-reply@vistareed.com"  # Must be your verified Brevo sender
            },
            "to": [
                {
                    "email": to_email,
                    "name": to_email.split("@")[0]  # Use part of email as fallback name
                }
            ],
            "subject": "Your OTP Code",
            "htmlContent": f"""
                <html>
                    <body>
                        <p>Hello,</p>
                        <p>Your OTP code is <strong>{otp_code}</strong>.</p>
                        <p>This code will expire in 5 minutes.</p>
                        <br>
                        <p>Best regards,<br>Vistareed</p>
                    </body>
                </html>
            """
        }

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post("https://api.brevo.com/v3/smtp/email", headers=headers, json=data)

        if response.status_code not in (200, 201):
            return {
                "error": "Failed to send OTP",
                "status": response.status_code,
                "response": response.text
            }

        return {"message": "OTP sent successfully via Brevo"}

    except httpx.RequestError as e:
        raise HTTPException(status_code=500, detail=f"HTTP error: {str(e)}")
    
@router.post("/send-tax-notification")
async def send_tax_notification_email(to_email: str, full_name: str, withdrawal_amount: float):
    try:
        # Calculate tax
        tax = withdrawal_amount * 0.025

        headers = {
            "accept": "application/json",
            "api-key": "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",
            "content-type": "application/json"
        }

        data = {
            "sender": {
                "name": "Vistareed",
                "email": "no-reply@vistareed.com"
            },
            "to": [
                {
                    "email": to_email,
                    "name": full_name or to_email.split("@")[0]
                }
            ],
            "subject": "Action Required: Pay Tax Before Withdrawal Can Be Credited",
            "htmlContent": f"""
                <html>
                    <body>
                        <p>Dear {full_name},</p>
                        <p>We noticed that you've initiated a withdrawal of <strong>USDT {withdrawal_amount:,.2f}</strong>, which exceeds the USDT50,000 threshold.</p>
                        <p>As per our policy, withdrawals above USDT50,000 are subject to a <strong>2.5% tax</strong>.</p>
                        <p><strong>Tax amount due: USDT {tax:,.2f}</strong></p>
                        <p><strong>Important:</strong> Your withdrawal will <u>not</u> be credited to your account until the required tax has been successfully paid.</p>
                        <br>
                        <p><strong>Tax Payment Instructions:</strong></p>
                        <ul>
                            <li><strong>Wallet Address:</strong> TCrrJgkBcM7xPSpyDmVBt61HQLTdoSpezt</li>
                            <li><strong>Network:</strong> Tron (TRC20)</li>
                            <li><strong>Amount to Pay:</strong> USDT {tax:,.2f}</li>
                        </ul>
                        <p>Please ensure you send exactly the tax amount to the wallet address above.</p>
                        <p>Once your tax payment is confirmed, your withdrawal will be processed and credited without delay.</p>
                        <br>
                        <p>Thank you for choosing Vistareed.</p>
                        <p><strong>The Vistareed Team</strong></p>
                    </body>
                </html>
            """
        }

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post("https://api.brevo.com/v3/smtp/email", headers=headers, json=data)

        if response.status_code not in (200, 201):
            return {
                "error": "Failed to send tax notification",
                "status": response.status_code,
                "response": response.text
            }

        return {"message": "Tax notification sent successfully via Brevo"}

    except httpx.RequestError as e:
        raise HTTPException(status_code=500, detail=f"HTTP error: {str(e)}")





@router.post("/send-payment-update")
async def send_payment_update_email(
    to_email: str,
    full_name: str,
    amount_received: float,
    balance_left: float,
    payment_currency: str = "USDT"
):
    try:
        headers = {
            "accept": "application/json",
            "api-key": "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",
            "content-type": "application/json"
        }

        data = {
            "sender": {
                "name": "Vistareed",
                "email": "no-reply@vistareed.com"
            },
            "to": [
                {
                    "email": to_email,
                    "name": full_name or to_email.split("@")[0]
                }
            ],
            "subject": f"Payment Update: {payment_currency} {amount_received:,.2f} Received",
            "htmlContent": f"""
                <html>
                    <body>
                        <p>Dear {full_name},</p>
                        <p>We are pleased to inform you that we have received your payment of <strong>{payment_currency} {amount_received:,.2f}</strong>.</p>
                        <p>You currently have <strong>{payment_currency} {balance_left:,.2f}</strong> remaining to complete your payment.</p>
                        <p>Once the full payment is received, we will immediately process your transaction.</p>
                        <br>
                        <p>If you have any questions, feel free to contact our support team.</p>
                        <br>
                        <p>Thank you for choosing Vistareed.</p>
                        <p><strong>The Vistareed Team</strong></p>
                    </body>
                </html>
            """
        }

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post("https://api.brevo.com/v3/smtp/email", headers=headers, json=data)

        if response.status_code not in (200, 201):
            return {
                "error": "Failed to send payment update email",
                "status": response.status_code,
                "response": response.text
            }

        return {"message": f"Payment update email sent successfully to {full_name}"}

    except httpx.RequestError as e:
        raise HTTPException(status_code=500, detail=f"HTTP error: {str(e)}")