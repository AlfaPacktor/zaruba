import asyncio
import json
from datetime import datetime, timedelta
from typing import Dict, List

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

# --- Pydantic models ---
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
active_sessions: Dict[str, Dict] = {}
PRODUCT_LIST = [
    "ДК", "КК", "Комбо/Кросс КК", "ЦП", "Гос.Уведомления", "Смарт",
    "Кешбек", "ЖКУ", "БС", "БС со Стратегией", "Инвесткопилка",
    "Токенизация", "Накопительный Счет", "Вклад", "Детская Кросс",
    "Сим-Карта", "Перевод Пенсии", "Селфи ДК", "Селфи КК"
]

# --- Connection Manager ---
class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, List[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, session_id: str):
        await websocket.accept()
        self.active_connections.setdefault(session_id, []).append(websocket)

    def disconnect(self, websocket: WebSocket, session_id: str):
        if session_id in self.active_connections:
            self.active_connections[session_id].remove(websocket)

    async def broadcast(self, message: str, session_id: str):
        for connection in self.active_connections.get(session_id, []):
            await connection.send_text(message)

manager = ConnectionManager()

# --- Periodic Cleanup Task ---
async def cleanup_old_sessions():
    while True:
        await asyncio.sleep(3600)
        now = datetime.utcnow()
        sessions_to_delete = [
            session_id for session_id, data in active_sessions.items()
            if now - data.get("created_at", now) > timedelta(hours=15)
        ]
        for session_id in sessions_to_delete:
            active_sessions.pop(session_id, None)
            manager.active_connections.pop(session_id, None)
            print(f"Session {session_id} expired and was cleaned up.")

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(cleanup_old_sessions())

# --- HTTP Endpoints ---
@app.get("/")
async def get_page():
    return HTMLResponse(content=open("index.html", "r", encoding="utf-8").read(), status_code=200)

@app.get("/style.css")
async def get_styles():
    return HTMLResponse(content=open("style.css", "r", encoding="utf-8").read(), media_type="text/css")

@app.get("/script.js")
async def get_scripts():
    return HTMLResponse(content=open("script.js", "r", encoding="utf-8").read(), media_type="application/javascript")

@app.post("/register")
async def register_session(registration_data: SessionRegistration):
    p1, p2 = registration_data.participant1.strip(), registration_data.participant2.strip()
    session_id = p2

    if not p1 or not p2 or p1 == p2:
        return JSONResponse(status_code=400, content={"message": "Имена участников должны быть разными и не пустыми."})
    if session_id in active_sessions:
        return JSONResponse(status_code=409, content={"message": f"Сессия для '{p2}' уже существует."})

    active_sessions[session_id] = {
        "participant1": p1,
        "participant2": p2,
        "scores": {p1: {product: 0 for product in PRODUCT_LIST}, p2: {product: 0 for product in PRODUCT_LIST}},
        "created_at": datetime.utcnow()
    }
    print(f"New session created: {session_id}")
    return JSONResponse(status_code=201, content={"message": "Сессия создана!", "session_id": session_id, "user_name": p1})

@app.post("/login")
async def login_user(login_data: UserLogin):
    session_id = login_data.login.strip()
    if session_id not in active_sessions:
        return JSONResponse(status_code=404, content={"message": "Сессия не найдена."})
    return JSONResponse(status_code=200, content={"message": "Вход выполнен!", "session_id": session_id})

@app.post("/end_session")
async def end_session(session_data: EndSession):
    session_id = session_data.session_id
    if session_id in active_sessions:
        await manager.broadcast(json.dumps({"type": "session_ended"}), session_id)
        active_sessions.pop(session_id, None)
        manager.active_connections.pop(session_id, None)
        print(f"Session {session_id} ended.")
        return JSONResponse(status_code=200, content={"message": "Сессия успешно завершена."})
    return JSONResponse(status_code=404, content={"message": "Сессия не найдена."})

# --- WebSocket Endpoint ---
@app.websocket("/ws/{session_id}/{user_name}")
async def websocket_endpoint(websocket: WebSocket, session_id: str, user_name: str):
    if session_id not in active_sessions:
        await websocket.close(code=1008)
        return

    await manager.connect(websocket, session_id)
    try:
        await websocket.send_text(json.dumps({"type": "state_update", "data": active_sessions[session_id]}))
        while True:
            data = json.loads(await websocket.receive_text())
            if data.get("type") == "update_score" and session_id in active_sessions:
                active_sessions[session_id]["scores"][user_name] = data.get("payload", {})
                await manager.broadcast(json.dumps({"type": "state_update", "data": active_sessions[session_id]}), session_id)
    except WebSocketDisconnect:
        manager.disconnect(websocket, session_id)
        print(f"User {user_name} disconnected from session {session_id}")
    except Exception as e:
        print(f"Error in WebSocket: {e}")
        manager.disconnect(websocket, session_id)

# --- Run Server ---
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
