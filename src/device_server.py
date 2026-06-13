import asyncio
import logging
from typing import Dict, List, Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from pydantic import BaseModel
import uvicorn
import json
import time

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("BrainServer")

app = FastAPI(title="Jarvis Device Ecosystem Brain")

# --- DATA MODELS ---

class DeviceInfo(BaseModel):
    device_id: str
    name: str
    device_type: str  # 'mobile', 'pc', 'tablet'
    capabilities: List[str]
    battery: int
    os: str
    status: str = "online"
    last_seen: float = 0.0

class CommandRequest(BaseModel):
    target_device_id: str
    action: str
    params: Dict = {}

class BroadcastRequest(BaseModel):
    action: str
    params: Dict = {}

# --- CONNECTION MANAGER & REGISTRY ---

class ConnectionManager:
    def __init__(self):
        # Active socket connections: device_id -> WebSocket
        self.active_connections: Dict[str, WebSocket] = {}
        # Device Registry: device_id -> DeviceInfo
        self.device_registry: Dict[str, DeviceInfo] = {}

    async def connect(self, websocket: WebSocket, device_id: str, initial_info: dict):
        # WebSocket already accepted in endpoint
        self.active_connections[device_id] = websocket
        
        # Register device
        info = DeviceInfo(**initial_info)
        info.last_seen = time.time()
        self.device_registry[device_id] = info
        
        logger.info(f"Device Connected: {info.name} ({device_id})")

    def disconnect(self, device_id: str):
        if device_id in self.active_connections:
            del self.active_connections[device_id]
        
        if device_id in self.device_registry:
            self.device_registry[device_id].status = "offline"
            logger.info(f"Device Disconnected: {device_id}")

    async def send_personal_message(self, message: dict, device_id: str):
        if device_id in self.active_connections:
            websocket = self.active_connections[device_id]
            try:
                await websocket.send_text(json.dumps(message))
                return True
            except Exception as e:
                logger.error(f"Failed to send to {device_id}: {e}")
                return False
        return False

    async def broadcast(self, message: dict):
        for device_id, websocket in self.active_connections.items():
            try:
                await websocket.send_text(json.dumps(message))
            except:
                pass

    def get_device(self, device_id: str) -> Optional[DeviceInfo]:
        return self.device_registry.get(device_id)

    def get_online_devices(self) -> List[DeviceInfo]:
        return [
            d for d in self.device_registry.values() 
            if d.device_id in self.active_connections
        ]

    def find_devices_by_capability(self, capability: str) -> List[DeviceInfo]:
        return [
            d for d in self.get_online_devices()
            if capability in d.capabilities
        ]

manager = ConnectionManager()

# --- WEBSOCKET ENDPOINT ---

@app.websocket("/ws/{device_id}")
async def websocket_endpoint(websocket: WebSocket, device_id: str):
    await websocket.accept() # Accept immediately
    try:
        # Wait for registration message first
        data = await websocket.receive_text()
        message = json.loads(data)
        
        if message.get("type") == "register":
            # Register device
            device_info = {
                "device_id": device_id,
                "name": message.get("name", "Unknown"),
                "device_type": message.get("device_type", "unknown"),
                "capabilities": message.get("capabilities", []),
                "battery": message.get("battery", 0),
                "os": message.get("os", "unknown")
            }
            await manager.connect(websocket, device_id, device_info)
            
            # Send acknowledgement
            await manager.send_personal_message({
                "type": "ack",
                "status": "connected",
                "message": "Welcome to Jarvis Ecosystem"
            }, device_id)
        else:
            await websocket.close(code=4000, reason="Registration required first")
            return

        # Main Loop
        try:
            while True:
                data = await websocket.receive_text()
                msg = json.loads(data)
                
                # Handle Heartbeat / Status Updates / Results
                if msg.get("type") == "heartbeat":
                    if device_id in manager.device_registry:
                        manager.device_registry[device_id].last_seen = time.time()
                        manager.device_registry[device_id].battery = msg.get("battery", 0)
                
                elif msg.get("type") == "result":
                    logger.info(f"Result from {device_id}: {msg}")
                    
                # [NEW] Handle Command Requests (Device-to-Device)
                elif msg.get("type") == "command_request":
                    target_id = msg.get("target")
                    action = msg.get("action")
                    params = msg.get("params", {})
                    logger.info(f"Routing command from {device_id} to {target_id}: {action}")
                    
                    # Logic to find target and send
                    target_device = manager.get_device(target_id)
                    
                    # Fuzzy Match logic reuse
                    if not target_device:
                         target_lower = target_id.lower()
                         for d in manager.get_online_devices():
                             if (target_lower in d.name.lower()) or (target_lower == d.device_type.lower()) or (target_lower in d.device_id.lower()):
                                 target_device = d
                                 break
                    
                    if target_device:
                        payload = {
                            "type": "command",
                            "command_id": f"cmd_r_{int(time.time())}",
                            "action": action,
                            "params": params
                        }
                        await manager.send_personal_message(payload, target_device.device_id)
                        await websocket.send_text(json.dumps({"type": "info", "msg": f"Command sent to {target_device.name}"}))
                    else:
                        await websocket.send_text(json.dumps({"type": "error", "msg": f"Target '{target_id}' not found"}))

                    
        except WebSocketDisconnect:
            manager.disconnect(device_id)
            
    except Exception as e:
        logger.error(f"WebSocket Error for {device_id}: {e}")
        manager.disconnect(device_id)

