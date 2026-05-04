import os
import asyncio
import logging
import json
import re
import random
from typing import List, Dict, Optional
from datetime import datetime, timedelta
from io import BytesIO
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton,
    Message, CallbackQuery
)
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from telethon import TelegramClient, events
from telethon.errors import (
    SessionPasswordNeededError,
    PhoneCodeInvalidError,
    PhoneCodeExpiredError,
    PhoneNumberInvalidError
)
from telethon.sessions import StringSession
from telethon.tl.functions.channels import GetFullChannelRequest
from telethon.tl.types import (
    InputMediaUploadedPhoto,
    InputMediaUploadedDocument,
    DocumentAttributeVideo,
    DocumentAttributeFilename
)
import psycopg2
from psycopg2 import pool
from psycopg2.extras import RealDictCursor
import aiohttp
from PIL import Image

# ===== НАСТРОЙКА ЛОГИРОВАНИЯ =====
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ===== КОНФИГУРАЦИЯ БОТА =====
API_ID = 32480523
API_HASH = "147839735c9fa4e83451209e9b55cfc5"
BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
CRYPTOBOT_TOKEN = os.getenv("CRYPTOBOT_TOKEN")
YOOMONEY_ACCOUNT = "4100119286550472"
ADMIN_ID = 7973988177
FIRST_BOT = "@VestTrafferBot"

# Курсы криптовалют
USDT_RATE = 90
TON_RATE = 90

# Глобальные хранилища
account_clients = {}
active_commentators = {}

# ===== ТАРИФЫ ПОДПИСОК =====
SUBSCRIPTIONS = {
    "7": {"days": 7, "price": 15, "title": "7 дней"},
    "21": {"days": 21, "price": 30, "title": "21 день"},
    "30": {"days": 30, "price": 35, "title": "30 дней"},
    "60": {"days": 60, "price": 50, "title": "60 дней"},
    "180": {"days": 180, "price": 90, "title": "180 дней"},
    "360": {"days": 360, "price": 150, "title": "360 дней"},
}

# ===== ПОДАРКИ =====
GIFTS = {
    "Мишка": {"id": 5170233102089322756, "stars": 0},
    "Подарок": {"id": 5170145012310081615, "stars": 0},
    "Роза": {"id": 5168103777563050263, "stars": 0},
    "Коробка": {"id": 5170250947678437525, "stars": 0},
    "Шампанское": {"id": 6028601630662853006, "stars": 0},
    "Ракета": {"id": 5170564780938756245, "stars": 0},
    "Букет": {"id": 5170314324215857265, "stars": 0},
    "Торт": {"id": 5170144170496491616, "stars": 0},
    "Алмаз": {"id": 5170521118301225164, "stars": 0},
    "Кольцо": {"id": 5170690322832818290, "stars": 0},
    "Кубок": {"id": 5168043875654172773, "stars": 0},
    "Пасхальный мишка": {"id": 5969796561943660080, "stars": 50},
    "Мишка клоун": {"id": 5935895822435615975, "stars": 50},
    "НГ мишка": {"id": 5956217000635139069, "stars": 50},
    "14 Февраля мишка": {"id": 5800655655995968830, "stars": 50},
    "Елочка": {"id": 5922558454332916696, "stars": 50},
    "Сердце 14 февраля": {"id": 5801108895304779062, "stars": 50},
}

# ===== PREMIUM EMOJI ID =====
class Emoji:
    profile = "5870994129244131212"
    people = "5870772616305839506"
    user_profile = "5891207662678317861"
    check = "5870633910337015697"
    cross = "5870657884844462243"
    trash = "5870875489362513438"
    eye = "6037397706505195857"
    write = "5870753782874246579"
    add_text = "5771851822897566479"
    download = "6039802767931871481"
    back = "5373141891321699086"
    send = "5963103826075456248"
    upload = "6039802767931871481"
    clock = "5983150113483134607"
    loading = "5345906554510012647"
    lock_closed = "6037249452824072506"
    lock_open = "6037496202990194718"
    bot_emoji = "6030400221232501136"
    info = "6028435952299413210"
    megaphone = "6039422865189638057"
    tag = "5886285355279193209"
    wallet = "5769126056262898415"
    box = "5884479287171485878"
    crown = "6041731551845159060"
    money = "5904462880941545555"
    admin = "6030400221232501136"
    instruction = "5870528606328852614"
    support = "6039451237743595514"
    gift = "6035128606563241721"
    media = "6035128606563241721"
    stop = "5870657884844462243"
    file_doc = "5870528606328852614"
    first_bot = "6030400221232501136"
    promo = "6032644646587338669"
    comment = "5870753782874246579"
    star = "5356657699865243528"

# ===== БАЗА ДАННЫХ =====
class Database:
    def __init__(self):
        self.pool = None
    
    async def init(self):
        logger.info("Initializing database connection...")
        
        for attempt in range(5):
            try:
                self.pool = psycopg2.pool.ThreadedConnectionPool(1, 10, DATABASE_URL)
                conn = self.pool.getconn()
                conn.cursor().execute("SELECT 1")
                self.pool.putconn(conn)
                logger.info("Database connected successfully")
                break
            except Exception as e:
                logger.error(f"Database connection attempt {attempt + 1} failed: {e}")
                if attempt == 4:
                    logger.critical("All database connection attempts failed")
                    raise
                await asyncio.sleep(5)
        
        loop = asyncio.get_running_loop()
        
        async def _exec(query, *args):
            def run():
                conn = self.pool.getconn()
                try:
                    with conn.cursor() as cursor:
                        cursor.execute(query, args)
                    conn.commit()
                except Exception as e:
                    logger.error(f"SQL execute error: {e}")
                    raise
                finally:
                    self.pool.putconn(conn)
            await loop.run_in_executor(None, run)
        
        async def _fetch(query, *args):
            def run():
                conn = self.pool.getconn()
                try:
                    with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                        cursor.execute(query, args)
                        return cursor.fetchall()
                finally:
                    self.pool.putconn(conn)
            return await loop.run_in_executor(None, run)
        
        async def _fetchrow(query, *args):
            def run():
                conn = self.pool.getconn()
                try:
                    with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                        cursor.execute(query, args)
                        return cursor.fetchone()
                finally:
                    self.pool.putconn(conn)
            return await loop.run_in_executor(None, run)
        
        async def _fetchval(query, *args):
            def run():
                conn = self.pool.getconn()
                try:
                    with conn.cursor() as cursor:
                        cursor.execute(query, args)
                        result = cursor.fetchone()
                        return result[0] if result else None
                finally:
                    self.pool.putconn(conn)
            return await loop.run_in_executor(None, run)
        
        async def _insert_returning_id(query, *args):
            def run():
                conn = self.pool.getconn()
                try:
                    with conn.cursor() as cursor:
                        cursor.execute(query, args)
                        result = cursor.fetchone()
                        conn.commit()
                        return result[0] if result else None
                finally:
                    self.pool.putconn(conn)
            return await loop.run_in_executor(None, run)
        
        self._execute = _exec
        self._fetch = _fetch
        self._fetchrow = _fetchrow
        self._fetchval = _fetchval
        self._insert_returning_id = _insert_returning_id
        
        logger.info("Creating database tables...")
        
        await self._execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                subscription_until TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        await self._execute('''
            CREATE TABLE IF NOT EXISTS accounts (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                phone TEXT NOT NULL,
                session_string TEXT NOT NULL,
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, phone)
            )
        ''')
        
        await self._execute('''
            CREATE TABLE IF NOT EXISTS chats (
                id SERIAL PRIMARY KEY,
                account_id INTEGER REFERENCES accounts(id) ON DELETE CASCADE,
                chat_id BIGINT NOT NULL,
                title TEXT,
                type TEXT
            )
        ''')
        
        await self._execute('''
            CREATE TABLE IF NOT EXISTS promocodes (
                id SERIAL PRIMARY KEY,
                code TEXT UNIQUE NOT NULL,
                type TEXT NOT NULL,
                value INTEGER NOT NULL,
                max_activations INTEGER DEFAULT 1,
                current_activations INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        await self._execute('''
            CREATE TABLE IF NOT EXISTS promo_activations (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                promo_id INTEGER REFERENCES promocodes(id) ON DELETE CASCADE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, promo_id)
            )
        ''')
        
        await self._execute('''
            CREATE TABLE IF NOT EXISTS instructions (
                id SERIAL PRIMARY KEY,
                text TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        logger.info("Database initialization completed successfully")
    
    async def create_user(self, user_id: int):
        await self._execute(
            'INSERT INTO users (user_id) VALUES (%s) ON CONFLICT DO NOTHING',
            user_id
        )
    
    async def has_subscription(self, user_id: int) -> bool:
        row = await self._fetchrow(
            "SELECT subscription_until FROM users WHERE user_id = %s",
            user_id
        )
        if row and row['subscription_until']:
            return row['subscription_until'] > datetime.now()
        return False
    
    async def get_subscription(self, user_id: int) -> Optional[Dict]:
        row = await self._fetchrow(
            "SELECT subscription_until FROM users WHERE user_id = %s",
            user_id
        )
        return dict(row) if row else None
    
    async def add_subscription(self, user_id: int, days: int):
        current = await self._fetchrow(
            "SELECT subscription_until FROM users WHERE user_id = %s",
            user_id
        )
        if current and current['subscription_until'] and current['subscription_until'] > datetime.now():
            new_until = current['subscription_until'] + timedelta(days=days)
        else:
            new_until = datetime.now() + timedelta(days=days)
        
        await self._execute(
            'UPDATE users SET subscription_until = %s WHERE user_id = %s',
            new_until, user_id
        )
    
    async def get_all_users(self) -> List[Dict]:
        rows = await self._fetch("SELECT * FROM users ORDER BY created_at DESC")
        return [dict(r) for r in rows]
    
    async def add_account(self, user_id: int, phone: str, session_string: str) -> bool:
        try:
            await self._execute(
                'INSERT INTO accounts (user_id, phone, session_string) VALUES (%s, %s, %s) '
                'ON CONFLICT (user_id, phone) DO UPDATE SET session_string = %s',
                user_id, phone, session_string, session_string
            )
            return True
        except Exception as e:
            logger.error(f"Error adding account: {e}")
            return False
    
    async def get_user_accounts(self, user_id: int) -> List[Dict]:
        rows = await self._fetch(
            "SELECT id, phone, is_active FROM accounts WHERE user_id = %s ORDER BY created_at DESC",
            user_id
        )
        return [
            {"id": r['id'], "phone": r['phone'], "is_active": r['is_active']}
            for r in rows
        ]
    
    async def get_account_count(self, user_id: int) -> int:
        count = await self._fetchval(
            "SELECT COUNT(*) FROM accounts WHERE user_id = %s",
            user_id
        )
        return count if count else 0
    
    async def get_account_by_id(self, account_id: int) -> Optional[Dict]:
        row = await self._fetchrow(
            "SELECT id, user_id, phone, session_string FROM accounts WHERE id = %s",
            account_id
        )
        if row:
            return {
                "id": row['id'],
                "user_id": row['user_id'],
                "phone": row['phone'],
                "session_string": row['session_string']
            }
        return None
    
    async def delete_account(self, account_id: int):
        await self._execute("DELETE FROM accounts WHERE id = %s", account_id)
    
    async def save_chats(self, account_id: int, chats_data: List[Dict]):
        await self._execute("DELETE FROM chats WHERE account_id = %s", account_id)
        for chat in chats_data:
            await self._execute(
                "INSERT INTO chats (account_id, chat_id, title, type) VALUES (%s, %s, %s, %s)",
                account_id, chat['chat_id'], chat['title'], chat['type']
            )
    
    async def get_chats_paginated(self, account_id: int, page: int, per_page: int = 10) -> tuple:
        offset = (page - 1) * per_page
        total = await self._fetchval(
            "SELECT COUNT(*) FROM chats WHERE account_id = %s",
            account_id
        )
        rows = await self._fetch(
            "SELECT id, chat_id, title, type FROM chats WHERE account_id = %s LIMIT %s OFFSET %s",
            account_id, per_page, offset
        )
        chats = [
            {"id": r['id'], "chat_id": r['chat_id'], "title": r['title'], "type": r['type']}
            for r in rows
        ]
        total_pages = (total + per_page - 1) // per_page if total > 0 else 1
        return chats, total, total_pages
    
    async def get_chat_by_db_id(self, chat_db_id: int) -> Optional[Dict]:
        row = await self._fetchrow(
            "SELECT id, account_id, chat_id, title FROM chats WHERE id = %s",
            chat_db_id
        )
        if row:
            return {
                "id": row['id'],
                "account_id": row['account_id'],
                "chat_id": row['chat_id'],
                "title": row['title']
            }
        return None
    
    async def create_promo(self, code: str, promo_type: str, value: int, max_activations: int) -> int:
        return await self._insert_returning_id(
            'INSERT INTO promocodes (code, type, value, max_activations) VALUES (%s, %s, %s, %s) RETURNING id',
            code, promo_type, value, max_activations
        )
    
    async def get_promo(self, code: str) -> Optional[Dict]:
        row = await self._fetchrow(
            "SELECT * FROM promocodes WHERE code = %s",
            code.upper()
        )
        return dict(row) if row else None
    
    async def activate_promo(self, user_id: int, promo_id: int):
        await self._execute(
            'INSERT INTO promo_activations (user_id, promo_id) VALUES (%s, %s)',
            user_id, promo_id
        )
        await self._execute(
            'UPDATE promocodes SET current_activations = current_activations + 1 WHERE id = %s',
            promo_id
        )
    
    async def has_activated_promo(self, user_id: int, promo_id: int) -> bool:
        row = await self._fetchrow(
            "SELECT id FROM promo_activations WHERE user_id = %s AND promo_id = %s",
            user_id, promo_id
        )
        return row is not None
    
    async def get_instruction(self) -> str:
        row = await self._fetchrow(
            "SELECT text FROM instructions ORDER BY id DESC LIMIT 1"
        )
        if row and row['text']:
            return row['text']
        return "<b>📄 Инструкция</b>\n\nИнструкция пока не добавлена администратором."
    
    async def update_instruction(self, text: str):
        await self._execute("DELETE FROM instructions")
        await self._execute("INSERT INTO instructions (text) VALUES (%s)", text)

# ===== ИНИЦИАЛИЗАЦИЯ БОТА И БАЗЫ ДАННЫХ =====
db = Database()
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())

