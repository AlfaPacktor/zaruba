# main.py
import asyncio
import json
from datetime import datetime, timedelta
from typing import Dict, List

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

# --- Pydantic models for request data validation ---
class SessionRegistration(BaseModel):
    participant1: str
    participant2: str

class UserLogin(BaseModel):
    login: str

class EndSession(BaseModel):
    session_id: str


# --- FastAPI App Initialization ---
app = FastAPI()

# --- In-memory data storage ---
# In a real application, this would be a database (e.g., PostgreSQL + Redis)
# Key: session_id (participant2's name), Value: session data
active_sessions: Dict[str, Dict] = {}

# The list of products, used across the application
PRODUCT_LIST = [
    "ДК", "КК", "Комбо/Кросс КК", "ЦП", "Гос.Уведомления", "Смарт",
    "Кешбек", "ЖКУ", "БС", "БС со Стратегией", "Инвесткопилка",
    "Токенизация", "Накопительный Счет", "Вклад", "Детская Кросс",
    "Сим-Карта", "Перевод Пенсии", "Селфи ДК", "Селфи КК"
]

# --- WebSocket Connection Manager ---
class ConnectionManager:
    def __init__(self):
        # Stores active connections for each session
        self.active_connections: Dict[str, List[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, session_id: str):
        await websocket.accept()
        if session_id not in self.active_connections:
            self.active_connections[session_id] = []
        self.active_connections[session_id].append(websocket)

    def disconnect(self, websocket: WebSocket, session_id: str):
        if session_id in self.active_connections:
            self.active_connections[session_id].remove(websocket)
            # If no connections are left, we can consider cleaning up the session
            # For now, we'll let sessions expire or be manually ended

    async def broadcast(self, message: str, session_id: str):
        if session_id in self.active_connections:
            for connection in self.active_connections[session_id]:
                await connection.send_text(message)

manager = ConnectionManager()

# --- Background task to clean up old sessions ---
async def cleanup_old_sessions():
    while True:
        await asyncio.sleep(3600)  # Check every hour
        now = datetime.utcnow()
        sessions_to_delete = []
        for session_id, data in active_sessions.items():
            if now - data["created_at"] > timedelta(hours=15):
                sessions_to_delete.append(session_id)
        
        for session_id in sessions_to_delete:
            if session_id in active_sessions:
                del active_sessions[session_id]
            if session_id in manager.active_connections:
                del manager.active_connections[session_id]
            print(f"Session {session_id} expired and was cleaned up.")

@app.on_event("startup")
async def startup_event():
    # Start the background task when the server starts
    asyncio.create_task(cleanup_old_sessions())


# --- HTTP Endpoints ---

# 1. Serve Frontend Files
@app.get("/")
async def get_page():
    with open("index.html", "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read(), status_code=200)

@app.get("/style.css")
async def get_styles():
    with open("style.css", "r", encoding="utf-8") as f:
        # Return with the correct media type for CSS
        return HTMLResponse(content=f.read(), media_type="text/css")

@app.get("/script.js")
async def get_scripts():
    with open("script.js", "r", encoding="utf-8") as f:
        # Return with the correct media type for JavaScript
        return HTMLResponse(content=f.read(), media_type="application/javascript")

# 2. Register a new session ("Заруба")
@app.post("/register")
async def register_session(registration_data: SessionRegistration):
    p1 = registration_data.participant1.strip()
    p2 = registration_data.participant2.strip()
    session_id = p2  # The session is identified by participant 2's name

    if not p1 or not p2:
        return JSONResponse(status_code=400, content={"message": "Имена участников не могут быть пустыми."})
    if p1 == p2:
        return JSONResponse(status_code=400, content={"message": "Имена участников должны быть разными."})
    if session_id in active_sessions:
        return JSONResponse(status_code=409, content={"message": f"Сессия для участника '{p2}' уже существует. Попросите его завершить старую сессию или выберите другое имя."})

    # Create a new session
    active_sessions[session_id] = {
        "participant1": p1,
        "participant2": p2,
        "scores": {
            p1: {product: 0 for product in PRODUCT_LIST},
            p2: {product: 0 for product in PRODUCT_LIST},
        },
        "created_at": datetime.utcnow()
    }
    print(f"New session created: {session_id}")
    return JSONResponse(status_code=201, content={"message": "Сессия создана!", "session_id": session_id, "user_name": p1})

# 3. Login for the second participant
@app.post("/login")
async def login_user(login_data: UserLogin):
    login = login_data.login.strip()
    session_id = login

    if session_id not in active_sessions:
        return JSONResponse(status_code=404, content={"message": "Сессия с таким именем не найдена. Убедитесь, что Участник 1 правильно ввел ваше имя."})
    
    return JSONResponse(status_code=200, content={"message": "Вход выполнен!", "session_id": session_id, "user_name": login})

# 4. End a session
@app.post("/end_session")
async def end_session(session_data: EndSession):
    session_id = session_data.session_id
    if session_id in active_sessions:
        # Notify clients that the session is ending
        await manager.broadcast(json.dumps({"type": "session_ended"}), session_id)
        
        # Clean up
        del active_sessions[session_id]
        if session_id in manager.active_connections:
            del manager.active_connections[session_id]
            
        print(f"Session {session_id} ended by a user.")
        return JSONResponse(status_code=200, content={"message": "Сессия успешно завершена."})
    
    return JSONResponse(status_code=404, content={"message": "Сессия не найдена."})


# --- WebSocket Endpoint for real-time communication ---
@app.websocket("/ws/{session_id}/{user_name}")
async def websocket_endpoint(websocket: WebSocket, session_id: str, user_name: str):
    if session_id not in active_sessions:
        await websocket.close(code=1008)
        return

    await manager.connect(websocket, session_id)
    
    try:
        # Send initial data to the newly connected client
        initial_data = {
            "type": "state_update",
            "data": active_sessions[session_id
