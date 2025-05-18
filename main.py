from fastapi import FastAPI, WebSocket, WebSocketDisconnect, APIRouter, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi_utils.tasks import repeat_every
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import delete
import json
import asyncio
from app.database import async_session  # wherever your session is
from app.seed_coins import seed_coins
from contextlib import asynccontextmanager
from sqlalchemy.orm import sessionmaker
from datetime import datetime
from app.utils.coin_utils import background_price_updater
from app.enums import RideStatusEnum
import logging
from app.routers import auth, users, rides, wallet, chatMessage, pushNotifications,coordinates, coins
from app.database import Base, async_engine, get_async_db
from app.models import Ride, ChatMessage, CallLog, OTPVerification
from app.utils.connection_manager import ConnectionManager, CallConnectionManager, driver_connection_manager
from app.routers.coordinates import update_driver_coordinates
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from app.utils.otp_delete_test import delete_expired_otps
from app.routers.coordinates import update_driver_coordinates
from app.models import Driver
from app.utils.rides_utility_functions import get_rides_within_radius
from sqlalchemy.sql.expression import update

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
# app = FastAPI()


# Logging configuration
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("app.log"),
        logging.StreamHandler()
    ]
)



# WebSocket Connection Manager
manager = ConnectionManager()
call_manager = CallConnectionManager()

# Dictionary to track active driver connections
active_drivers = {}

# Set up the scheduler
scheduler = AsyncIOScheduler()


# Create session factory
AsyncSessionLocal = sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False
)


async def delete_expired_otps():
    """
    Deletes all expired OTPs from the database.
    """
    async with AsyncSessionLocal() as session:
        try:
            logger.info("🔍 Checking for expired OTPs...")

            # Get current timestamp
            now = datetime.utcnow()

            # Select all expired OTPs
            stmt = select(OTPVerification).where(OTPVerification.expires_at < now)
            result = await session.execute(stmt)
            expired_otps = result.scalars().all()

            if expired_otps:
                # Delete expired OTPs
                for otp in expired_otps:
                    await session.delete(otp)

                await session.commit()
                logger.info(f"✅ Deleted {len(expired_otps)} expired OTP(s).")
            else:
                logger.info("✅ No expired OTPs found.")

        except Exception as e:
            logger.error(f"❌ Error deleting expired OTPs: {e}")
            await session.rollback()  # Rollback in case of error