auth_sessions = {}

# ===== СОСТОЯНИЯ FSM =====

class AccountStates(StatesGroup):
    waiting_for_phone = State()
    waiting_for_code = State()
    waiting_for_2fa = State()

class AdminStates(StatesGroup):
    waiting_for_user_id = State()
    waiting_for_days = State()
    waiting_for_promo_type = State()
    waiting_for_promo_value = State()
    waiting_for_promo_code = State()
    waiting_for_promo_activations = State()
    waiting_for_instruction = State()

class PromoStates(StatesGroup):
    waiting_for_code = State()

class GiftStates(StatesGroup):
    selecting_account = State()
    selecting_gift = State()
    waiting_for_username = State()
    waiting_for_caption = State()

class CommentStates(StatesGroup):
    selecting_account = State()
    selecting_channels = State()
    waiting_for_comment_text = State()

# ===== КЛАВИАТУРЫ БОТА =====

def get_main_menu():
    kb = ReplyKeyboardBuilder()
    kb.button(text="Менеджер аккаунтов", icon_custom_emoji_id=Emoji.people)
    kb.button(text="Функции", icon_custom_emoji_id=Emoji.megaphone)
    kb.button(text="Профиль", icon_custom_emoji_id=Emoji.user_profile)
    kb.button(text="Инструкция", icon_custom_emoji_id=Emoji.instruction)
    kb.button(text="Поддержка", icon_custom_emoji_id=Emoji.support)
    kb.adjust(2, 2, 1)
    return kb.as_markup(resize_keyboard=True)

def get_functions_menu():
    kb = InlineKeyboardBuilder()
    kb.button(text="Отправка подарков", callback_data="gift_menu", icon_custom_emoji_id=Emoji.gift)
    kb.button(text="Автокомментарии", callback_data="comment_menu", icon_custom_emoji_id=Emoji.comment)
    kb.button(text="Назад", callback_data="main_menu", icon_custom_emoji_id=Emoji.back)
    kb.adjust(1)
    return kb.as_markup()

def get_admin_menu():
    kb = InlineKeyboardBuilder()
    kb.button(text="Выдать подписку", callback_data="admin_give_sub", icon_custom_emoji_id=Emoji.crown)
    kb.button(text="Создать промокод", callback_data="admin_create_promo", icon_custom_emoji_id=Emoji.promo)
    kb.button(text="Изменить инструкцию", callback_data="admin_edit_instruction", icon_custom_emoji_id=Emoji.instruction)
    kb.button(text="Список пользователей", callback_data="admin_users", icon_custom_emoji_id=Emoji.people)
    kb.button(text="Назад", callback_data="main_menu", icon_custom_emoji_id=Emoji.back)
    kb.adjust(1)
    return kb.as_markup()

def get_accounts_menu():
    kb = InlineKeyboardBuilder()
    kb.button(text="Добавить аккаунт", callback_data="add_account", icon_custom_emoji_id=Emoji.add_text)
    kb.button(text="Мои аккаунты", callback_data="view_accounts", icon_custom_emoji_id=Emoji.eye)
    kb.button(text="Назад", callback_data="main_menu", icon_custom_emoji_id=Emoji.back)
    kb.adjust(1)
    return kb.as_markup()

def get_accounts_list(accounts: List[Dict]):
    kb = InlineKeyboardBuilder()
    for acc in accounts:
        status_emoji = Emoji.check if acc['is_active'] else Emoji.cross
        kb.button(
            text=acc['phone'],
            callback_data=f"acc_{acc['id']}",
            icon_custom_emoji_id=status_emoji
        )
    kb.button(text="Назад", callback_data="accounts_back", icon_custom_emoji_id=Emoji.back)
    kb.adjust(1)
    return kb.as_markup()

def get_profile_menu():
    kb = InlineKeyboardBuilder()
    kb.button(text="Купить подписку", callback_data="buy_subscription", icon_custom_emoji_id=Emoji.crown)
    kb.button(text="Активировать промокод", callback_data="activate_promo", icon_custom_emoji_id=Emoji.promo)
    kb.button(text="Назад", callback_data="main_menu", icon_custom_emoji_id=Emoji.back)
    kb.adjust(1)
    return kb.as_markup()

def get_subscription_keyboard():
    kb = InlineKeyboardBuilder()
    for key, sub in SUBSCRIPTIONS.items():
        kb.button(
            text=f"{sub['title']} - {sub['price']}₽",
            callback_data=f"sub_{key}"
        )
    kb.button(text="Назад", callback_data="profile", icon_custom_emoji_id=Emoji.back)
    kb.adjust(2)
    return kb.as_markup()

def get_payment_method_keyboard(sub_key: str):
    kb = InlineKeyboardBuilder()
    kb.button(text="USDT", callback_data=f"pay_usdt_{sub_key}", icon_custom_emoji_id=Emoji.money)
    kb.button(text="TON", callback_data=f"pay_ton_{sub_key}", icon_custom_emoji_id=Emoji.money)
    kb.button(text="Рубли", callback_data=f"pay_rub_{sub_key}", icon_custom_emoji_id=Emoji.wallet)
    kb.button(text="Назад", callback_data="buy_subscription", icon_custom_emoji_id=Emoji.back)
    kb.adjust(2)
    return kb.as_markup()

def get_promo_type_keyboard():
    kb = InlineKeyboardBuilder()
    kb.button(text="На скидку (%)", callback_data="promotype_discount", icon_custom_emoji_id=Emoji.money)
    kb.button(text="На подписку (дни)", callback_data="promotype_subscription", icon_custom_emoji_id=Emoji.crown)
    kb.button(text="Назад", callback_data="admin_back", icon_custom_emoji_id=Emoji.back)
    kb.adjust(2)
    return kb.as_markup()

