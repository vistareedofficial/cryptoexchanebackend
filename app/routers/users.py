from fastapi import APIRouter, HTTPException, status, Depends, Form, UploadFile, File
from typing import Any, Optional, Union
from pathlib import Path
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import or_
from sqlalchemy import and_
from datetime import datetime
from ..database import get_async_db
from ..models import User, Rider,CryptoUser, Driver, KYC, Admin, Wallet, Referral, PasswordReset, TemporaryUserPhoto, PanicButton
from ..schemas import KycCreate, AdminCreate, get_password_hash, pwd_context
from ..utils.schemas_utils import RiderProfileUpdate, RiderProfile, PreRegisterRequest, DriverPreRegisterRequest, RiderProfileUpdateus, RiderProfileus
from ..utils.utils_dependencies_files import get_current_user, generate_hashed_referral_code
from ..utils.generatetronwallet import create_crypto_wallets
import logging
from sqlalchemy.orm import selectinload
import os
from fastapi.encoders import jsonable_encoder
from ..utils.otp import generate_otp, OTPVerification, generate_otp_expiration
import random
from sqlalchemy.future import select
from fastapi import HTTPException
from ..enums import UserType
from pydantic import BaseModel, Field, EmailStr, ValidationError
from app.utils.security import hash_password
from app.utils.coin_schema import  CryptoUserProfile, UserInfo
from sqlalchemy.orm import joinedload
import httpx
from ..enums import UserStatusEnum
from fastapi import HTTPException, Query

router = APIRouter()

# Define the path to the 'app/router' directory where the log file will be stored
log_directory = 'app/router'
# Check if the directory exists; if not, create it
if not os.path.exists(log_directory):
    os.makedirs(log_directory)

# Set up logging configuration to save the log file in the 'app/router' directory
logging.basicConfig(
    filename=os.path.join(log_directory, 'app.log'),  # Log file location
    level=logging.DEBUG,                              # Set log level to DEBUG for detailed output
    format='%(asctime)s - %(levelname)s - %(message)s'  # Log format
)

logger = logging.getLogger(__name__)


@router.post("/pre-register/crypto-user/new/", status_code=status.HTTP_200_OK)
async def pre_register_crypto_user(
    request: PreRegisterRequest,
    db: AsyncSession = Depends(get_async_db)
):
    full_name = request.full_name
    user_name = request.user_name
    phone_number = request.phone_number
    email = request.email
    password = request.password
    referral_code = request.referral_code

    async with db as session:
        user_query = await session.execute(
            select(User).filter(
                (User.phone_number == phone_number) |
                (User.email == email) |
                (User.user_name == user_name)
            )
        )
        existing_user = user_query.scalars().first()

        if existing_user:
            if existing_user.phone_number == phone_number:
                raise HTTPException(status_code=400, detail="Phone number is already in use.")
            elif existing_user.email == email:
                raise HTTPException(status_code=400, detail="Email is already in use.")
            elif existing_user.user_name == user_name:
                raise HTTPException(status_code=400, detail="Username is already taken.")

        otp_query = await session.execute(
            select(OTPVerification).filter(
                (OTPVerification.phone_number == phone_number) |
                (OTPVerification.email == email) |
                (OTPVerification.user_name == user_name)
            )
        )
        existing_otp = otp_query.scalars().first()
        if existing_otp:
            raise HTTPException(status_code=400, detail="OTP already sent. Check your email.")

        # Validate referral code
        referrer_crypto = None
        referrer_rider = None
        referrer_driver = None
        if referral_code:
            referrer_crypto = await session.scalar(
                select(CryptoUser).filter(CryptoUser.referral_code == referral_code)
            )
            if not referrer_crypto:
                referrer_rider = await session.scalar(
                    select(Rider).filter(Rider.referral_code == referral_code)
                )
            if not referrer_crypto and not referrer_rider:
                referrer_driver = await session.scalar(
                    select(Driver).filter(Driver.referral_code == referral_code)
                )
            if not any([referrer_crypto, referrer_rider, referrer_driver]):
                raise HTTPException(status_code=400, detail="Invalid referral code.")

        # Generate OTP
        otp_code = generate_otp()
        expiration_time = generate_otp_expiration()

        # Send OTP
        async with httpx.AsyncClient(base_url="http://localhost:8000") as client:
            email_response = await client.post(
                "/auth/brevo-send-otp-email",
                params={"to_email": email, "otp_code": otp_code}
            )
            if email_response.status_code != 200:
                raise HTTPException(status_code=500, detail="Failed to send OTP email.")

        # Save OTP data
        otp_entry = OTPVerification(
            full_name=full_name,
            user_name=user_name,
            phone_number=phone_number,
            email=email,
            otp_code=otp_code,
            expires_at=expiration_time,
            is_verified=False,
            hashed_password=hash_password(password),
            referral_code=referral_code
        )
        session.add(otp_entry)
        await session.commit()
        await session.refresh(otp_entry)

    return {
        "message": "Pre-registration successful. OTP sent via email.",
        "data": {
            "full_name": otp_entry.full_name,
            "user_name": otp_entry.user_name,
            "phone_number": otp_entry.phone_number,
            "email": otp_entry.email,
            "otp_code": otp_entry.otp_code,
            "expires_at": otp_entry.expires_at,
            "is_verified": otp_entry.is_verified,
            "referral_code": otp_entry.referral_code,
        }
    }