# The lifespan context manager
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Startup and shutdown event handler for FastAPI.
    """
    logger.info("🚀 Starting FastAPI application...")

    try:
        # Starting OTP cleanup scheduler
        logger.info("🔄 Starting scheduler for OTP cleanup...")

        # Schedule the OTP cleanup task to run every 2 minutes
        scheduler.add_job(
            delete_expired_otps,  # Function to run
            trigger=IntervalTrigger(minutes=2),  # Every 2 minutes
            id="otp_cleanup",  # Job id
            name="Delete expired OTPs",  # Job name
            replace_existing=True  # Replace the job if it already exists
        )

        # Start the scheduler
        scheduler.start()
        logger.info("✅ OTP cleanup task scheduled and scheduler started.")
        
        # Starting background price updater task
        logger.info("🔄 Starting background price updater...")
        task = asyncio.create_task(background_price_updater(get_async_db))

        logger.info("✅ Background price updater task started.")
    
    except Exception as e:
        logger.error(f"❌ Error starting background tasks: {e}")

    yield  # App runs while this is active

    # Shutdown logic
    try:
        # Stopping OTP cleanup scheduler
        logger.info("🛑 Shutting down OTP cleanup scheduler...")
        if scheduler.running:
            scheduler.shutdown()
            logger.info("✅ OTP cleanup scheduler stopped successfully.")
        else:
            logger.warning("⚠️ OTP cleanup scheduler was not running.")

        # Cancelling background price updater task
        logger.info("🛑 Cancelling background price updater task...")
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        logger.info("✅ Background price updater task stopped.")

    except Exception as e:
        logger.error(f"❌ Error during shutdown: {e}")

    logger.info("🚀 FastAPI application shutdown complete.")


# Create FastAPI app with lifespan context
app = FastAPI(lifespan=lifespan)
# Optional root endpoint to test the app
@app.get("/")
async def read_root():
    return {"message": "OTP Cleanup Service is running!"}


# WebSocket endpoint for chat within rides
@app.websocket("/ws/chat/{ride_id}/{user_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    ride_id: int,
    user_id: int,
    db: AsyncSession = Depends(get_async_db)
):
    """
    WebSocket endpoint for chat within a ride.
    """
    # Check if the ride exists
    result = await db.execute(select(Ride).filter_by(id=ride_id))
    ride = result.scalar()

    if not ride:
        await websocket.close(code=1008)
        raise HTTPException(status_code=404, detail="Ride not found")

    # Check if the user is authorized for the ride
    if ride.rider_id != user_id and ride.driver_id != user_id:
        await websocket.close(code=1008)
        raise HTTPException(status_code=403, detail="User not authorized for this ride")

    # Connect the user to the WebSocket manager
    await manager.connect(user_id, websocket)

    try:
        while True:
            data = await websocket.receive_text()
            # Parse recipient_id and message (format: recipient_id:message)
            try:
                recipient_id, message = data.split(":", 1)
                recipient_id = int(recipient_id)
            except ValueError:
                await websocket.send_text("Invalid message format. Expected 'recipient_id:message'.")
                continue

            # Log and save the message
            chat_message = ChatMessage(
                sender_id=user_id,
                receiver_id=recipient_id,
                message=message,
                ride_id=ride_id
            )
            db.add(chat_message)
            await db.commit()

            # Send the message to the recipient
            if recipient_id in [ride.rider_id, ride.driver_id]:
                await manager.send_personal_message(f"User {user_id}: {message}", recipient_id)
            else:
                await websocket.send_text("Recipient not part of this ride.")

    except WebSocketDisconnect:
        await manager.disconnect(user_id)
        logger.info(f"User {user_id} disconnected from WebSocket.")
    except Exception as e:
        logger.error(f"Unexpected error in WebSocket: {e}")
        await websocket.close(code=1011)  # Close with a server error code



@app.websocket("/ws/call/{ride_id}/{user_id}")
async def websocket_call_endpoint(
    websocket: WebSocket,
    ride_id: int,
    user_id: int,
    db: AsyncSession = Depends(get_async_db)
):
    """
    WebSocket endpoint for handling call functionality within a ride.
    """
    # Check if the ride exists
    result = await db.execute(select(Ride).filter_by(id=ride_id))
    ride = result.scalar()

    if not ride:
        await websocket.close(code=1008)
        raise HTTPException(status_code=404, detail="Ride not found")

    # Check if the user is authorized for the ride
    if ride.rider_id != user_id and ride.driver_id != user_id:
        await websocket.close(code=1008)
        raise HTTPException(status_code=403, detail="User not authorized for this ride")

    # Connect the user to the CallConnectionManager
    await call_manager.connect(user_id, websocket)

    try:
        while True:
            data = await websocket.receive_json()

            event_type = data.get("event_type")
            recipient_id = data.get("recipient_id")
            payload = data.get("payload")

            if not recipient_id or recipient_id not in [ride.rider_id, ride.driver_id]:
                await websocket.send_json({"error": "Recipient not part of this ride."})
                continue

            # Handle different call events
            if event_type == "call_initiate":
                # Log the call initiation
                call_log = CallLog(
                    ride_id=ride_id,
                    caller_id=user_id,
                    receiver_id=recipient_id,
                    status="INITIATED"
                )
                db.add(call_log)
                await db.commit()

                # Notify the recipient
                await call_manager.send_personal_message(
                    {
                        "event_type": "call_initiate",
                        "from_user": user_id,
                        "message": "Incoming call.",
                        "payload": payload
                    },
                    recipient_id
                )

            elif event_type == "call_accept":
                # Update call log status
                call_log = await db.execute(
                    select(CallLog)
                    .filter_by(ride_id=ride_id, caller_id=recipient_id, receiver_id=user_id, status="INITIATED")
                )
                call_log = call_log.scalar()
                if call_log:
                    call_log.status = "ACCEPTED"
                    await db.commit()

                # Notify the caller
                await call_manager.send_personal_message(
                    {"event_type": "call_accept", "from_user": user_id, "message": "Call accepted."},
                    recipient_id
                )

            elif event_type == "call_reject":
                # Update call log status
                call_log = await db.execute(
                    select(CallLog)
                    .filter_by(ride_id=ride_id, caller_id=recipient_id, receiver_id=user_id, status="INITIATED")
                )
                call_log = call_log.scalar()
                if call_log:
                    call_log.status = "REJECTED"
                    await db.commit()

                # Notify the caller
                await call_manager.send_personal_message(
                    {"event_type": "call_reject", "from_user": user_id, "message": "Call rejected."},
                    recipient_id
                )

            elif event_type == "call_end":
                # End an active call
                await call_manager.send_personal_message(
                    {"event_type": "call_end", "from_user": user_id, "message": "Call ended."},
                    recipient_id
                )

            elif event_type == "signal":
                # Exchange signaling data for WebRTC
                await call_manager.send_personal_message(
                    {"event_type": "signal", "from_user": user_id, "payload": payload},
                    recipient_id
                )

            else:
                await websocket.send_json({"error": "Invalid event type."})

    except WebSocketDisconnect:
        await call_manager.disconnect(user_id)
        logger.info(f"User {user_id} disconnected from WebSocket.")
    except Exception as e:
        logger.error(f"Unexpected error in WebSocket: {e}")

        await websocket.close(code=1011)  # Close with a server error code



@app.websocket("/ws/drivers/{driver_id}")
async def driver_ws(websocket: WebSocket, driver_id: int, db: AsyncSession = Depends(get_async_db)):
    # 👇 Delegate all logic to the manager
    await driver_connection_manager.connect(driver_id, websocket, db)


@app.on_event("startup")
async def start_background_tasks():
    asyncio.create_task(background_price_updater(get_async_db))


origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://76.76.21.21",  # Allow direct IP access over HTTP
    "https://76.76.21.21", # If served over HTTPS (which Vercel usually does)
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,  # Use ["*"] for testing only
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(auth.router, prefix="/auth", tags=["Auth"])
app.include_router(users.router, prefix="/users", tags=["Users"])
app.include_router(wallet.router, prefix="/wallet", tags=["Wallet"])
app.include_router(chatMessage.router, prefix="/chatMessage", tags=["ChatMessage"])
app.include_router(pushNotifications.router, prefix="/pushNotifications", tags=["pushNotifications"])
app.include_router(coins.router, prefix="/coins", tags=["coins"])