def get_gift_selection_keyboard(page: int = 0):
    kb = InlineKeyboardBuilder()
    
    gift_list = list(GIFTS.items())
    per_page = 8
    total_pages = (len(gift_list) + per_page - 1) // per_page
    
    start = page * per_page
    end = start + per_page
    current_gifts = gift_list[start:end]
    
    for name, gift_data in current_gifts:
        stars_text = f" ({gift_data['stars']}⭐)" if gift_data['stars'] > 0 else ""
        kb.button(
            text=f"{name}{stars_text}",
            callback_data=f"giftselect_{gift_data['id']}"
        )
    
    kb.adjust(1)
    
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(
            text="Назад",
            callback_data=f"giftpage_{page-1}",
            icon_custom_emoji_id=Emoji.back
        ))
    
    nav_buttons.append(InlineKeyboardButton(
        text=f"Стр {page+1}/{total_pages}",
        callback_data="none"
    ))
    
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton(
            text="Далее",
            callback_data=f"giftpage_{page+1}",
            icon_custom_emoji_id=Emoji.download
        ))
    
    if nav_buttons:
        kb.row(*nav_buttons)
    
    kb.button(text="Назад", callback_data="gift_back", icon_custom_emoji_id=Emoji.back)
    return kb.as_markup()

async def get_channels_keyboard(account_id: int, page: int = 1, selected_channels: List[int] = None):
    if selected_channels is None:
        selected_channels = []
    
    chats, total, total_pages = await db.get_chats_paginated(account_id, page)
    
    kb = InlineKeyboardBuilder()
    
    for chat in chats:
        if chat['type'] in ['channel', 'group']:
            is_selected = chat['id'] in selected_channels
            prefix_emoji = Emoji.check if is_selected else Emoji.cross
            kb.button(
                text=chat['title'][:30] if chat['title'] else "Без названия",
                callback_data=f"tgl_ch_{chat['id']}_{page}",
                icon_custom_emoji_id=prefix_emoji
            )
    
    nav_buttons = []
    if page > 1:
        nav_buttons.append(InlineKeyboardButton(
            text="Назад",
            callback_data=f"ch_page_{page-1}",
            icon_custom_emoji_id=Emoji.back
        ))
    
    nav_buttons.append(InlineKeyboardButton(
        text=f"Стр {page}/{total_pages}",
        callback_data="none"
    ))
    
    if page < total_pages:
        nav_buttons.append(InlineKeyboardButton(
            text="Далее",
            callback_data=f"ch_page_{page+1}",
            icon_custom_emoji_id=Emoji.download
        ))
    
    if nav_buttons:
        kb.row(*nav_buttons)
    
    if selected_channels:
        kb.button(
            text=f"Продолжить ({len(selected_channels)} выбрано)",
            callback_data="confirm_channels",
            icon_custom_emoji_id=Emoji.send
        )
    
    kb.button(text="Назад", callback_data="comment_menu", icon_custom_emoji_id=Emoji.back)
    kb.adjust(1)
    return kb.as_markup()

# ===== ОБРАБОТЧИКИ КОМАНД БОТА =====

@dp.message(Command("start"))
async def cmd_start(message: Message):
    await db.create_user(message.from_user.id)
    
    welcome_text = (
        f'<b><tg-emoji emoji-id="{Emoji.bot_emoji}">🤖</tg-emoji> '
        f'Добро пожаловать в Vest Traffer 2!</b>\n\n'
        f'<tg-emoji emoji-id="{Emoji.first_bot}">🤖</tg-emoji> '
        f'<b>Первая часть бота:</b> {FIRST_BOT}\n'
        f'<tg-emoji emoji-id="{Emoji.info}">ℹ️</tg-emoji> '
        f'Все аккаунты синхронизированы между ботами\n\n'
        f'<tg-emoji emoji-id="{Emoji.people}">👥</tg-emoji> '
        f'<b>Менеджер аккаунтов</b> - управление аккаунтами\n'
        f'<tg-emoji emoji-id="{Emoji.megaphone}">📣</tg-emoji> '
        f'<b>Функции</b> - отправка подарков и автокомментарии\n'
        f'<tg-emoji emoji-id="{Emoji.user_profile}">👤</tg-emoji> '
        f'<b>Профиль</b> - подписка и промокоды\n'
        f'<tg-emoji emoji-id="{Emoji.instruction}">📄</tg-emoji> '
        f'<b>Инструкция</b> - руководство по использованию\n'
        f'<tg-emoji emoji-id="{Emoji.support}">📞</tg-emoji> '
        f'<b>Поддержка</b> - помощь и ответы на вопросы'
    )
    
    await message.answer(welcome_text, reply_markup=get_main_menu())

@dp.message(Command("admin"))
async def cmd_admin(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer(
            f'<tg-emoji emoji-id="{Emoji.lock_closed}">🔒</tg-emoji> '
            f'У вас нет доступа к админ-панели.'
        )
        return
    
    await message.answer(
        f'<tg-emoji emoji-id="{Emoji.admin}">🤖</tg-emoji> <b>Админ панель</b>\n\n'
        f'Выберите действие:',
        reply_markup=get_admin_menu()
    )

# ===== ОБРАБОТЧИКИ ТЕКСТОВЫХ КНОПОК ГЛАВНОГО МЕНЮ =====

@dp.message(F.text == "Менеджер аккаунтов")
async def accounts_menu_handler(message: Message):
    if message.from_user.id != ADMIN_ID and not await db.has_subscription(message.from_user.id):
        await message.answer(
            f'<tg-emoji emoji-id="{Emoji.lock_closed}">🔒</tg-emoji> '
            f'<b>Нет доступа!</b>\n\n'
            f'<tg-emoji emoji-id="{Emoji.crown}">👑</tg-emoji> '
            f'Купите подписку в разделе <b>Профиль</b>'
        )
        return
    
    accounts_count = await db.get_account_count(message.from_user.id)
    
    await message.answer(
        f'<tg-emoji emoji-id="{Emoji.people}">👥</tg-emoji> '
        f'<b>Менеджер аккаунтов</b>\n\n'
        f'<tg-emoji emoji-id="{Emoji.profile}">👤</tg-emoji> '
        f'Аккаунтов: {accounts_count}/100\n\n'
        f'<tg-emoji emoji-id="{Emoji.info}">ℹ️</tg-emoji> '
        f'Аккаунты синхронизированы с {FIRST_BOT}',
        reply_markup=get_accounts_menu()
    )

@dp.message(F.text == "Функции")
async def functions_menu_handler(message: Message):
    if message.from_user.id != ADMIN_ID and not await db.has_subscription(message.from_user.id):
        await message.answer(
            f'<tg-emoji emoji-id="{Emoji.lock_closed}">🔒</tg-emoji> '
            f'<b>Нет доступа!</b>\n\n'
            f'<tg-emoji emoji-id="{Emoji.crown}">👑</tg-emoji> '
            f'Купите подписку в разделе <b>Профиль</b>'
        )
        return
    
    await message.answer(
        f'<tg-emoji emoji-id="{Emoji.megaphone}">📣</tg-emoji> <b>Функции</b>\n\n'
        f'<tg-emoji emoji-id="{Emoji.info}">ℹ️</tg-emoji> Выберите нужную функцию:',
        reply_markup=get_functions_menu()
    )

@dp.message(F.text == "Профиль")
async def profile_handler(message: Message):
    has_sub = await db.has_subscription(message.from_user.id)
    sub = await db.get_subscription(message.from_user.id)
    
    sub_text = "Нет"
    if has_sub and sub and sub['subscription_until']:
        days_left = (sub['subscription_until'] - datetime.now()).days
        sub_text = (
            f"Активна до {sub['subscription_until'].strftime('%d.%m.%Y')} "
            f"({days_left} дн.)"
        )
    
    await message.answer(
        f'<tg-emoji emoji-id="{Emoji.user_profile}">👤</tg-emoji> <b>Профиль</b>\n\n'
        f'<tg-emoji emoji-id="{Emoji.tag}">🏷</tg-emoji> '
        f'ID: <code>{message.from_user.id}</code>\n'
        f'<tg-emoji emoji-id="{Emoji.crown}">👑</tg-emoji> '
        f'Подписка: {sub_text}',
        reply_markup=get_profile_menu()
    )

@dp.message(F.text == "Инструкция")
async def instruction_handler(message: Message):
    text = await db.get_instruction()
    
    await message.answer(
        f'<tg-emoji emoji-id="{Emoji.instruction}">📄</tg-emoji> <b>Инструкция</b>\n\n'
        f'{text}\n\n'
        f'<tg-emoji emoji-id="{Emoji.first_bot}">🤖</tg-emoji> '
        f'Первая часть бота: {FIRST_BOT}\n'
        f'<tg-emoji emoji-id="{Emoji.info}">ℹ️</tg-emoji> '
        f'Все аккаунты синхронизированы'
    )

@dp.message(F.text == "Поддержка")
async def support_handler(message: Message):
    await message.answer(
        f'<tg-emoji emoji-id="{Emoji.support}">📞</tg-emoji> <b>Поддержка</b>\n\n'
        f'По всем вопросам обращайтесь: @VestSupport\n\n'
        f'<tg-emoji emoji-id="{Emoji.first_bot}">🤖</tg-emoji> '
        f'Первая часть бота: {FIRST_BOT}'
    )

# ===== CALLBACK ОБРАБОТЧИКИ НАВИГАЦИИ =====

@dp.callback_query(F.data == "main_menu")
async def back_to_main(callback: CallbackQuery):
    await callback.message.delete()
    await callback.message.answer(
        f'<tg-emoji emoji-id="{Emoji.bot_emoji}">🤖</tg-emoji> <b>Главное меню</b>',
        reply_markup=get_main_menu()
    )
    await callback.answer()

@dp.callback_query(F.data == "functions_menu")
async def functions_menu_callback(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID and not await db.has_subscription(callback.from_user.id):
        await callback.answer("Нет доступа. Купите подписку в Профиль", show_alert=True)
        return
    
    await callback.message.edit_text(
        f'<tg-emoji emoji-id="{Emoji.megaphone}">📣</tg-emoji> <b>Функции</b>\n\n'
        f'<tg-emoji emoji-id="{Emoji.info}">ℹ️</tg-emoji> Выберите нужную функцию:',
        reply_markup=get_functions_menu()
    )
    await callback.answer()

# ===== ОБРАБОТЧИКИ ПОДПИСКИ =====

@dp.callback_query(F.data == "buy_subscription")
async def buy_subscription(callback: CallbackQuery):
    await callback.message.edit_text(
        f'<tg-emoji emoji-id="{Emoji.crown}">👑</tg-emoji> <b>Выберите срок подписки:</b>\n\n'
        f'<tg-emoji emoji-id="{Emoji.info}">ℹ️</tg-emoji> '
        f'После оплаты подписка активируется автоматически',
        reply_markup=get_subscription_keyboard()
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("sub_"))
async def select_subscription(callback: CallbackQuery):
    sub_key = callback.data.split("_")[1]
    sub = SUBSCRIPTIONS.get(sub_key)
    
    if not sub:
        await callback.answer("Ошибка: подписка не найдена", show_alert=True)
        return
    
    await callback.message.edit_text(
        f'<tg-emoji emoji-id="{Emoji.money}">💳</tg-emoji> '
        f'<b>Оплата подписки {sub["title"]}</b>\n\n'
        f'<tg-emoji emoji-id="{Emoji.info}">ℹ️</tg-emoji> '
        f'Сумма: {sub["price"]}₽\n'
        f'Выберите способ оплаты:',
        reply_markup=get_payment_method_keyboard(sub_key)
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("pay_"))
async def process_payment(callback: CallbackQuery):
    parts = callback.data.split("_")
    method = parts[1]
    sub_key = parts[2]
    
    sub = SUBSCRIPTIONS.get(sub_key)
    if not sub:
        await callback.answer("Ошибка: подписка не найдена", show_alert=True)
        return
    
    user_id = callback.from_user.id
    
    if method in ("usdt", "ton"):
        if not CRYPTOBOT_TOKEN:
            await callback.answer("CryptoBot не настроен", show_alert=True)
            return
        
        currency = "USDT" if method == "usdt" else "TON"
        rate = USDT_RATE if method == "usdt" else TON_RATE
        crypto_amount = round(sub['price'] / rate, 2)
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://pay.crypt.bot/api/createInvoice",
                headers={"Crypto-Pay-API-Token": CRYPTOBOT_TOKEN},
                json={
                    "asset": currency,
                    "amount": str(crypto_amount),
                    "description": f"Подписка {sub['title']}",
                    "payload": f"{user_id}_{sub_key}"
                }
            ) as resp:
                data = await resp.json()
                
                if data.get("ok"):
                    invoice_url = data["result"]["bot_invoice_url"]
                    
                    kb = InlineKeyboardBuilder()
                    kb.button(text="Оплатить", url=invoice_url)
                    kb.button(
                        text="Назад",
                        callback_data="buy_subscription",
                        icon_custom_emoji_id=Emoji.back
                    )
                    kb.adjust(1)
                    
                    await callback.message.edit_text(
                        f'<tg-emoji emoji-id="{Emoji.money}">💳</tg-emoji> '
                        f'<b>Оплата {currency}</b>\n\n'
                        f'Сумма: {crypto_amount} {currency}\n'
                        f'После оплаты подписка активируется автоматически',
                        reply_markup=kb.as_markup()
                    )
                else:
                    error_msg = data.get('error', 'неизвестная ошибка')
                    await callback.answer(f"Ошибка: {error_msg}", show_alert=True)
    
    elif method == "rub":
        amount = sub['price']
        payment_url = (
            f"https://yoomoney.ru/quickpay/confirm.xml?"
            f"receiver={YOOMONEY_ACCOUNT}&"
            f"quickpay-form=shop&"
            f"targets=Подписка+{sub['title']}&"
            f"sum={amount}&"
            f"label={user_id}_{sub_key}&"
            f"paymentType=AC"
        )
        
        kb = InlineKeyboardBuilder()
        kb.button(text="Оплатить", url=payment_url)
        kb.button(
            text="Назад",
            callback_data="buy_subscription",
            icon_custom_emoji_id=Emoji.back
        )
        kb.adjust(1)
        
        await callback.message.edit_text(
            f'<tg-emoji emoji-id="{Emoji.wallet}">👛</tg-emoji> '
            f'<b>Оплата рублями</b>\n\n'
            f'Сумма: {amount} ₽\n'
            f'Нажмите кнопку для оплаты',
            reply_markup=kb.as_markup()
        )
    
    await callback.answer()

@dp.callback_query(F.data == "profile")
async def profile_callback(callback: CallbackQuery):
    has_sub = await db.has_subscription(callback.from_user.id)
    sub = await db.get_subscription(callback.from_user.id)
    
    sub_text = "Нет"
    if has_sub and sub and sub['subscription_until']:
        days_left = (sub['subscription_until'] - datetime.now()).days
        sub_text = (
            f"Активна до {sub['subscription_until'].strftime('%d.%m.%Y')} "
            f"({days_left} дн.)"
        )
    
    await callback.message.edit_text(
        f'<tg-emoji emoji-id="{Emoji.user_profile}">👤</tg-emoji> <b>Профиль</b>\n\n'
        f'<tg-emoji emoji-id="{Emoji.tag}">🏷</tg-emoji> '
        f'ID: <code>{callback.from_user.id}</code>\n'
        f'<tg-emoji emoji-id="{Emoji.crown}">👑</tg-emoji> '
        f'Подписка: {sub_text}',
        reply_markup=get_profile_menu()
    )
    await callback.answer()

# ===== ОБРАБОТЧИКИ ПРОМОКОДОВ =====

@dp.callback_query(F.data == "activate_promo")
async def activate_promo_start(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        f'<tg-emoji emoji-id="{Emoji.promo}">🎁</tg-emoji> '
        f'<b>Активация промокода</b>\n\n'
        f'<tg-emoji emoji-id="{Emoji.info}">ℹ️</tg-emoji> '
        f'Введите промокод:',
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="Назад",
                callback_data="profile",
                icon_custom_emoji_id=Emoji.back
            )]
        ])
    )
    await state.set_state(PromoStates.waiting_for_code)
    await callback.answer()

