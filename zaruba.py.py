# main.py
import asyncio
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import HTMLResponse
from typing import List, Dict
import json

# Создаем приложение FastAPI
app = FastAPI()

# --- Хранилище данных в памяти ---
# В реальном приложении здесь была бы база данных (PostgreSQL + Redis)
# Ключ - имя Участника 2, значение - вся информация о сессии
active_sessions: Dict[str, Dict] = {}

# Список продуктов, который будет использоваться везде
PRODUCT_LIST = [
    "ДК", "КК", "Комбо/Кросс КК", "ЦП", "Гос.Уведомления", "Смарт",
    "Кешбек", "ЖКУ", "БС", "БС со Стратегией", "Инвесткопилка",
    "Токенизация", "Накопительный Счет", "Вклад", "Детская Кросс",
    "Сим-Карта", "Перевод Пенсии", "Селфи ДК", "Селфи КК"
]

# --- Класс для управления WebSocket-соединениями ---
class ConnectionManager:
    def __init__(self):
        # Храним активные подключения для каждой сессии
        self.active_connections: Dict[str, List[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, session_id: str):
        await websocket.accept()
        if session_id not in self.active_connections:
            self.active_connections[session_id] = []
        self.active_connections[session_id].append(websocket)

    def disconnect(self, websocket: WebSocket, session_id: str):
        if session_id in self.active_connections:
            self.active_connections[session_id].remove(websocket)

    async def broadcast(self, message: str, session_id: str):
        if session_id in self.active_connections:
            for connection in self.active_connections[session_id]:
                await connection.send_text(message)

manager = ConnectionManager()


# --- API эндпоинты (точки входа для фронтенда) ---

# Отдаем главную HTML страницу
@app.get("/")
async def get_page():
    with open("index.html", "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read(), status_code=200)

# Отдаем CSS стили
@app.get("/style.css")
async def get_styles():
    with open("style.css", "r", encoding="utf-8") as f:
        