@router.post("/crypto-user-complete-registration/", status_code=status.HTTP_200_OK)
async def complete_crypto_registration(
    phone_number: str = Form(...),
    otp_code: str = Form(...),
    referral_code: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_async_db)
):
    async with db as session:
        otp_query = await session.execute(
            select(OTPVerification).filter(
                OTPVerification.phone_number == phone_number,
                OTPVerification.otp_code == otp_code,
                OTPVerification.expires_at > datetime.utcnow(),
                OTPVerification.is_verified == False
            )
        )
        otp_entry = otp_query.scalar()

        if not otp_entry:
            raise HTTPException(status_code=400, detail="Invalid or expired OTP.")

        otp_entry.is_verified = True
        await session.commit()

        account_number = f"{random.randint(1000000000, 9999999999)}"

        user = User(
            full_name=otp_entry.full_name,
            user_name=otp_entry.user_name,
            phone_number=otp_entry.phone_number,
            email=otp_entry.email,
            hashed_password=otp_entry.hashed_password,
            user_type=UserType.CRYPTOUSER,
            created_at=datetime.utcnow()
        )
        session.add(user)
        await session.flush()

        crypto_user = CryptoUser(user_id=user.id)
        session.add(crypto_user)
        await session.flush()

        wallet = Wallet(
            user_id=user.id,
            balance=0.0,
            account_number=account_number
        )
        session.add(wallet)

        if referral_code:
            referrer_crypto = await session.scalar(
                select(CryptoUser).filter(CryptoUser.referral_code == referral_code)
            )
            referrer_rider = None
            referrer_driver = None

            if not referrer_crypto:
                referrer_rider = await session.scalar(
                    select(Rider).filter(Rider.referral_code == referral_code)
                )
            if not referrer_crypto and not referrer_rider:
                referrer_driver = await session.scalar(
                    select(Driver).filter(Driver.referral_code == referral_code)
                )
            if not any([referrer_crypto, referrer_rider, referrer_driver]):
                raise HTTPException(status_code=400, detail="Invalid referral code.")

            referral = Referral(
                referrer_crypto_user_id=referrer_crypto.id if referrer_crypto else None,
                referrer_rider_id=referrer_rider.id if referrer_rider else None,
                referrer_driver_id=referrer_driver.id if referrer_driver else None,
                referred_crypto_user_id=crypto_user.id
            )
            session.add(referral)

        await session.commit()

        crypto_wallet_address = await create_crypto_wallets(user.id, crypto_user.id, db)
        crypto_user.wallet_address = crypto_wallet_address
        session.add(crypto_user)  # Ensure it's marked as dirty if needed
        await session.commit()
        await session.refresh(crypto_user)  # Optional: refresh to get latest values


        user_data = jsonable_encoder(user)
        user_data.pop("hashed_password", None)

        return {
            "message": "Registration completed successfully",
            "user_type": user.user_type,
            "crypto_user_id": crypto_user.id,
            "user_data": {
                "id": user.id,
                "full_name": user.full_name,
                "user_name": user.user_name,
                "phone_number": user.phone_number,
                "email": user.email,
                "user_type": user.user_type,
                "user_status": user.user_status,
                "address": user.address,
                "created_at": user.created_at,
                "gender": user.gender,
                "crypto_user": {
                    "id": crypto_user.id,
                    "user_id": crypto_user.user_id,
                    "wallet_address": crypto_user.wallet_address,
                    "referral_code": crypto_user.referral_code,
                    "kyc_verified": crypto_user.kyc_verified
                }
            }
        }