@dp.message(PromoStates.waiting_for_code)
async def activate_promo_execute(message: Message, state: FSMContext):
    code = message.text.strip().upper()
    promo = await db.get_promo(code)
    
    if not promo:
        await message.answer(
            f'<tg-emoji emoji-id="{Emoji.cross}">❌</tg-emoji> '
            f'<b>Промокод не найден!</b>\n\n'
            f'Проверьте правильность ввода и попробуйте снова.'
        )
        await state.clear()
        return
    
    if promo['current_activations'] >= promo['max_activations']:
        await message.answer(
            f'<tg-emoji emoji-id="{Emoji.cross}">❌</tg-emoji> '
            f'<b>Промокод закончился!</b>\n\n'
            f'Все активации уже использованы.'
        )
        await state.clear()
        return
    
    if await db.has_activated_promo(message.from_user.id, promo['id']):
        await message.answer(
            f'<tg-emoji emoji-id="{Emoji.cross}">❌</tg-emoji> '
            f'<b>Вы уже активировали этот промокод!</b>\n\n'
            f'Повторная активация невозможна.'
        )
        await state.clear()
        return
    
    await db.activate_promo(message.from_user.id, promo['id'])
    
    if promo['type'] == 'subscription':
        await db.add_subscription(message.from_user.id, promo['value'])
        await message.answer(
            f'<tg-emoji emoji-id="{Emoji.check}">✅</tg-emoji> '
            f'<b>Промокод активирован!</b>\n\n'
            f'Подписка продлена на {promo["value"]} дней.'
        )
    elif promo['type'] == 'discount':
        await message.answer(
            f'<tg-emoji emoji-id="{Emoji.check}">✅</tg-emoji> '
            f'<b>Промокод активирован!</b>\n\n'
            f'Скидка {promo["value"]}%\n'
            f'Обратитесь в поддержку для применения скидки.'
        )
    
    await state.clear()

# ===== АДМИН ПАНЕЛЬ =====

@dp.callback_query(F.data == "admin_give_sub")
async def admin_give_sub_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Нет доступа", show_alert=True)
        return
    
    await callback.message.edit_text(
        f'<tg-emoji emoji-id="{Emoji.admin}">🤖</tg-emoji> '
        f'<b>Выдача подписки</b>\n\n'
        f'<tg-emoji emoji-id="{Emoji.info}">ℹ️</tg-emoji> '
        f'Введите ID пользователя:',
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="Назад",
                callback_data="admin_back",
                icon_custom_emoji_id=Emoji.back
            )]
        ])
    )
    await state.set_state(AdminStates.waiting_for_user_id)
    await callback.answer()

