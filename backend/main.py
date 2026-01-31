from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
import os
from typing import Optional, List
from pydantic import BaseModel
from dotenv import load_dotenv
import psycopg2
from psycopg2 import pool as psycopg2_pool
from psycopg2.extras import DictCursor
import ipaddress

from contextlib import asynccontextmanager

# Загружаем переменные окружения из .env файла
load_dotenv()

@asynccontextmanager
async def lifespan(app: FastAPI):
    get_pool_sync()
    yield
    global connection_pool
    if connection_pool:
        connection_pool.closeall()

app = FastAPI(title="Referral Balance API",lifespan=lifespan)

# IP Whitelist Middleware
class IPWhitelistMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, allowed_ips: List[str]):
        super().__init__(app)
        self.allowed_ips = allowed_ips
        # Разрешаем localhost для разработки
        self.allowed_ips.extend(['127.0.0.1', '::1', 'localhost'])
    
    async def dispatch(self, request: Request, call_next):
        # Получаем IP клиента
        client_ip = request.client.host if request.client else None
        
        # Проверяем X-Forwarded-For заголовок (если за прокси)
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            client_ip = forwarded_for.split(",")[0].strip()
        
        # Проверяем X-Real-IP заголовок
        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            client_ip = real_ip.strip()
        
        # Если whitelist не настроен или пуст (только localhost), разрешаем все
        # Проверяем, что в списке только localhost адреса
        non_localhost_ips = [ip for ip in self.allowed_ips if ip not in ['127.0.0.1', '::1', 'localhost']]
        if not non_localhost_ips:
            return await call_next(request)
        
        # Проверяем IP
        if client_ip and self._is_ip_allowed(client_ip):
            return await call_next(request)
        else:
            return JSONResponse(
                status_code=status.HTTP_403_FORBIDDEN,
                content={"error": "Access denied. Your IP is not whitelisted."}
            )
    
    def _is_ip_allowed(self, ip: str) -> bool:
        """Проверяет, разрешен ли IP"""
        # Проверяем точное совпадение
        if ip in self.allowed_ips:
            return True
        
        # Проверяем CIDR блоки
        for allowed in self.allowed_ips:
            try:
                if '/' in allowed:
                    # Это CIDR блок
                    network = ipaddress.ip_network(allowed, strict=False)
                    if ipaddress.ip_address(ip) in network:
                        return True
                else:
                    # Точный IP
                    if ip == allowed:
                        return True
            except (ValueError, ipaddress.AddressValueError):
                continue
        
        return False

# Настройка IP whitelist из переменных окружения
# Формат: ALLOWED_IPS=192.168.1.1,10.0.0.0/8,203.0.113.0/24
allowed_ips_str = os.getenv("ALLOWED_IPS", "")
allowed_ips = [ip.strip() for ip in allowed_ips_str.split(",") if ip.strip()] if allowed_ips_str else []

# Добавляем IP whitelist middleware
# Если whitelist пуст, middleware все равно добавится, но будет разрешать все IP
app.add_middleware(IPWhitelistMiddleware, allowed_ips=allowed_ips)
if allowed_ips:
    print(f"✓ IP Whitelist активен: {len(allowed_ips)} IP адресов/сетей")
else:
    print("⚠ IP Whitelist не настроен - доступ открыт для всех")

# CORS настройки для работы с фронтендом
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # В продакшене укажите конкретный домен
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Модель данных
class ReferralBalance(BaseModel):
    user_id: int
    username: Optional[str]
    debt: float  # referral_balance - withdrawn_balance
    total_referral_balance: float  # referral_balance

# Конфигурация БД
db_info = {
    "dbname": os.getenv("DB_NAME", "default_db"),
    "user": os.getenv("DB_USER", "gen_user"),
    "password": os.getenv("DB_PASSWORD", "TimaSun1502@@@"),
    "host": os.getenv("DB_HOST", "188.225.35.116"),
    "port": int(os.getenv("DB_PORT", "5432"))
}

# Пул соединений
connection_pool = None

def get_pool_sync():
    """Создает синхронный пул соединений"""
    global connection_pool
    if connection_pool is None:
        try:
            connection_pool = psycopg2_pool.ThreadedConnectionPool(
                1, 20,  # минимум 1, максимум 20 соединений
                **db_info
            )
            print(f"✓ Пул соединений создан: {db_info['host']}:{db_info['port']}/{db_info['dbname']}")
        except Exception as e:
            print(f"✗ Ошибка создания пула: {e}")
            raise
    return connection_pool

@app.get("/api/referral-balances")
async def get_referral_balances():
    """
    Получает список всех пользователей с их реферальными балансами.
    Username берется из таблицы users (предполагается, что она существует).
    """
    try:
        pool = get_pool_sync()
        conn = pool.getconn()
        
        try:
            cur = conn.cursor(cursor_factory=DictCursor)
            
            # SQL запрос с фильтрами:
            # - referral_count1 > 1 (количество рефералов 1 уровня больше 1)
            # - referral_balance > 0 (реферальный баланс больше нуля)
            query = """
            SELECT 
                r.user_id,
                (r.referral_balance - r.withdrawn_balance) as debt,
                r.referral_balance as total_referral_balance
            FROM referral r
            WHERE r.referral_count1 > 1
                AND r.referral_balance > 0
            ORDER BY r.user_id
            """
            
            cur.execute(query)
            rows = cur.fetchall()
            
            # Получаем список user_id для запроса username
            user_ids = [row["user_id"] for row in rows]
            
            # Отдельный запрос для получения username из таблицы client
            usernames = {}
            if user_ids:
                placeholders = ','.join(['%s'] * len(user_ids))
                username_query = f"""
                SELECT user_id, username
                FROM client
                WHERE user_id IN ({placeholders})
                """
                cur.execute(username_query, user_ids)
                username_rows = cur.fetchall()
                usernames = {row["user_id"]: row["username"] for row in username_rows}
            
            cur.close()
            
            result = [
                {
                    "user_id": row["user_id"],
                    "username": usernames.get(row["user_id"]),
                    "debt": float(row["debt"]),
                    "total_referral_balance": float(row["total_referral_balance"])
                }
                for row in rows
            ]
            
            return JSONResponse(content={"data": result})
        finally:
            pool.putconn(conn)
    
    except Exception as e:
        print(f"✗ Ошибка при получении данных: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )

@app.get("/health")
async def health_check():
    """Проверка здоровья API"""
    return {"status": "ok"}

if __name__ == "__main__":
    import uvicorn
    # Получаем хост и порт из переменных окружения
    host = os.getenv("HOST", "0.0.0.0")  # По умолчанию слушаем на всех интерфейсах
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host=host, port=port)