@router.get("/crypto-user/profile", response_model=CryptoUserProfile)
async def get_crypto_user_profile(user_id: int, db: AsyncSession = Depends(get_async_db)):
    # Fetch the CryptoUser with UserInfo (nested relationship)
    result = await db.execute(
        select(CryptoUser)
        .options(selectinload(CryptoUser.user))  # Eagerly load the related user
        .where(CryptoUser.user_id == user_id)
    )
    crypto_user = result.scalars().first()

    if not crypto_user:
        raise HTTPException(status_code=404, detail="Crypto user not found")

    # Build the CryptoUserProfile response with nested user info
    crypto_user_profile = CryptoUserProfile(
        id=crypto_user.id,
        wallet_address=crypto_user.wallet_address,
        kyc_verified=crypto_user.kyc_verified,
        referral_code=crypto_user.referral_code,
        public_key=crypto_user.public_key,
        user=UserInfo(
            id=crypto_user.user.id,
            full_name=crypto_user.user.full_name,
            email=crypto_user.user.email,
            phone_number=crypto_user.user.phone_number,
            created_at=crypto_user.user.created_at
        )
    )
    
    return crypto_user_profile

# Create Admin Endpoint
@router.post("/admin/", status_code=status.HTTP_201_CREATED)
async def create_admin(admin: AdminCreate, db: AsyncSession = Depends(get_async_db)) -> Any:
    query = select(User).filter(User.id == admin.user_id)
    user = (await db.execute(query)).scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    new_admin = Admin(
        user_id=admin.user_id,
        department=admin.department,
        access_level=admin.access_level
    )
    db.add(new_admin)
    await db.commit()
    await db.refresh(new_admin)

    return {"message": "Admin record created successfully", "admin_id": new_admin.id}


# Rider Referal Code Endpoint
@router.get("/rider/referral-code/{rider_id}", status_code=status.HTTP_200_OK)
async def get_referral_code(rider_id: int, db: AsyncSession = Depends(get_async_db)):
    # Ensure the rider exists in the database
    result = await db.execute(select(Rider).filter(Rider.id == rider_id))
    rider = result.scalars().first()

    if not rider:
        raise HTTPException(status_code=404, detail="Rider not found")

    # Check if the rider already has a referral code
    if rider.referral_code:
        return {
            "referral_code": rider.referral_code
        }

    # Generate a new referral code
    referral_code = generate_hashed_referral_code()

    # Set the new referral code
    rider.referral_code = referral_code

    # Commit the changes to the database
    try:
        db.add(rider)  # Mark the rider instance for update
        await db.commit()  # Commit the transaction
        await db.refresh(rider)  # Refresh the rider instance
    except Exception as e:
        await db.rollback()  # Rollback in case of error
        raise HTTPException(status_code=500, detail=f"An error occurred while saving the referral code: {e}")

    return {
        "referral_code": rider.referral_code
    }