@dp.callback_query(F.data == "admin_users")
async def admin_users_list(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    
    users = await db.get_all_users()
    
    kb = InlineKeyboardBuilder()
    for u in users[:20]:
        has_sub = (
            u.get('subscription_until') and
            u['subscription_until'] > datetime.now()
        )
        st = "✅" if has_sub else "❌"
        kb.button(
            text=f"{st} {u['user_id']}",
            callback_data=f"admin_user_{u['user_id']}"
        )
    kb.button(
        text="Назад",
        callback_data="admin_back",
        icon_custom_emoji_id=Emoji.back
    )
    kb.adjust(1)
    
    await callback.message.edit_text(
        f'<tg-emoji emoji-id="{Emoji.people}">👥</tg-emoji> '
        f'<b>Список пользователей</b>\n\n'
        f'Всего зарегистрировано: {len(users)}',
        reply_markup=kb.as_markup()
    )
    await callback.answer()

@dp.callback_query(F.data == "admin_back")
async def admin_back(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    
    await callback.message.edit_text(
        f'<tg-emoji emoji-id="{Emoji.admin}">🤖</tg-emoji> '
        f'<b>Админ панель</b>\n\n'
        f'Выберите действие:',
        reply_markup=get_admin_menu()
    )
    await callback.answer()

@dp.message(AdminStates.waiting_for_user_id)
async def admin_process_user_id(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        await state.clear()
        return
    
    try:
        user_id = int(message.text)
        await state.update_data(give_user_id=user_id)
        
        kb = InlineKeyboardBuilder()
        for key, sub in SUBSCRIPTIONS.items():
            kb.button(text=sub['title'], callback_data=f"give_sub_{key}")
        kb.button(
            text="Назад",
            callback_data="admin_back",
            icon_custom_emoji_id=Emoji.back
        )
        kb.adjust(2)
        
        await message.answer(
            f'<tg-emoji emoji-id="{Emoji.crown}">👑</tg-emoji> '
            f'<b>Выберите срок подписки</b>\n\n'
            f'Для пользователя: <code>{user_id}</code>',
            reply_markup=kb.as_markup()
        )
        await state.set_state(AdminStates.waiting_for_days)
    except ValueError:
        await message.answer(
            f'<tg-emoji emoji-id="{Emoji.cross}">❌</tg-emoji> '
            f'Введите корректный ID пользователя'
        )

@dp.callback_query(F.data.startswith("give_sub_"), AdminStates.waiting_for_days)
async def admin_give_sub_finish(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        return
    
    sub_key = callback.data.split("_")[-1]
    state_data = await state.get_data()
    user_id = state_data.get('give_user_id')
    
    if not user_id:
        await callback.answer("Ошибка: пользователь не найден", show_alert=True)
        return
    
    sub = SUBSCRIPTIONS.get(sub_key)
    if not sub:
        await callback.answer("Ошибка: подписка не найдена", show_alert=True)
        return
    
    await db.add_subscription(user_id, sub['days'])
    
    await callback.message.edit_text(
        f'<tg-emoji emoji-id="{Emoji.check}">✅</tg-emoji> '
        f'<b>Подписка успешно выдана!</b>\n\n'
        f'Пользователь: <code>{user_id}</code>\n'
        f'Срок: {sub["title"]}'
    )
    await state.clear()
    await callback.answer()

# ===== СОЗДАНИЕ ПРОМОКОДА (АДМИН) =====

@dp.callback_query(F.data == "admin_create_promo")
async def admin_create_promo_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        return
    
    await callback.message.edit_text(
        f'<tg-emoji emoji-id="{Emoji.promo}">🎁</tg-emoji> '
        f'<b>Создание промокода</b>\n\n'
        f'<tg-emoji emoji-id="{Emoji.info}">ℹ️</tg-emoji> '
        f'Выберите тип промокода:',
        reply_markup=get_promo_type_keyboard()
    )
    await state.set_state(AdminStates.waiting_for_promo_type)
    await callback.answer()

@dp.callback_query(F.data.startswith("promotype_"), AdminStates.waiting_for_promo_type)
async def admin_set_promo_type(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        return
    
    promo_type = callback.data.split("_")[1]
    await state.update_data(promo_type=promo_type)
    
    type_text = "скидки (%)" if promo_type == 'discount' else "подписки (дни)"
    
    await callback.message.edit_text(
        f'<tg-emoji emoji-id="{Emoji.promo}">🎁</tg-emoji> '
        f'<b>Создание промокода</b>\n\n'
        f'<tg-emoji emoji-id="{Emoji.info}">ℹ️</tg-emoji> '
        f'Введите значение для {type_text}:',
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="Назад",
                callback_data="admin_create_promo",
                icon_custom_emoji_id=Emoji.back
            )]
        ])
    )
    await state.set_state(AdminStates.waiting_for_promo_value)
    await callback.answer()

@dp.message(AdminStates.waiting_for_promo_value)
async def admin_set_promo_value(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        await state.clear()
        return
    
    try:
        value = int(message.text)
        if value < 1:
            await message.answer(
                f'<tg-emoji emoji-id="{Emoji.cross}">❌</tg-emoji> '
                f'Значение должно быть больше 0'
            )
            return
        
        await state.update_data(promo_value=value)
        await message.answer(
            f'<tg-emoji emoji-id="{Emoji.write}">✍️</tg-emoji> '
            f'<b>Введите промокод (одно слово):</b>'
        )
        await state.set_state(AdminStates.waiting_for_promo_code)
    except ValueError:
        await message.answer(
            f'<tg-emoji emoji-id="{Emoji.cross}">❌</tg-emoji> '
            f'Введите число'
        )

@dp.message(AdminStates.waiting_for_promo_code)
async def admin_set_promo_code(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        await state.clear()
        return
    
    code = message.text.strip().upper()
    await state.update_data(promo_code=code)
    
    await message.answer(
        f'<tg-emoji emoji-id="{Emoji.box}">📦</tg-emoji> '
        f'<b>Введите количество активаций:</b>'
    )
    await state.set_state(AdminStates.waiting_for_promo_activations)

@dp.message(AdminStates.waiting_for_promo_activations)
async def admin_create_promo_finish(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        await state.clear()
        return
    
    try:
        activations = int(message.text)
        if activations < 1:
            await message.answer(
                f'<tg-emoji emoji-id="{Emoji.cross}">❌</tg-emoji> '
                f'Минимум 1 активация'
            )
            return
        
        state_data = await state.get_data()
        await db.create_promo(
            state_data['promo_code'],
            state_data['promo_type'],
            state_data['promo_value'],
            activations
        )
        
        type_text = "Скидка" if state_data['promo_type'] == 'discount' else "Подписка"
        value_text = (
            f"{state_data['promo_value']}%"
            if state_data['promo_type'] == 'discount'
            else f"{state_data['promo_value']} дн."
        )
        
        await message.answer(
            f'<tg-emoji emoji-id="{Emoji.check}">✅</tg-emoji> '
            f'<b>Промокод успешно создан!</b>\n\n'
            f'<tg-emoji emoji-id="{Emoji.tag}">🏷</tg-emoji> '
            f'Код: <code>{state_data["promo_code"]}</code>\n'
            f'<tg-emoji emoji-id="{Emoji.info}">ℹ️</tg-emoji> '
            f'Тип: {type_text}\n'
            f'<tg-emoji emoji-id="{Emoji.info}">ℹ️</tg-emoji> '
            f'Значение: {value_text}\n'
            f'<tg-emoji emoji-id="{Emoji.box}">📦</tg-emoji> '
            f'Количество активаций: {activations}'
        )
        await state.clear()
    except ValueError:
        await message.answer(
            f'<tg-emoji emoji-id="{Emoji.cross}">❌</tg-emoji> '
            f'Введите число'
        )

# ===== ИЗМЕНЕНИЕ ИНСТРУКЦИИ (АДМИН) =====

@dp.callback_query(F.data == "admin_edit_instruction")
async def admin_edit_instruction_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        return
    
    current_text = await db.get_instruction()
    
    await callback.message.edit_text(
        f'<tg-emoji emoji-id="{Emoji.instruction}">📄</tg-emoji> '
        f'<b>Редактирование инструкции</b>\n\n'
        f'<tg-emoji emoji-id="{Emoji.info}">ℹ️</tg-emoji> '
        f'Текущий текст:\n{current_text}\n\n'
        f'<tg-emoji emoji-id="{Emoji.write}">✍️</tg-emoji> '
        f'Отправьте новый текст (поддерживается HTML):',
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="Назад",
                callback_data="admin_back",
                icon_custom_emoji_id=Emoji.back
            )]
        ])
    )
    await state.set_state(AdminStates.waiting_for_instruction)
    await callback.answer()

