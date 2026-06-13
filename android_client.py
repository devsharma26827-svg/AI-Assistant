import asyncio
import websockets
import json
import logging
import platform

# --- CONFIGURATION (EDIT THIS IP) ---
# Your Laptop's Local IP
SERVER_IP = "10.133.83.26" 
SERVER_PORT = "8000"
SERVER_URL = f"ws://{SERVER_IP}:{SERVER_PORT}/ws/"

DEVICE_ID = "android_phone_01"
DEVICE_NAME = "My Android Phone"
DEVICE_TYPE = "mobile"
# 'vibrate' and 'toast' are mobile specific
CAPABILITIES = ["notification", "toast", "vibrate"] 

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("AndroidClient")

async def connect_to_brain():
    uri = f"{SERVER_URL}{DEVICE_ID}"
    logger.info(f"Attempting connection to: {uri}")
    
    while True:
        try:
            async with websockets.connect(uri) as websocket:
                logger.info("✅ Connected to Brain!")
                
                # 1. Register
                reg_msg = {
                    "type": "register",
                    "device_id": DEVICE_ID,
                    "name": DEVICE_NAME,
                    "device_type": DEVICE_TYPE,
                    "capabilities": CAPABILITIES,
                    "battery": 85, # Placeholder, hard to get in pure python without plyer
                    "os": "Android"
                }
                await websocket.send(json.dumps(reg_msg))
                logger.info("Sent Registration")

                # 2. Main Loop
                while True:
                    message = await websocket.recv()
                    data = json.loads(message)
                    logger.info(f"📩 Received: {data}")
                    
                    if data.get("type") == "command":
                        await handle_command(websocket, data)
                    elif data.get("type") == "ack":
                        logger.info(f"Brain Ack: {data.get('message')}")
                        
        except Exception as e:
            logger.error(f"❌ Connection failed: {e}")
            logger.info("Retrying in 5 seconds...")
            await asyncio.sleep(5)

async def handle_command(websocket, data):
    command_id = data.get("command_id")
    action = data.get("action")
    params = data.get("params", {})
    
    status = "success"
    output = ""
    
    try:
        if action == "toast":
            text = params.get("text", "Hello")
            print(f"🍞 TOAST: {text}")
            try:
                # Termux/Android native integration (if avaliable)
                from androidhelper import Android
                droid = Android()
                droid.makeToast(text)
                output = f"Toast shown: {text}"
            except:
                output = f"Toast (Simulated): {text}"

        elif action == "vibrate":
            duration = params.get("duration", 1000)
            print(f"📳 VIBRATING for {duration}ms")
            try:
                from androidhelper import Android
                droid = Android()
                droid.vibrate(duration)
                output = "Vibrated success"
            except:
                output = "Vibrate (Simulated)"

        elif action == "notification":
            title = params.get("title", "Jarvis")
            msg = params.get("message", "Alert")
            print(f"🔔 NOTIFICATION: {title} - {msg}")
            try:
                 from androidhelper import Android
                 droid = Android()
                 droid.notify(title, msg)
            except:
                 pass
            output = f"Notification: {title}"

        else:
            status = "error"
            output = f"Unknown action: {action}"
            
    except Exception as e:
        status = "error"
        output = str(e)

    # Send Result
    result = {
        "type": "result",
        "command_id": command_id,
        "status": status,
        "output": output
    }
    await websocket.send(json.dumps(result))

if __name__ == "__main__":
    try:
        asyncio.run(connect_to_brain())
    except KeyboardInterrupt:
        pass