@router.post("/password-reset/request", status_code=status.HTTP_200_OK)
async def request_password_reset(
    email: str = Form(...),
    db: AsyncSession = Depends(get_async_db)
):
    async with db as session:
        # Check if the user exists
        user_query = await session.execute(select(User).where(User.email == email))
        user = user_query.scalar()

        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

        # Check if there's already a valid, unused, and unexpired OTP
        existing_otp_query = await session.execute(
            select(PasswordReset).where(
                and_(
                    PasswordReset.user_id == user.id,
                    PasswordReset.used == False,
                    PasswordReset.expires_at > datetime.utcnow()
                )
            )
        )
        existing_otp = existing_otp_query.scalar()

        if existing_otp:
            return {
                "message": "An OTP has already been sent. Please check your email."
            }

        # Generate new OTP
        otp_code = generate_otp()
        expiration_time = generate_otp_expiration()

        # Save OTP to database
        password_reset = PasswordReset(
            user_id=user.id,
            otp_code=otp_code,
            expires_at=expiration_time,
            used=False
        )
        session.add(password_reset)
        await session.commit()

        # Send OTP email
        async with httpx.AsyncClient(base_url="http://localhost:8000") as client:
            params = {
                "to_email": email,
                "otp_code": otp_code
            }
            email_response = await client.post("/auth/brevo-send-otp-email", params=params)
            if email_response.status_code != 200:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Failed to send OTP email."
                )

    return {"message": "Password reset OTP sent. Please check your email."}


@router.post("/users/password-reset/reset", status_code=status.HTTP_200_OK)
async def reset_password(
    otp_code: str = Form(...),
    new_password: str = Form(...),
    email: str = Form(...),
    db: AsyncSession = Depends(get_async_db)
):
    async with db as session:
        now = datetime.utcnow()
        print(f"Current UTC time: {now}")

        # Query for the password reset record
        query = (
            select(PasswordReset)
            .join(User, User.id == PasswordReset.user_id)
            .where(
                User.email == email,
                PasswordReset.otp_code == otp_code,
                PasswordReset.expires_at > now,  # Ensure OTP is not expired
                PasswordReset.used == False  # Ensure OTP has not been used
            )
        )

        result = await session.execute(query)
        password_reset = result.scalar()

        if not password_reset:
            print("Password reset record query returned no results.")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or expired OTP."
            )

        # Debugging information
        print(f"Password reset record found for email: {email}")
        print(f"Requested OTP code: {otp_code}")
        print(f"Database OTP code: {password_reset.otp_code}")
        print(f"Expires at: {password_reset.expires_at} (UTC)")
        print(f"Used status: {password_reset.used}")

        # Mark OTP as used
        password_reset.used = True
        session.add(password_reset)

        # Query for the user associated with the email
        user_query = await session.execute(select(User).where(User.email == email))
        user = user_query.scalar()

        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found."
            )

        # Hash the new password and update the user's password
        hashed_password = pwd_context.hash(new_password)
        user.hashed_password = hashed_password
        session.add(user)

        # Commit the changes to the database
        await session.commit()

    return {"message": "Password reset successfully."}



# Function to save image and return the file path
async def save_image(file: UploadFile, folder_path: str) -> str:
    # Convert folder_path to Path object
    folder = Path(folder_path)
    
    # Create the folder if it doesn't exist
    if not folder.exists():
        folder.mkdir(parents=True, exist_ok=True)
    
    # Create a unique filename for the uploaded image
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    file_name = f"{timestamp}_{file.filename}"
    
    # Define the full path to save the image
    file_path = folder / file_name
    
    # Save the file
    with open(file_path, "wb") as buffer:
        content = await file.read()  # Read the content of the file
        buffer.write(content)  # Write the content to the file
    
    # Return the path where the file was saved
    return str(file_path)