@dp.message(AdminStates.waiting_for_instruction)
async def admin_update_instruction(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        await state.clear()
        return
    
    await db.update_instruction(message.html_text)
    await message.answer(
        f'<tg-emoji emoji-id="{Emoji.check}">✅</tg-emoji> '
        f'<b>Инструкция успешно обновлена!</b>'
    )
    await state.clear()

# ===== ДОБАВЛЕНИЕ АККАУНТА TELEGRAM =====

@dp.callback_query(F.data == "add_account")
async def add_account_start(callback: CallbackQuery, state: FSMContext):
    accounts_count = await db.get_account_count(callback.from_user.id)
    if accounts_count >= 100:
        await callback.answer("Достигнут лимит аккаунтов (100)", show_alert=True)
        return
    
    await callback.message.edit_text(
        f'<tg-emoji emoji-id="{Emoji.add_text}">🔡</tg-emoji> '
        f'<b>Добавление аккаунта</b>\n\n'
        f'<tg-emoji emoji-id="{Emoji.info}">ℹ️</tg-emoji> '
        f'Отправьте номер телефона в формате:\n'
        f'<code>+79991234567</code>'
    )
    await state.set_state(AccountStates.waiting_for_phone)
    await callback.answer()

@dp.message(AccountStates.waiting_for_phone)
async def process_phone(message: Message, state: FSMContext):
    phone = message.text.strip()
    
    client = TelegramClient(StringSession(), API_ID, API_HASH)
    await client.connect()
    
    try:
        await client.send_code_request(phone)
    except PhoneNumberInvalidError:
        await message.answer(
            f'<tg-emoji emoji-id="{Emoji.cross}">❌</tg-emoji> '
            f'Неверный формат номера. Попробуйте снова.'
        )
        await client.disconnect()
        return
    except Exception as e:
        await message.answer(
            f'<tg-emoji emoji-id="{Emoji.cross}">❌</tg-emoji> '
            f'Ошибка: {str(e)}'
        )
        await client.disconnect()
        return
    
    auth_sessions[message.from_user.id] = {
        'client': client,
        'phone': phone
    }
    
    await message.answer(
        f'<tg-emoji emoji-id="{Emoji.check}">✅</tg-emoji> '
        f'<b>Код отправлен!</b>\n\n'
        f'<tg-emoji emoji-id="{Emoji.info}">ℹ️</tg-emoji> '
        f'Введите код из Telegram:'
    )
    await state.set_state(AccountStates.waiting_for_code)

@dp.message(AccountStates.waiting_for_code)
async def process_code(message: Message, state: FSMContext):
    if message.from_user.id not in auth_sessions:
        await message.answer(
            f'<tg-emoji emoji-id="{Emoji.cross}">❌</tg-emoji> '
            f'Сессия истекла. Начните заново.'
        )
        await state.clear()
        return
    
    session = auth_sessions[message.from_user.id]
    client = session['client']
    phone = session['phone']
    code = message.text.strip()
    
    try:
        await client.sign_in(phone, code)
    except SessionPasswordNeededError:
        await message.answer(
            f'<tg-emoji emoji-id="{Emoji.lock_closed}">🔒</tg-emoji> '
            f'<b>Требуется 2FA пароль</b>\n\n'
            f'<tg-emoji emoji-id="{Emoji.info}">ℹ️</tg-emoji> '
            f'Введите пароль:'
        )
        await state.set_state(AccountStates.waiting_for_2fa)
        return
    except (PhoneCodeInvalidError, PhoneCodeExpiredError):
        await message.answer(
            f'<tg-emoji emoji-id="{Emoji.cross}">❌</tg-emoji> '
            f'Неверный код. Попробуйте снова.'
        )
        await state.clear()
        await client.disconnect()
        if message.from_user.id in auth_sessions:
            del auth_sessions[message.from_user.id]
        return
    except Exception as e:
        await message.answer(
            f'<tg-emoji emoji-id="{Emoji.cross}">❌</tg-emoji> '
            f'Ошибка: {str(e)}'
        )
        await state.clear()
        await client.disconnect()
        if message.from_user.id in auth_sessions:
            del auth_sessions[message.from_user.id]
        return
    
    await complete_auth(message, state, client, phone)

@dp.message(AccountStates.waiting_for_2fa)
async def process_2fa(message: Message, state: FSMContext):
    if message.from_user.id not in auth_sessions:
        await message.answer(
            f'<tg-emoji emoji-id="{Emoji.cross}">❌</tg-emoji> '
            f'Сессия истекла. Начните заново.'
        )
        await state.clear()
        return
    
    session = auth_sessions[message.from_user.id]
    client = session['client']
    phone = session['phone']
    password = message.text.strip()
    
    try:
        await client.sign_in(password=password)
    except Exception as e:
        await message.answer(
            f'<tg-emoji emoji-id="{Emoji.cross}">❌</tg-emoji> '
            f'Неверный пароль. Попробуйте снова.'
        )
        return
    
    await complete_auth(message, state, client, phone)

async def complete_auth(message: Message, state: FSMContext, client: TelegramClient, phone: str):
    try:
        session_string = client.session.save()
        
        if await db.add_account(message.from_user.id, phone, session_string):
            await message.answer(
                f'<tg-emoji emoji-id="{Emoji.check}">✅</tg-emoji> '
                f'<b>Аккаунт успешно добавлен!</b>\n'
                f'<tg-emoji emoji-id="{Emoji.profile}">👤</tg-emoji> '
                f'Телефон: {phone}',
                reply_markup=get_accounts_menu()
            )
        else:
            await message.answer(
                f'<tg-emoji emoji-id="{Emoji.cross}">❌</tg-emoji> '
                f'Ошибка при сохранении аккаунта'
            )
    except Exception as e:
        await message.answer(
            f'<tg-emoji emoji-id="{Emoji.cross}">❌</tg-emoji> '
            f'Ошибка: {str(e)}'
        )
    finally:
        await client.disconnect()
        if message.from_user.id in auth_sessions:
            del auth_sessions[message.from_user.id]
        await state.clear()

# ===== ПРОСМОТР АККАУНТОВ =====

@dp.callback_query(F.data == "view_accounts")
async def view_accounts(callback: CallbackQuery):
    accounts = await db.get_user_accounts(callback.from_user.id)
    if not accounts:
        await callback.answer("У вас нет добавленных аккаунтов", show_alert=True)
        return
    
    await callback.message.edit_text(
        f'<tg-emoji emoji-id="{Emoji.people}">👥</tg-emoji> '
        f'<b>Ваши аккаунты</b>\n'
        f'<tg-emoji emoji-id="{Emoji.info}">ℹ️</tg-emoji> '
        f'Нажмите на аккаунт для управления',
        reply_markup=get_accounts_list(accounts)
    )
    await callback.answer()

@dp.callback_query(F.data == "accounts_back")
async def accounts_back(callback: CallbackQuery):
    accounts_count = await db.get_account_count(callback.from_user.id)
    await callback.message.edit_text(
        f'<tg-emoji emoji-id="{Emoji.people}">👥</tg-emoji> '
        f'<b>Менеджер аккаунтов</b>\n\n'
        f'<tg-emoji emoji-id="{Emoji.profile}">👤</tg-emoji> '
        f'Аккаунтов: {accounts_count}/100\n\n'
        f'<tg-emoji emoji-id="{Emoji.info}">ℹ️</tg-emoji> '
        f'Аккаунты синхронизированы с {FIRST_BOT}',
        reply_markup=get_accounts_menu()
    )
    await callback.answer()

# ===== УПРАВЛЕНИЕ ОТДЕЛЬНЫМ АККАУНТОМ =====

@dp.callback_query(F.data.startswith("acc_"))
async def account_details(callback: CallbackQuery):
    acc_id = int(callback.data.split("_")[1])
    account = await db.get_account_by_id(acc_id)
    
    if not account or account['user_id'] != callback.from_user.id:
        await callback.answer("Аккаунт не найден", show_alert=True)
        return
    
    kb = InlineKeyboardBuilder()
    kb.button(
        text="Загрузить чаты",
        callback_data=f"loadchats_{acc_id}",
        icon_custom_emoji_id=Emoji.download
    )
    kb.button(
        text="Удалить аккаунт",
        callback_data=f"delete_acc_{acc_id}",
        icon_custom_emoji_id=Emoji.trash
    )
    kb.button(
        text="Назад к аккаунтам",
        callback_data="view_accounts",
        icon_custom_emoji_id=Emoji.back
    )
    kb.adjust(1)
    
    await callback.message.edit_text(
        f'<tg-emoji emoji-id="{Emoji.profile}">👤</tg-emoji> <b>Управление аккаунтом</b>\n\n'
        f'<tg-emoji emoji-id="{Emoji.people}">👥</tg-emoji> Телефон: {account["phone"]}\n'
        f'<tg-emoji emoji-id="{Emoji.info}">ℹ️</tg-emoji> ID: <code>{acc_id}</code>\n\n'
        f'<tg-emoji emoji-id="{Emoji.info}">ℹ️</tg-emoji> Выберите действие:',
        reply_markup=kb.as_markup()
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("delete_acc_"))
async def delete_account_handler(callback: CallbackQuery):
    acc_id = int(callback.data.split("_")[-1])
    account = await db.get_account_by_id(acc_id)
    
    if not account or account['user_id'] != callback.from_user.id:
        await callback.answer("Аккаунт не найден", show_alert=True)
        return
    
    kb = InlineKeyboardBuilder()
    kb.button(
        text="Да, удалить",
        callback_data=f"confirm_delete_{acc_id}",
        icon_custom_emoji_id=Emoji.trash
    )
    kb.button(
        text="Нет, отмена",
        callback_data=f"acc_{acc_id}",
        icon_custom_emoji_id=Emoji.back
    )
    kb.adjust(2)
    
    await callback.message.edit_text(
        f'<tg-emoji emoji-id="{Emoji.cross}">❌</tg-emoji> '
        f'<b>Удалить аккаунт {account["phone"]}?</b>\n\n'
        f'Это действие нельзя отменить!',
        reply_markup=kb.as_markup()
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("confirm_delete_"))
async def confirm_delete_account(callback: CallbackQuery):
    acc_id = int(callback.data.split("_")[-1])
    account = await db.get_account_by_id(acc_id)
    
    if not account or account['user_id'] != callback.from_user.id:
        await callback.answer("Аккаунт не найден", show_alert=True)
        return
    
    await db.delete_account(acc_id)
    
    await callback.message.edit_text(
        f'<tg-emoji emoji-id="{Emoji.check}">✅</tg-emoji> '
        f'<b>Аккаунт {account["phone"]} успешно удален!</b>'
    )
    
    await asyncio.sleep(2)
    accounts = await db.get_user_accounts(callback.from_user.id)
    if accounts:
        await callback.message.edit_text(
            f'<tg-emoji emoji-id="{Emoji.people}">👥</tg-emoji> '
            f'<b>Ваши аккаунты</b>\n'
            f'<tg-emoji emoji-id="{Emoji.info}">ℹ️</tg-emoji> '
            f'Нажмите на аккаунт для управления',
            reply_markup=get_accounts_list(accounts)
        )
    else:
        await callback.message.edit_text(
            f'<tg-emoji emoji-id="{Emoji.people}">👥</tg-emoji> '
            f'<b>Менеджер аккаунтов</b>\n\n'
            f'<tg-emoji emoji-id="{Emoji.profile}">👤</tg-emoji> '
            f'Аккаунтов: 0/100\n\n'
            f'<tg-emoji emoji-id="{Emoji.info}">ℹ️</tg-emoji> '
            f'Аккаунты синхронизированы с {FIRST_BOT}',
            reply_markup=get_accounts_menu()
        )
    await callback.answer()

# ===== ЗАГРУЗКА ЧАТОВ (КАНАЛОВ) ДЛЯ АККАУНТА =====

@dp.callback_query(F.data.startswith("loadchats_"))
async def load_chats(callback: CallbackQuery):
    acc_id = int(callback.data.split("_")[1])
    account = await db.get_account_by_id(acc_id)
    
    if not account:
        await callback.answer("Аккаунт не найден", show_alert=True)
        return
    
    await callback.message.edit_text(
        f'<tg-emoji emoji-id="{Emoji.loading}">🔄</tg-emoji> '
        f'<b>Загрузка чатов...</b>\n\n'
        f'Пожалуйста, подождите. Это может занять некоторое время.'
    )
    await callback.answer()
    
    try:
        client = TelegramClient(
            StringSession(account['session_string']),
            API_ID, API_HASH
        )
        await client.connect()
        
        if not await client.is_user_authorized():
            await callback.message.edit_text(
                f'<tg-emoji emoji-id="{Emoji.cross}">❌</tg-emoji> '
                f'Аккаунт не авторизован'
            )
            await client.disconnect()
            return
        
        dialogs = await client.get_dialogs(limit=200)
        chats_data = []
        
        for dialog in dialogs:
            if dialog.is_channel or dialog.is_group:
                chat_type = "channel" if dialog.is_channel else "group"
                chats_data.append({
                    'chat_id': dialog.id,
                    'title': dialog.name[:100] if dialog.name else "Без названия",
                    'type': chat_type
                })
        
        await db.save_chats(acc_id, chats_data)
        
        await callback.message.edit_text(
            f'<tg-emoji emoji-id="{Emoji.check}">✅</tg-emoji> '
            f'<b>Чаты загружены!</b>\n\n'
            f'Каналов и групп: {len(chats_data)}\n\n'
            f'Теперь вы можете использовать автокомментарии.',
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text="Назад к аккаунту",
                    callback_data=f"acc_{acc_id}",
                    icon_custom_emoji_id=Emoji.back
                )]
            ])
        )
        
    except Exception as e:
        logger.error(f"Error loading chats: {e}")
        await callback.message.edit_text(
            f'<tg-emoji emoji-id="{Emoji.cross}">❌</tg-emoji> '
            f'Ошибка при загрузке чатов:\n{str(e)[:200]}'
        )
    finally:
        await client.disconnect()

