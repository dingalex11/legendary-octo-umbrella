import asyncio
import json
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from core.events import Event
import uvicorn
import os

import os
import asyncio
import json
from typing import Dict, List
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
import sys
import os

# 1. Get the absolute path of the current subfolder
current_dir = os.path.dirname(os.path.abspath(__file__))

# 2. Go up one level to the root project directory
parent_dir = os.path.dirname(current_dir)

# 3. Add the root directory to Python's system path
sys.path.append(parent_dir)

# 4. NOW you can safely import from main!
# Adjust the import based on where your moderator class lives
from main import ScienceBowlModerator 

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class RoomManager:
    """Manages WebSocket connections with room support"""
    def __init__(self):
        # Maps room_id to its own isolated game engine instance
        self.rooms: Dict[str, ScienceBowlModerator] = {}
        # Maps room_id to a list of connected WebSockets
        self.active_connections: Dict[str, List[WebSocket]] = {}

    def get_or_create_room(self, room_id: str) -> ScienceBowlModerator:
        if room_id not in self.rooms:
            # Initialize a fresh, isolated game engine for this new room
            moderator = ScienceBowlModerator()
            self.rooms[room_id] = moderator
            self.active_connections[room_id] = []
            
            # Start the background game loop for this specific room
            asyncio.create_task(moderator.run_game_loop())
            
            # Start the background task to route outbound messages to room clients
            asyncio.create_task(self.listen_for_outbound(room_id, moderator))
            
            print(f"🚀 Room created: {room_id}")
            
        return self.rooms[room_id]

    async def listen_for_outbound(self, room_id: str, moderator: ScienceBowlModerator):
        """Constantly reads the moderator's outbound queue and broadcasts it."""
        while True:
            # Wait for the game engine to generate a payload (e.g., score update)
            message = await moderator.outbound_queue.get()
            await self.broadcast_to_room(room_id, message)

    async def connect(self, websocket: WebSocket, room_id: str):
        await websocket.accept()
        self.get_or_create_room(room_id)
        self.active_connections[room_id].append(websocket)

    def disconnect(self, websocket: WebSocket, room_id: str):
        if room_id in self.active_connections:
            self.active_connections[room_id].remove(websocket)
            # Optional cleanup: Delete the room from RAM if everyone leaves
            # if not self.active_connections[room_id]:
            #     del self.rooms[room_id]
            #     del self.active_connections[room_id]

    async def broadcast_to_room(self, room_id: str, message: dict):
        if room_id in self.active_connections:
            for connection in self.active_connections[room_id]:
                try:
                    await connection.send_text(json.dumps(message))
                except RuntimeError:
                    # Safely ignore disconnected clients
                    pass

manager = RoomManager()

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/video_feed")
async def video_feed():
    """Streams MJPEG frames to the frontend for calibration."""
    ui_service = app.state.ui_service
    async def frame_generator():
        while True:
            # Safely grab the frame from VisionService
            if hasattr(ui_service, 'vision_service') and ui_service.vision_service:
                frame_bytes = ui_service.vision_service.get_mjpeg_frame()
                if frame_bytes:
                    yield (b'--frame\r\n'
                           b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
            # Throttle stream to ~10 FPS to save network/browser rendering CPU
            await asyncio.sleep(0.1) 
            
    return StreamingResponse(frame_generator(), media_type="multipart/x-mixed-replace; boundary=frame")

class HTMLGUIService:
    def __init__(self, inbound_queue: asyncio.Queue, outbound_queue: asyncio.Queue, vision_service=None):
        self.inbound_queue = inbound_queue
        self.outbound_queue = outbound_queue
        self.vision_service = vision_service 
        self.active_connections: list[WebSocket] = []
        app.state.ui_service = self

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        print("\n🌐 [UI SERVICE]: Browser connected to WebSocket!")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        print("\n🌐 [UI SERVICE]: Browser disconnected.")

    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except RuntimeError:
                continue

    import os

    async def start_server(self):
        port = int(os.environ.get("PORT", 8080))
        config = uvicorn.Config(app, host="0.0.0.0", port=port, log_level="warning")
        server = uvicorn.Server(config)
        await server.serve()

    async def update_ui_from_queue(self):
        while True:
            try:
                event = await self.outbound_queue.get()
                
                if isinstance(event, dict):
                    await self.broadcast(event)
                else:
                    evt_type = event.type.name if hasattr(event.type, 'name') else str(event.type)
                    payload = getattr(event, 'payload', {})
                    await self.broadcast({"type": evt_type, "payload": payload})
            except asyncio.CancelledError:
                break

# --- FastAPI Routes ---

@app.get("/")
async def get_index():
    with open("index.html", "r", encoding="utf-8") as f:
        return HTMLResponse(f.read())

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    ui_service: HTMLGUIService = app.state.ui_service
    await ui_service.connect(websocket)
    
    try:
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)
            
            # ROUTE EVERYTHING DIRECTLY TO MEMORY
            ui_service.inbound_queue.put_nowait(Event(type=message["type"], payload=message.get("payload", {})))
            
            # Send immediate feedback for calibration without touching the disk
            if message["type"] == "SAVE_CALIBRATION":
                await ui_service.outbound_queue.put({"type": "UPDATE_STATUS", "payload": {"text": "✅ Session ROIs Locked in Memory!"}})
                
    except WebSocketDisconnect:
        ui_service.disconnect(websocket)

@app.websocket("/ws/{room_id}")
async def websocket_endpoint(websocket: WebSocket, room_id: str):
    await manager.connect(websocket, room_id)
    moderator = manager.get_or_create_room(room_id)
    
    try:
        while True:
            # 1. Receive data from a client in this room
            data = await websocket.receive_text()
            payload = json.loads(data)
            
            # 2. Feed it into this specific room's game engine
            await moderator.inbound_queue.put(payload)
            
    except WebSocketDisconnect:
        manager.disconnect(websocket, room_id)
        print(f"Client disconnected from room {room_id}")