# --- HTTP API FOR AGENT ---

@app.get("/")
async def root():
    return {"status": "Jarvis Brain Online", "devices": len(manager.active_connections)}

@app.post("/devices")
async def list_devices():
    return {"devices": manager.get_online_devices()}

@app.post("/command")
async def send_command(request: CommandRequest):
    # 1. Try Exact Match
    device = manager.get_device(request.target_device_id)
    
    # 2. Try Fuzzy Match (Name or Partial ID) if not found
    if not device:
        logger.info(f"Exact match failed for '{request.target_device_id}'. Trying fuzzy match...")
        target_lower = request.target_device_id.lower()
        online_devices = manager.get_online_devices()
        
        for d in online_devices:
            # Match Name (e.g. "Laptop") or Device Type (e.g. "pc") or Partial ID
            if (target_lower in d.name.lower()) or \
               (target_lower == d.device_type.lower()) or \
               (target_lower in d.device_id.lower()):
                device = d
                break
    
    if not device or device.status == "offline":
        raise HTTPException(status_code=404, detail=f"Device '{request.target_device_id}' offline or not found")
     
    
    payload = {
        "type": "command",
        "command_id": f"cmd_{int(time.time())}",
        "action": request.action,
        "params": request.params
    }
    
    success = await manager.send_personal_message(payload, request.target_device_id)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to send command")
        
    return {"status": "sent", "command_id": payload["command_id"]}

@app.post("/broadcast")
async def broadcast_command(request: BroadcastRequest):
    payload = {
        "type": "command",
        "command_id": f"bcast_{int(time.time())}",
        "action": request.action,
        "params": request.params
    }
    await manager.broadcast(payload)
    return {"status": "broadcast_sent"}

@app.post("/find_device")
async def find_device(capability: str):
    devices = manager.find_devices_by_capability(capability)
    return {"devices": devices}


from fastapi.responses import HTMLResponse
import os

from fastapi import File, UploadFile
from fastapi.staticfiles import StaticFiles

# --- FILE TRANSFER ENDPOINTS ---

# Mount 'uploads' to serve files
if not os.path.exists("uploads"):
    os.makedirs("uploads")
app.mount("/files", StaticFiles(directory="uploads"), name="uploads")

@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    try:
        file_location = f"uploads/{file.filename}"
        with open(file_location, "wb+") as file_object:
            file_object.write(file.file.read())
        logger.info(f"File uploaded: {file.filename}")
        return {"info": f"file '{file.filename}' saved at '{file_location}'"}
    except Exception as e:
        logger.error(f"Upload failed: {e}")
        return {"error": str(e)}

@app.get("/list_files")
async def list_uploaded_files():
    files = os.listdir("uploads")
    return {"files": [f for f in files if os.path.isfile(os.path.join("uploads", f))]}

# --- WEB CLIENT ENDPOINTS ---

@app.get("/mobile", response_class=HTMLResponse)
async def mobile_client():
    """Serves the Web-Based Mobile Client"""
    path = os.path.join("templates", "mobile_client.html")
    with open(path, "r") as f:
        return f.read()

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