# ===== ОТПРАВКА ПОДАРКОВ =====

@dp.callback_query(F.data == "gift_menu")
async def gift_menu_handler(callback: CallbackQuery, state: FSMContext):
    accounts = await db.get_user_accounts(callback.from_user.id)
    if not accounts:
        await callback.answer("Нет аккаунтов", show_alert=True)
        return
    
    kb = InlineKeyboardBuilder()
    for acc in accounts:
        kb.button(
            text=acc['phone'],
            callback_data=f"giftacc_{acc['id']}",
            icon_custom_emoji_id=Emoji.profile
        )
    kb.button(
        text="Назад",
        callback_data="functions_menu",
        icon_custom_emoji_id=Emoji.back
    )
    kb.adjust(1)
    
    await callback.message.edit_text(
        f'<tg-emoji emoji-id="{Emoji.gift}">🎁</tg-emoji> '
        f'<b>Отправка подарков</b>\n\n'
        f'<tg-emoji emoji-id="{Emoji.info}">ℹ️</tg-emoji> '
        f'Выберите аккаунт для отправки подарка.',
        reply_markup=kb.as_markup()
    )
    await state.set_state(GiftStates.selecting_account)
    await callback.answer()

@dp.callback_query(F.data == "gift_back")
async def gift_back(callback: CallbackQuery):
    await callback.message.edit_text(
        f'<tg-emoji emoji-id="{Emoji.megaphone}">📣</tg-emoji> <b>Функции</b>\n\n'
        f'<tg-emoji emoji-id="{Emoji.info}">ℹ️</tg-emoji> Выберите нужную функцию:',
        reply_markup=get_functions_menu()
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("giftacc_"), GiftStates.selecting_account)
async def gift_select_account(callback: CallbackQuery, state: FSMContext):
    acc_id = int(callback.data.split("_")[1])
    account = await db.get_account_by_id(acc_id)
    
    if not account:
        await callback.answer("Аккаунт не найден", show_alert=True)
        return
    
    await state.update_data(gift_acc_id=acc_id)
    
    await callback.message.edit_text(
        f'<tg-emoji emoji-id="{Emoji.gift}">🎁</tg-emoji> '
        f'<b>Выберите подарок:</b>\n\n'
        f'<tg-emoji emoji-id="{Emoji.star}">⭐</tg-emoji> '
        f'Некоторые подарки требуют звёзды',
        reply_markup=get_gift_selection_keyboard(0)
    )
    await state.set_state(GiftStates.selecting_gift)
    await callback.answer()

@dp.callback_query(F.data.startswith("giftpage_"), GiftStates.selecting_gift)
async def gift_page_handler(callback: CallbackQuery):
    page = int(callback.data.split("_")[1])
    await callback.message.edit_reply_markup(reply_markup=get_gift_selection_keyboard(page))
    await callback.answer()

@dp.callback_query(F.data.startswith("giftselect_"), GiftStates.selecting_gift)
async def gift_selected(callback: CallbackQuery, state: FSMContext):
    gift_id = int(callback.data.split("_")[1])
    await state.update_data(gift_id=gift_id)
    
    gift_name = None
    gift_stars = 0
    for name, data in GIFTS.items():
        if data['id'] == gift_id:
            gift_name = name
            gift_stars = data['stars']
            break
    
    stars_info = f" (требуется {gift_stars}⭐)" if gift_stars > 0 else ""
    
    await callback.message.edit_text(
        f'<tg-emoji emoji-id="{Emoji.gift}">🎁</tg-emoji> '
        f'<b>Выбран подарок: {gift_name}{stars_info}</b>\n\n'
        f'<tg-emoji emoji-id="{Emoji.write}">✍️</tg-emoji> '
        f'<b>Введите юзернейм получателя:</b>\n\n'
        f'<tg-emoji emoji-id="{Emoji.info}">ℹ️</tg-emoji> '
        f'Пример: <code>@username</code> или <code>username</code>',
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="Назад к выбору подарка",
                callback_data="gift_back_to_selection",
                icon_custom_emoji_id=Emoji.back
            )]
        ])
    )
    await state.set_state(GiftStates.waiting_for_username)
    await callback.answer()

@dp.callback_query(F.data == "gift_back_to_selection", GiftStates.waiting_for_username)
async def gift_back_to_selection(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        f'<tg-emoji emoji-id="{Emoji.gift}">🎁</tg-emoji> '
        f'<b>Выберите подарок:</b>\n\n'
        f'<tg-emoji emoji-id="{Emoji.star}">⭐</tg-emoji> '
        f'Некоторые подарки требуют звёзды',
        reply_markup=get_gift_selection_keyboard(0)
    )
    await state.set_state(GiftStates.selecting_gift)
    await callback.answer()

@dp.message(GiftStates.waiting_for_username)
async def gift_process_username(message: Message, state: FSMContext):
    username = message.text.strip().replace('@', '').strip()
    
    if not username:
        await message.answer(
            f'<tg-emoji emoji-id="{Emoji.cross}">❌</tg-emoji> '
            f'Введите корректный юзернейм'
        )
        return
    
    await state.update_data(gift_username=username)
    
    await message.answer(
        f'<tg-emoji emoji-id="{Emoji.write}">✍️</tg-emoji> '
        f'<b>Введите подпись к подарку:</b>\n\n'
        f'<tg-emoji emoji-id="{Emoji.info}">ℹ️</tg-emoji> '
        f'Этот текст будет виден получателю.'
    )
    await state.set_state(GiftStates.waiting_for_caption)

@dp.message(GiftStates.waiting_for_caption)
async def gift_send(message: Message, state: FSMContext):
    caption = message.html_text
    state_data = await state.get_data()
    acc_id = state_data.get('gift_acc_id')
    gift_id = state_data.get('gift_id')
    username = state_data.get('gift_username')
    
    if not acc_id or not gift_id or not username:
        await message.answer(
            f'<tg-emoji emoji-id="{Emoji.cross}">❌</tg-emoji> '
            f'<b>Ошибка данных!</b>\n\n'
            f'Пожалуйста, начните заново.'
        )
        await state.clear()
        return
    
    account = await db.get_account_by_id(acc_id)
    if not account:
        await message.answer(
            f'<tg-emoji emoji-id="{Emoji.cross}">❌</tg-emoji> '
            f'Аккаунт не найден'
        )
        await state.clear()
        return
    
    gift_name = "Подарок"
    for name, data in GIFTS.items():
        if data['id'] == gift_id:
            gift_name = name
            break
    
    status_msg = await message.answer(
        f'<tg-emoji emoji-id="{Emoji.loading}">🔄</tg-emoji> '
        f'<b>Отправляем подарок...</b>\n\n'
        f'<tg-emoji emoji-id="{Emoji.gift}">🎁</tg-emoji> Подарок: {gift_name}\n'
        f'<tg-emoji emoji-id="{Emoji.people}">👥</tg-emoji> Получатель: @{username}\n'
        f'<tg-emoji emoji-id="{Emoji.profile}">👤</tg-emoji> От аккаунта: {account["phone"]}'
    )
    
    try:
        client = TelegramClient(
            StringSession(account['session_string']),
            API_ID, API_HASH
        )
        await client.connect()
        
        if not await client.is_user_authorized():
            await status_msg.edit_text(
                f'<tg-emoji emoji-id="{Emoji.cross}">❌</tg-emoji> '
                f'Аккаунт не авторизован'
            )
            await client.disconnect()
            await state.clear()
            return
        
        try:
            receiver = await client.get_entity(username)
        except Exception as e:
            await status_msg.edit_text(
                f'<tg-emoji emoji-id="{Emoji.cross}">❌</tg-emoji> '
                f'<b>Пользователь @{username} не найден!</b>\n\n'
                f'Проверьте правильность юзернейма.'
            )
            await client.disconnect()
            await state.clear()
            return
        
        # Пробуем отправить подарок
        try:
            from telethon.tl.functions.payments import SendStarGiftRequest
            result = await client(SendStarGiftRequest(
                user_id=receiver,
                gift_id=gift_id,
                message=caption if caption else "",
                hide_my_name=False
            ))
        except (ImportError, TypeError, AttributeError):
            # Fallback - пробуем через invoke с правильной сигнатурой
            try:
                result = await client.invoke(
                    SendStarGiftRequest(
                        user_id=receiver,
                        gift_id=gift_id,
                        message=caption if caption else "",
                        hide_my_name=False
                    )
                )
            except:
                # Последняя попытка - через прямую передачу параметров
                from telethon.tl.custom import TLRequest
                result = await client.invoke(TLRequest(
                    'payments.sendStarGift',
                    user_id=receiver,
                    gift_id=gift_id,
                    message=caption if caption else "",
                    hide_my_name=False
                ))
        
        await status_msg.edit_text(
            f'<tg-emoji emoji-id="{Emoji.check}">✅</tg-emoji> '
            f'<b>Подарок успешно отправлен!</b>\n\n'
            f'<tg-emoji emoji-id="{Emoji.gift}">🎁</tg-emoji> Подарок: {gift_name}\n'
            f'<tg-emoji emoji-id="{Emoji.people}">👥</tg-emoji> Получатель: @{username}\n'
            f'<tg-emoji emoji-id="{Emoji.profile}">👤</tg-emoji> От аккаунта: {account["phone"]}'
        )
        
    except Exception as e:
        logger.error(f"Gift sending error: {e}")
        await status_msg.edit_text(
            f'<tg-emoji emoji-id="{Emoji.cross}">❌</tg-emoji> '
            f'<b>Ошибка при отправке подарка:</b>\n\n'
            f'{str(e)[:300]}\n\n'
            f'Возможные причины:\n'
            f'- Недостаточно звёзд на аккаунте\n'
            f'- Пользователь не принимает подарки\n'
            f'- Аккаунт не имеет Premium\n'
            f'- API запрос не поддерживается в этой версии Telethon'
        )
    finally:
        try:
            await client.disconnect()
        except:
            pass
        await state.clear()

# ===== АВТОКОММЕНТАРИИ =====

