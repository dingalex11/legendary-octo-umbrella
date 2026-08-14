import asyncio
import json
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from core.events import Event
import uvicorn
import os
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