@router.post("/users/temp-photo/")
async def upload_temp_driver_photo(
    driver_id: int = None,
    rider_id: int = None,  # Optional for cases when it’s a driver photo
    file: UploadFile = File(...), 
    db: AsyncSession = Depends(get_async_db)
):
    # Validate that the file is an image
    if not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Invalid file type. Please upload an image.")

    try:
        # Determine if the uploaded photo is for a driver or a rider
        if driver_id:
            folder_path = './assets/temporal_photos/driver_photos'
        elif rider_id:
            folder_path = './assets/temporal_photos/riders/rider_photos'
        else:
            raise HTTPException(status_code=400, detail="Either driver_id or rider_id must be provided.")
        
        # Save the image
        photo_path = await save_image(file, folder_path)
        
        # Create a temporary record
        temp_photo = TemporaryUserPhoto(
            driver_id=driver_id,
            rider_id=rider_id,
            photo_path=photo_path
        )
        
        db.add(temp_photo)
        await db.flush()  # Ensure data is sent to the DB
        await db.commit()  # Commit the transaction

        return {"message": "Temporary photo uploaded successfully.", "photo_path": photo_path}
    
    except Exception as e:
        await db.rollback()  # Rollback the transaction in case of error
        raise HTTPException(status_code=500, detail=f"An error occurred: {str(e)}")
    


@router.patch("/user/{user_id}/suspend", status_code=status.HTTP_200_OK)
async def suspend_user(user_id: int, db: AsyncSession = Depends(get_async_db)):
    result = await db.execute(select(User).filter(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.user_status = UserStatusEnum.SUSPENDED
    await db.commit()
    return {"message": f"User {user_id} suspended successfully"}


@router.patch("/user/{user_id}/disable", status_code=status.HTTP_200_OK)
async def disable_user(user_id: int, db: AsyncSession = Depends(get_async_db)):
    result = await db.execute(select(User).filter(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.user_status = UserStatusEnum.DISABLED
    await db.commit()
    return {"message": f"User {user_id} disabled (banned) successfully"}


@router.patch("/user/{user_id}/disable", status_code=status.HTTP_200_OK)
async def disable_user(user_id: int, db: AsyncSession = Depends(get_async_db)):
    result = await db.execute(select(User).filter(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.user_status = UserStatusEnum.DISABLED
    await db.commit()
    return {"message": f"User {user_id} disabled (banned) successfully"}


@router.patch("/user/{user_id}/reactivate", status_code=status.HTTP_200_OK)
async def reactivate_user(user_id: int, db: AsyncSession = Depends(get_async_db)):
    result = await db.execute(select(User).filter(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.user_status = UserStatusEnum.APPROVED
    await db.commit()
    return {"message": f"User {user_id} reactivated successfully"}



# If router is not defined in this file, ensure it uses your existing APIRouter instance
@router.get("/dev/registered-users/", status_code=status.HTTP_200_OK)
async def get_user_registration_data(
    email: Optional[str] = None,
    phone_number: Optional[str] = None,
    db: AsyncSession = Depends(get_async_db)
):
    """
    Developer utility endpoint to fetch user registration profiles.
    Allows filtering by email or phone_number. If no filters are passed, it returns all records.
    """
    async with db as session:
        # 1. Start the base query selecting the User model
        query = select(User)
        
        # 2. Apply filters dynamically if provided in the URL query string
        if email:
            query = query.filter(User.email == email)
        if phone_number:
            query = query.filter(User.phone_number == phone_number)
            
        result = await session.execute(query)
        users = result.scalars().all()
        
        if not users:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, 
                detail="No registered user profiles found matching those parameters."
            )
            
        # 3. Format the response payload safely (excluding security sensitive fields like hashed_password)
        response_data = []
        for user in users:
            response_data.append({
                "id": user.id,
                "full_name": user.full_name,
                "user_name": user.user_name,
                "phone_number": user.phone_number,
                "email": user.email,
                "user_type": user.user_type,
                "created_at": user.created_at
            })
            
        return {
            "total_records": len(response_data),
            "users": response_data
        }