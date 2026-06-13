"""
Cynthia PC Client.
WebSocket client connecting local PCs to the Cynthia Brain Server. 
Executes system controls, downloads, and automation commands requested by the Master Brain.
"""
import asyncio
import websockets
import json
import socket
import platform
import os
import subprocess
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("PC_Client")

# Configuration
SERVER_URL = "ws://localhost:8000/ws/"
DEVICE_ID = f"pc_{socket.gethostname().lower()}"
DEVICE_NAME = socket.gethostname()
DEVICE_TYPE = "pc"
CAPABILITIES = ["shell", "screen", "files", "popup"]

async def connect_to_brain():
    uri = f"{SERVER_URL}{DEVICE_ID}"
    while True:
        try:
            logger.info(f"Connecting to Brain at {uri}...")
            async with websockets.connect(uri) as websocket:
                logger.info("Connected!")
                
                # 1. Register
                reg_msg = {
                    "type": "register",
                    "device_id": DEVICE_ID,
                    "name": DEVICE_NAME,
                    "device_type": DEVICE_TYPE,
                    "capabilities": CAPABILITIES,
                    "battery": 100, # Plugged in
                    "os": f"{platform.system()} {platform.release()}"
                }
                await websocket.send(json.dumps(reg_msg))
                logger.info("Sent Registration")

                # 2. Main Loop
                while True:
                    try:
                        message = await websocket.recv()
                        data = json.loads(message)
                        logger.info(f"Received: {data}")
                        
                        if data.get("type") == "command":
                            await handle_command(websocket, data)
                        elif data.get("type") == "ack":
                            logger.info(f"Brain Ack: {data.get('message')}")
                            
                    except websockets.exceptions.ConnectionClosed:
                        logger.warning("Connection closed by server")
                        break
                    except Exception as e:
                        logger.error(f"Error in loop: {e}")
                        break
        except Exception as e:
            logger.error(f"Connection failed: {e}")
            logger.info("Retrying in 5 seconds...")
            await asyncio.sleep(5)

async def handle_command(websocket, data):
    command_id = data.get("command_id")
    action = data.get("action")
    params = data.get("params", {})
    
    logger.info(f"Executing action: {action}")
    status = "success"
    output = ""
    
    try:
        if action == "shell":
            cmd = params.get("cmd")
            if cmd:
                # Security risk: Verify command in real app
                proc = subprocess.run(cmd, shell=True, capture_output=True, text=True)
                output = proc.stdout + proc.stderr
            else:
                status = "error"
                output = "No command provided"
                
        elif action == "download_file":
            import requests # Make sure requests is imported or use urllib
            # Params: url, filename
            url = params.get("url")
            filename = params.get("filename", "downloaded_file")
            
            if url:
                try:
                    # Save to Downloads folder
                    downloads_path = os.path.join(os.path.expanduser("~"), "Downloads")
                    save_path = os.path.join(downloads_path, filename)
                    
                    logger.info(f"Downloading {url} to {save_path}...")
                    
                    # Simple Download implementation
                    # Note: blocking request, but okay for this prototype
                    import requests 
                    r = requests.get(url, stream=True)
                    if r.status_code == 200:
                        with open(save_path, 'wb') as f:
                            for chunk in r.iter_content(chunk_size=8192):
                                f.write(chunk)
                        output = f"File saved to {save_path}"
                    else:
                        status = "error"
                        output = f"Download failed: {r.status_code}"
                except Exception as e:
                    status = "error"
                    output = f"Download error: {e}"
            else:
                 status = "error"
                 output = "No URL provided"

        elif action == "popup":
            msg = params.get("text", "Hello from Brain")
            # Windows only popup
            # Windows only popup
            if platform.system() == "Windows":
                # Use native Windows MessageBox via ctypes (reliable)
                import ctypes
                try:
                    # MB_OK | MB_ICONINFORMATION | MB_SYSTEMMODAL (0x1000) to force top
                    ctypes.windll.user32.MessageBoxW(0, msg, "Jarvis Message", 0x40 | 0x1) 
                except Exception as e:
                     logger.error(f"Popup failed: {e}")
            output = f"Displayed popup: {msg}"
            
        elif action == "screen":
            # Placeholder for screenshot logic
            output = "Screenshot taken (simulated)"
            
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
    logger.info(f"Sent Result: {status}")

if __name__ == "__main__":
    try:
        asyncio.run(connect_to_brain())
    except KeyboardInterrupt:
        logger.info("Client stopped by user")