@dp.callback_query(F.data == "comment_menu")
async def comment_menu_handler(callback: CallbackQuery, state: FSMContext):
    accounts = await db.get_user_accounts(callback.from_user.id)
    if not accounts:
        await callback.answer("Нет аккаунтов", show_alert=True)
        return
    
    kb = InlineKeyboardBuilder()
    for acc in accounts:
        kb.button(
            text=acc['phone'],
            callback_data=f"cmtacc_{acc['id']}",
            icon_custom_emoji_id=Emoji.profile
        )
    kb.button(text="Назад", callback_data="functions_menu", icon_custom_emoji_id=Emoji.back)
    kb.adjust(1)
    
    await callback.message.edit_text(
        f'<tg-emoji emoji-id="{Emoji.comment}">💬</tg-emoji> <b>Автокомментарии</b>\n\n'
        f'<tg-emoji emoji-id="{Emoji.info}">ℹ️</tg-emoji> Выберите аккаунт для автокомментирования.\n'
        f'Бот будет отслеживать новые посты в выбранных каналах и оставлять комментарии.',
        reply_markup=kb.as_markup()
    )
    await state.set_state(CommentStates.selecting_account)
    await callback.answer()

@dp.callback_query(F.data.startswith("cmtacc_"), CommentStates.selecting_account)
async def comment_select_account(callback: CallbackQuery, state: FSMContext):
    acc_id = int(callback.data.split("_")[1])
    account = await db.get_account_by_id(acc_id)
    
    if not account:
        await callback.answer("Аккаунт не найден", show_alert=True)
        return
    
    chats, total, _ = await db.get_chats_paginated(acc_id, 1)
    
    if not chats:
        kb = InlineKeyboardBuilder()
        kb.button(text="Загрузить чаты", callback_data=f"loadchats_{acc_id}", icon_custom_emoji_id=Emoji.download)
        kb.button(text="Назад", callback_data="comment_menu", icon_custom_emoji_id=Emoji.back)
        kb.adjust(1)
        
        await callback.message.edit_text(
            f'<tg-emoji emoji-id="{Emoji.info}">ℹ️</tg-emoji> '
            f'<b>Нет загруженных чатов!</b>\n\n'
            f'Сначала загрузите список каналов для этого аккаунта.',
            reply_markup=kb.as_markup()
        )
        await callback.answer()
        return
    
    await state.update_data(cmt_acc_id=acc_id, selected_channels=[])
    
    keyboard = await get_channels_keyboard(acc_id)
    
    await callback.message.edit_text(
        f'<tg-emoji emoji-id="{Emoji.people}">👥</tg-emoji> <b>Выберите каналы (до 20)</b>\n\n'
        f'<tg-emoji emoji-id="{Emoji.info}">ℹ️</tg-emoji> Бот будет отслеживать новые посты и комментировать их.\n'
        f'Выбрано: 0/20',
        reply_markup=keyboard
    )
    await state.set_state(CommentStates.selecting_channels)
    await callback.answer()

@dp.callback_query(F.data.startswith("tgl_ch_"), CommentStates.selecting_channels)
async def toggle_channel(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split("_")
    chat_db_id = int(parts[2])
    page = int(parts[3]) if len(parts) > 3 else 1
    
    state_data = await state.get_data()
    selected_channels = state_data.get('selected_channels', [])
    acc_id = state_data.get('cmt_acc_id')
    
    if chat_db_id in selected_channels:
        selected_channels.remove(chat_db_id)
    else:
        if len(selected_channels) >= 20:
            await callback.answer("Максимум 20 каналов", show_alert=True)
            return
        selected_channels.append(chat_db_id)
    
    await state.update_data(selected_channels=selected_channels)
    
    keyboard = await get_channels_keyboard(acc_id, page, selected_channels)
    
    await callback.message.edit_text(
        f'<tg-emoji emoji-id="{Emoji.people}">👥</tg-emoji> <b>Выберите каналы (до 20)</b>\n\n'
        f'Выбрано: {len(selected_channels)}/20',
        reply_markup=keyboard
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("ch_page_"), CommentStates.selecting_channels)
async def change_channels_page(callback: CallbackQuery, state: FSMContext):
    page = int(callback.data.split("_")[-1])
    state_data = await state.get_data()
    selected_channels = state_data.get('selected_channels', [])
    acc_id = state_data.get('cmt_acc_id')
    
    keyboard = await get_channels_keyboard(acc_id, page, selected_channels)
    await callback.message.edit_reply_markup(reply_markup=keyboard)
    await callback.answer()

@dp.callback_query(F.data == "confirm_channels", CommentStates.selecting_channels)
async def confirm_channels(callback: CallbackQuery, state: FSMContext):
    state_data = await state.get_data()
    if not state_data.get('selected_channels'):
        await callback.answer("Выберите хотя бы один канал!", show_alert=True)
        return
    
    await callback.message.edit_text(
        f'<tg-emoji emoji-id="{Emoji.write}">✍️</tg-emoji> <b>Отправьте текст комментария (HTML):</b>\n\n'
        f'<tg-emoji emoji-id="{Emoji.info}">ℹ️</tg-emoji> Этот текст будет оставляться под каждым новым постом.\n'
        f'Поддерживается HTML форматирование.',
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Назад", callback_data="comment_menu", icon_custom_emoji_id=Emoji.back)]
        ])
    )
    await state.set_state(CommentStates.waiting_for_comment_text)
    await callback.answer()

@dp.message(CommentStates.waiting_for_comment_text)
async def start_commentator(message: Message, state: FSMContext):
    comment_text = message.html_text
    state_data = await state.get_data()
    acc_id = state_data.get('cmt_acc_id')
    selected_channels = state_data.get('selected_channels', [])
    
    if not acc_id or not selected_channels:
        await message.answer(
            f'<tg-emoji emoji-id="{Emoji.cross}">❌</tg-emoji> Ошибка данных'
        )
        await state.clear()
        return
    
    account = await db.get_account_by_id(acc_id)
    if not account:
        await message.answer(
            f'<tg-emoji emoji-id="{Emoji.cross}">❌</tg-emoji> Аккаунт не найден'
        )
        await state.clear()
        return
    
    channel_ids = []
    for chat_db_id in selected_channels:
        chat = await db.get_chat_by_db_id(chat_db_id)
        if chat:
            channel_ids.append(chat['chat_id'])
    
    if not channel_ids:
        await message.answer(
            f'<tg-emoji emoji-id="{Emoji.cross}">❌</tg-emoji> Каналы не найдены'
        )
        await state.clear()
        return
    
    active_commentators[message.from_user.id] = {"stop": False}
    
    await message.answer(
        f'<tg-emoji emoji-id="{Emoji.check}">✅</tg-emoji> <b>Автокомментарии запущены!</b>\n\n'
        f'<tg-emoji emoji-id="{Emoji.profile}">👤</tg-emoji> Аккаунт: {account["phone"]}\n'
        f'<tg-emoji emoji-id="{Emoji.people}">👥</tg-emoji> Каналов: {len(channel_ids)}\n\n'
        f'<tg-emoji emoji-id="{Emoji.info}">ℹ️</tg-emoji> Бот будет отслеживать новые посты и оставлять комментарии.\n'
        f'Для остановки нажмите кнопку ниже.',
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="Остановить",
                callback_data="stop_commentator",
                icon_custom_emoji_id=Emoji.stop
            )]
        ])
    )
    
    asyncio.create_task(run_commentator(message.from_user.id, account, channel_ids, comment_text))
    await state.clear()

async def run_commentator(user_id: int, account: Dict, channel_ids: List[int], comment_text: str):
    try:
        client = TelegramClient(
            StringSession(account['session_string']),
            API_ID, API_HASH
        )
        await client.connect()
        
        if not await client.is_user_authorized():
            await bot.send_message(
                user_id,
                f'<tg-emoji emoji-id="{Emoji.cross}">❌</tg-emoji> '
                f'Аккаунт не авторизован'
            )
            if user_id in active_commentators:
                del active_commentators[user_id]
            return
        
        @client.on(events.NewMessage(chats=channel_ids))
        async def handler(event):
            if user_id not in active_commentators or active_commentators[user_id]["stop"]:
                return
            
            try:
                await asyncio.sleep(random.randint(2, 5))
                
                if user_id not in active_commentators or active_commentators[user_id]["stop"]:
                    return
                
                try:
                    await client.send_message(
                        entity=event.chat_id,
                        message=comment_text,
                        parse_mode='html',
                        comment_to=event.message.id
                    )
                    logger.info(f"Comment posted in {event.chat_id}")
                except Exception as e:
                    logger.warning(f"Comment_to failed, trying regular message: {e}")
                    await client.send_message(
                        entity=event.chat_id,
                        message=comment_text,
                        parse_mode='html'
                    )
                    logger.info(f"Regular message posted in {event.chat_id}")
                
            except Exception as e:
                logger.error(f"Comment posting error: {e}")
        
        await bot.send_message(
            user_id,
            f'<tg-emoji emoji-id="{Emoji.check}">✅</tg-emoji> '
            f'<b>Автокомментатор активен!</b>\n\n'
            f'Отслеживается каналов: {len(channel_ids)}\n'
            f'Бот будет оставлять комментарии под новыми постами.'
        )
        
        while user_id in active_commentators and not active_commentators[user_id]["stop"]:
            await asyncio.sleep(1)
        
        client.remove_event_handler(handler)
        
    except Exception as e:
        logger.error(f"Commentator process error: {e}")
        await bot.send_message(
            user_id,
            f'<tg-emoji emoji-id="{Emoji.cross}">❌</tg-emoji> '
            f'Ошибка автокомментатора: {str(e)[:200]}'
        )
    finally:
        await client.disconnect()
        if user_id in active_commentators:
            del active_commentators[user_id]

@dp.callback_query(F.data == "stop_commentator")
async def stop_commentator_handler(callback: CallbackQuery):
    if callback.from_user.id in active_commentators:
        active_commentators[callback.from_user.id]["stop"] = True
        await callback.answer("Останавливаю автокомментарии...", show_alert=True)
    else:
        await callback.answer("Нет активных автокомментариев", show_alert=True)

@dp.callback_query(F.data == "none")
async def none_callback(callback: CallbackQuery):
    await callback.answer()

# ===== ЗАПУСК БОТА =====

async def main():
    logger.info("Starting Vest Traffer 2 bot...")
    
    await db.init()
    
    logger.info("Bot started successfully!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
