from datetime import datetime, timedelta
from app.database import get_async_db  # Update with your actual path
from app.models import OTPVerification  # Update with your actual path
from sqlalchemy import delete


async def delete_expired_otps():
    """
    Deletes expired OTPs from the database.
    """
    async for db in get_async_db():  # Ensure get_async_db() is an async generator
        try:
            expiration_threshold = datetime.utcnow() - timedelta(minutes=5)
            print(f"Deleting OTPs older than: {expiration_threshold}")
            
            # Execute deletion query
            result = await db.execute(
                delete(OTPVerification).where(OTPVerification.expires_at <= expiration_threshold)
            )
            await db.commit()
            
            deleted_count = result.rowcount if result else 0
            print(f"Deleted {deleted_count} expired OTP(s).")
        except Exception as e:
            print(f"Error deleting expired OTPs: {e}")