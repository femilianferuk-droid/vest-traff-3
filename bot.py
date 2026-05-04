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
from telethon.tl.functions.stories import SendStoryRequest
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
active_stories = {}
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

# ===== PREMIUM EMOJI ID =====
class Emoji:
    # Профиль и пользователи
    profile = "5870994129244131212"
    people = "5870772616305839506"
    user_profile = "5891207662678317861"
    
    # Кнопки действий
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
    
    # Состояния
    clock = "5983150113483134607"
    loading = "5345906554510012647"
    lock_closed = "6037249452824072506"
    lock_open = "6037496202990194718"
    
    # Интерфейс
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
    story = "5870930636742595124"
    media = "6035128606563241721"
    stop = "5870657884844462243"
    file_doc = "5870528606328852614"
    first_bot = "6030400221232501136"
    promo = "6032644646587338669"
    comment = "5870753782874246579"

# ===== БАЗА ДАННЫХ =====
class Database:
    """
    Класс для работы с PostgreSQL базой данных.
    Использует пул соединений для эффективной работы с БД.
    """
    def __init__(self):
        self.pool = None
    
    async def init(self):
        """
        Инициализация подключения к базе данных.
        Выполняет несколько попыток подключения с задержкой при ошибках.
        Создает все необходимые таблицы, если они не существуют.
        """
        logger.info("Initializing database connection...")
        
        # Пытаемся подключиться с повторными попытками (до 5 раз)
        for attempt in range(5):
            try:
                self.pool = psycopg2.pool.ThreadedConnectionPool(1, 10, DATABASE_URL)
                # Проверяем подключение тестовым запросом
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
        
        # Получаем текущий event loop для асинхронных операций с БД
        loop = asyncio.get_running_loop()
        
        # Создаем асинхронные обертки для работы с БД через run_in_executor
        async def _exec(query, *args):
            """Выполнить SQL запрос без возврата результата (INSERT, UPDATE, DELETE)"""
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
            """Выполнить SELECT запрос и вернуть список записей"""
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
            """Выполнить SELECT запрос и вернуть одну запись"""
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
            """Выполнить SELECT запрос и вернуть одно значение"""
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
            """Выполнить INSERT запрос и вернуть ID вставленной записи"""
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
        
        # Сохраняем методы как атрибуты экземпляра класса
        self._execute = _exec
        self._fetch = _fetch
        self._fetchrow = _fetchrow
        self._fetchval = _fetchval
        self._insert_returning_id = _insert_returning_id
        
        # ===== СОЗДАНИЕ ТАБЛИЦ БАЗЫ ДАННЫХ =====
        logger.info("Creating database tables...")
        
        # Таблица пользователей бота
        await self._execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                subscription_until TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Таблица аккаунтов Telegram
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
        
        # Таблица чатов (каналов и групп) для аккаунтов
        await self._execute('''
            CREATE TABLE IF NOT EXISTS chats (
                id SERIAL PRIMARY KEY,
                account_id INTEGER REFERENCES accounts(id) ON DELETE CASCADE,
                chat_id BIGINT NOT NULL,
                title TEXT,
                type TEXT
            )
        ''')
        
        # Таблица промокодов
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
        
        # Таблица активаций промокодов пользователями
        await self._execute('''
            CREATE TABLE IF NOT EXISTS promo_activations (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                promo_id INTEGER REFERENCES promocodes(id) ON DELETE CASCADE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, promo_id)
            )
        ''')
        
        # Таблица инструкций (редактируется админом)
        await self._execute('''
            CREATE TABLE IF NOT EXISTS instructions (
                id SERIAL PRIMARY KEY,
                text TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        logger.info("Database initialization completed successfully")
    
    # ===== МЕТОДЫ ДЛЯ РАБОТЫ С ПОЛЬЗОВАТЕЛЯМИ =====
    
    async def create_user(self, user_id: int):
        """Создать нового пользователя, если он еще не существует"""
        await self._execute(
            'INSERT INTO users (user_id) VALUES (%s) ON CONFLICT DO NOTHING',
            user_id
        )
    
    async def has_subscription(self, user_id: int) -> bool:
        """Проверить, есть ли у пользователя активная подписка"""
        row = await self._fetchrow(
            "SELECT subscription_until FROM users WHERE user_id = %s",
            user_id
        )
        if row and row['subscription_until']:
            return row['subscription_until'] > datetime.now()
        return False
    
    async def get_subscription(self, user_id: int) -> Optional[Dict]:
        """Получить информацию о подписке пользователя"""
        row = await self._fetchrow(
            "SELECT subscription_until FROM users WHERE user_id = %s",
            user_id
        )
        return dict(row) if row else None
    
    async def add_subscription(self, user_id: int, days: int):
        """
        Продлить подписку пользователя на указанное количество дней.
        Если подписка уже активна - добавляет дни к текущей дате окончания.
        Если подписка неактивна - начинает новую с текущего момента.
        """
        current = await self._fetchrow(
            "SELECT subscription_until FROM users WHERE user_id = %s",
            user_id
        )
        if current and current['subscription_until'] and current['subscription_until'] > datetime.now():
            # Подписка активна - продлеваем
            new_until = current['subscription_until'] + timedelta(days=days)
        else:
            # Подписка неактивна - начинаем новую
            new_until = datetime.now() + timedelta(days=days)
        
        await self._execute(
            'UPDATE users SET subscription_until = %s WHERE user_id = %s',
            new_until, user_id
        )
    
    async def get_all_users(self) -> List[Dict]:
        """Получить список всех пользователей бота"""
        rows = await self._fetch("SELECT * FROM users ORDER BY created_at DESC")
        return [dict(r) for r in rows]
    
    # ===== МЕТОДЫ ДЛЯ РАБОТЫ С АККАУНТАМИ TELEGRAM =====
    
    async def add_account(self, user_id: int, phone: str, session_string: str) -> bool:
        """
        Добавить новый аккаунт Telegram или обновить сессию существующего.
        Сессия сохраняется в виде строки StringSession.
        """
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
        """Получить список аккаунтов пользователя"""
        rows = await self._fetch(
            "SELECT id, phone, is_active FROM accounts WHERE user_id = %s ORDER BY created_at DESC",
            user_id
        )
        return [
            {"id": r['id'], "phone": r['phone'], "is_active": r['is_active']}
            for r in rows
        ]
    
    async def get_account_count(self, user_id: int) -> int:
        """Получить количество аккаунтов пользователя"""
        count = await self._fetchval(
            "SELECT COUNT(*) FROM accounts WHERE user_id = %s",
            user_id
        )
        return count if count else 0
    
    async def get_account_by_id(self, account_id: int) -> Optional[Dict]:
        """Получить информацию об аккаунте по его ID"""
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
        """Удалить аккаунт и все связанные с ним данные"""
        await self._execute("DELETE FROM accounts WHERE id = %s", account_id)
    
    # ===== МЕТОДЫ ДЛЯ РАБОТЫ С ЧАТАМИ (КАНАЛАМИ) =====
    
    async def save_chats(self, account_id: int, chats_data: List[Dict]):
        """
        Сохранить список чатов для аккаунта.
        Старые чаты удаляются, новые добавляются.
        """
        await self._execute("DELETE FROM chats WHERE account_id = %s", account_id)
        for chat in chats_data:
            await self._execute(
                "INSERT INTO chats (account_id, chat_id, title, type) VALUES (%s, %s, %s, %s)",
                account_id, chat['chat_id'], chat['title'], chat['type']
            )
    
    async def get_chats_paginated(self, account_id: int, page: int, per_page: int = 10) -> tuple:
        """
        Получить чаты аккаунта с пагинацией.
        Возвращает кортеж: (список чатов, общее количество, количество страниц)
        """
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
        """Получить информацию о чате по его ID в базе данных"""
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
    
    # ===== МЕТОДЫ ДЛЯ РАБОТЫ С ПРОМОКОДАМИ =====
    
    async def create_promo(self, code: str, promo_type: str, value: int, max_activations: int) -> int:
        """Создать новый промокод"""
        return await self._insert_returning_id(
            'INSERT INTO promocodes (code, type, value, max_activations) VALUES (%s, %s, %s, %s) RETURNING id',
            code, promo_type, value, max_activations
        )
    
    async def get_promo(self, code: str) -> Optional[Dict]:
        """Найти промокод по его коду (без учета регистра)"""
        row = await self._fetchrow(
            "SELECT * FROM promocodes WHERE code = %s",
            code.upper()
        )
        return dict(row) if row else None
    
    async def activate_promo(self, user_id: int, promo_id: int):
        """Активировать промокод для пользователя"""
        await self._execute(
            'INSERT INTO promo_activations (user_id, promo_id) VALUES (%s, %s)',
            user_id, promo_id
        )
        await self._execute(
            'UPDATE promocodes SET current_activations = current_activations + 1 WHERE id = %s',
            promo_id
        )
    
    async def has_activated_promo(self, user_id: int, promo_id: int) -> bool:
        """Проверить, активировал ли пользователь данный промокод"""
        row = await self._fetchrow(
            "SELECT id FROM promo_activations WHERE user_id = %s AND promo_id = %s",
            user_id, promo_id
        )
        return row is not None
    
    # ===== МЕТОДЫ ДЛЯ РАБОТЫ С ИНСТРУКЦИЯМИ =====
    
    async def get_instruction(self) -> str:
        """Получить текущий текст инструкции"""
        row = await self._fetchrow(
            "SELECT text FROM instructions ORDER BY id DESC LIMIT 1"
        )
        if row and row['text']:
            return row['text']
        return "<b>📄 Инструкция</b>\n\nИнструкция пока не добавлена администратором."
    
    async def update_instruction(self, text: str):
        """Обновить текст инструкции (заменяет старый текст)"""
        await self._execute("DELETE FROM instructions")
        await self._execute("INSERT INTO instructions (text) VALUES (%s)", text)

# ===== ИНИЦИАЛИЗАЦИЯ БОТА И БАЗЫ ДАННЫХ =====
db = Database()
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())

# Временное хранилище для процесса авторизации аккаунтов
auth_sessions = {}

# ===== СОСТОЯНИЯ FSM (Finite State Machine) =====

class AccountStates(StatesGroup):
    """Состояния для процесса добавления нового аккаунта"""
    waiting_for_phone = State()
    waiting_for_code = State()
    waiting_for_2fa = State()

class AdminStates(StatesGroup):
    """Состояния для админ-панели"""
    waiting_for_user_id = State()
    waiting_for_days = State()
    waiting_for_promo_type = State()
    waiting_for_promo_value = State()
    waiting_for_promo_code = State()
    waiting_for_promo_activations = State()
    waiting_for_instruction = State()

class PromoStates(StatesGroup):
    """Состояния для активации промокода"""
    waiting_for_code = State()

class StoryStates(StatesGroup):
    """Состояния для создания историй"""
    selecting_account = State()
    waiting_for_media = State()
    waiting_for_usernames_file = State()
    waiting_for_delay = State()

class CommentStates(StatesGroup):
    """Состояния для настройки автокомментариев"""
    selecting_account = State()
    selecting_channels = State()
    waiting_for_comment_text = State()

# ===== КЛАВИАТУРЫ БОТА =====

def get_main_menu():
    """
    Главное меню бота с основными разделами.
    Использует ReplyKeyboardMarkup для постоянного отображения.
    """
    kb = ReplyKeyboardBuilder()
    kb.button(text="Менеджер аккаунтов", icon_custom_emoji_id=Emoji.people)
    kb.button(text="Функции", icon_custom_emoji_id=Emoji.megaphone)
    kb.button(text="Профиль", icon_custom_emoji_id=Emoji.user_profile)
    kb.button(text="Инструкция", icon_custom_emoji_id=Emoji.instruction)
    kb.button(text="Поддержка", icon_custom_emoji_id=Emoji.support)
    kb.adjust(2, 2, 1)
    return kb.as_markup(resize_keyboard=True)

def get_functions_menu():
    """
    Меню функций бота.
    Содержит кнопки для доступа к историям и автокомментариям.
    """
    kb = InlineKeyboardBuilder()
    kb.button(text="Создание историй", callback_data="story_menu", icon_custom_emoji_id=Emoji.story)
    kb.button(text="Автокомментарии", callback_data="comment_menu", icon_custom_emoji_id=Emoji.comment)
    kb.button(text="Назад", callback_data="main_menu", icon_custom_emoji_id=Emoji.back)
    kb.adjust(1)
    return kb.as_markup()

def get_admin_menu():
    """
    Меню админ-панели.
    Доступно только администратору бота.
    """
    kb = InlineKeyboardBuilder()
    kb.button(text="Выдать подписку", callback_data="admin_give_sub", icon_custom_emoji_id=Emoji.crown)
    kb.button(text="Создать промокод", callback_data="admin_create_promo", icon_custom_emoji_id=Emoji.promo)
    kb.button(text="Изменить инструкцию", callback_data="admin_edit_instruction", icon_custom_emoji_id=Emoji.instruction)
    kb.button(text="Список пользователей", callback_data="admin_users", icon_custom_emoji_id=Emoji.people)
    kb.button(text="Назад", callback_data="main_menu", icon_custom_emoji_id=Emoji.back)
    kb.adjust(1)
    return kb.as_markup()

def get_accounts_menu():
    """
    Меню управления аккаунтами Telegram.
    Позволяет добавлять новые и просматривать существующие аккаунты.
    """
    kb = InlineKeyboardBuilder()
    kb.button(text="Добавить аккаунт", callback_data="add_account", icon_custom_emoji_id=Emoji.add_text)
    kb.button(text="Мои аккаунты", callback_data="view_accounts", icon_custom_emoji_id=Emoji.eye)
    kb.button(text="Назад", callback_data="main_menu", icon_custom_emoji_id=Emoji.back)
    kb.adjust(1)
    return kb.as_markup()

def get_accounts_list(accounts: List[Dict]):
    """
    Список аккаунтов пользователя с кнопками для управления.
    Зеленый значок - аккаунт активен, красный - неактивен.
    """
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
    """
    Меню профиля пользователя.
    Отображает информацию о подписке и позволяет управлять ею.
    """
    kb = InlineKeyboardBuilder()
    kb.button(text="Купить подписку", callback_data="buy_subscription", icon_custom_emoji_id=Emoji.crown)
    kb.button(text="Активировать промокод", callback_data="activate_promo", icon_custom_emoji_id=Emoji.promo)
    kb.button(text="Назад", callback_data="main_menu", icon_custom_emoji_id=Emoji.back)
    kb.adjust(1)
    return kb.as_markup()

def get_subscription_keyboard():
    """
    Клавиатура выбора срока подписки.
    Отображает все доступные тарифы с ценами.
    """
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
    """
    Клавиатура выбора способа оплаты подписки.
    Доступны: USDT и TON через CryptoBot, Рубли через YooMoney.
    """
    kb = InlineKeyboardBuilder()
    kb.button(text="USDT", callback_data=f"pay_usdt_{sub_key}", icon_custom_emoji_id=Emoji.money)
    kb.button(text="TON", callback_data=f"pay_ton_{sub_key}", icon_custom_emoji_id=Emoji.money)
    kb.button(text="Рубли", callback_data=f"pay_rub_{sub_key}", icon_custom_emoji_id=Emoji.wallet)
    kb.button(text="Назад", callback_data="buy_subscription", icon_custom_emoji_id=Emoji.back)
    kb.adjust(2)
    return kb.as_markup()

def get_promo_type_keyboard():
    """
    Клавиатура выбора типа промокода при создании.
    Скидка указывается в процентах, подписка - в днях.
    """
    kb = InlineKeyboardBuilder()
    kb.button(text="На скидку (%)", callback_data="promotype_discount", icon_custom_emoji_id=Emoji.money)
    kb.button(text="На подписку (дни)", callback_data="promotype_subscription", icon_custom_emoji_id=Emoji.crown)
    kb.button(text="Назад", callback_data="admin_back", icon_custom_emoji_id=Emoji.back)
    kb.adjust(2)
    return kb.as_markup()

async def get_channels_keyboard(account_id: int, page: int = 1, selected_channels: List[int] = None):
    """
    Клавиатура для выбора каналов при настройке автокомментариев.
    Показывает только каналы и супергруппы с пагинацией.
    """
    if selected_channels is None:
        selected_channels = []
    
    chats, total, total_pages = await db.get_chats_paginated(account_id, page)
    
    kb = InlineKeyboardBuilder()
    
    # Показываем только каналы и супергруппы
    for chat in chats:
        if chat['type'] in ['channel', 'group']:
            is_selected = chat['id'] in selected_channels
            prefix_emoji = Emoji.check if is_selected else Emoji.cross
            kb.button(
                text=chat['title'][:30] if chat['title'] else "Без названия",
                callback_data=f"tgl_ch_{chat['id']}_{page}",
                icon_custom_emoji_id=prefix_emoji
            )
    
    # Кнопки навигации по страницам
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
    
    # Кнопка продолжения (показывается только если есть выбранные каналы)
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
    """
    Обработчик команды /start.
    Регистрирует пользователя в базе данных и показывает приветственное сообщение
    с описанием всех возможностей бота.
    """
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
        f'<b>Функции</b> - создание историй и автокомментарии\n'
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
    """
    Обработчик команды /admin.
    Доступен только администратору бота (ID указан в конфигурации).
    """
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
    """
    Обработчик кнопки "Менеджер аккаунтов".
    Проверяет наличие подписки и показывает меню управления аккаунтами.
    """
    # Проверка подписки (админ имеет доступ без подписки)
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
    """
    Обработчик кнопки "Функции".
    Показывает меню с доступными функциями бота.
    """
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
    """
    Обработчик кнопки "Профиль".
    Показывает информацию о пользователе и статус его подписки.
    """
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
    """
    Обработчик кнопки "Инструкция".
    Показывает инструкцию по использованию бота.
    """
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
    """
    Обработчик кнопки "Поддержка".
    Показывает контактную информацию для связи с поддержкой.
    """
    await message.answer(
        f'<tg-emoji emoji-id="{Emoji.support}">📞</tg-emoji> <b>Поддержка</b>\n\n'
        f'По всем вопросам обращайтесь: @VestSupport\n\n'
        f'<tg-emoji emoji-id="{Emoji.first_bot}">🤖</tg-emoji> '
        f'Первая часть бота: {FIRST_BOT}'
    )

# ===== CALLBACK ОБРАБОТЧИКИ НАВИГАЦИИ =====

@dp.callback_query(F.data == "main_menu")
async def back_to_main(callback: CallbackQuery):
    """
    Возврат в главное меню.
    Удаляет текущее сообщение и отправляет новое с главным меню.
    """
    await callback.message.delete()
    await callback.message.answer(
        f'<tg-emoji emoji-id="{Emoji.bot_emoji}">🤖</tg-emoji> <b>Главное меню</b>',
        reply_markup=get_main_menu()
    )
    await callback.answer()

@dp.callback_query(F.data == "functions_menu")
async def functions_menu_callback(callback: CallbackQuery):
    """
    Возврат в меню функций.
    Проверяет подписку перед показом меню.
    """
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
    """
    Покупка подписки - выбор срока.
    Показывает доступные тарифы с ценами.
    """
    await callback.message.edit_text(
        f'<tg-emoji emoji-id="{Emoji.crown}">👑</tg-emoji> <b>Выберите срок подписки:</b>\n\n'
        f'<tg-emoji emoji-id="{Emoji.info}">ℹ️</tg-emoji> '
        f'После оплаты подписка активируется автоматически',
        reply_markup=get_subscription_keyboard()
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("sub_"))
async def select_subscription(callback: CallbackQuery):
    """
    Выбор способа оплаты для выбранного тарифа подписки.
    """
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
    """
    Обработка платежа за подписку.
    Поддерживает оплату через CryptoBot (USDT/TON) и YooMoney (Рубли).
    """
    parts = callback.data.split("_")
    method = parts[1]  # usdt, ton или rub
    sub_key = parts[2]  # ключ тарифа
    
    sub = SUBSCRIPTIONS.get(sub_key)
    if not sub:
        await callback.answer("Ошибка: подписка не найдена", show_alert=True)
        return
    
    user_id = callback.from_user.id
    
    # Оплата через CryptoBot (USDT или TON)
    if method in ("usdt", "ton"):
        if not CRYPTOBOT_TOKEN:
            await callback.answer("CryptoBot не настроен", show_alert=True)
            return
        
        currency = "USDT" if method == "usdt" else "TON"
        rate = USDT_RATE if method == "usdt" else TON_RATE
        crypto_amount = round(sub['price'] / rate, 2)
        
        # Создаем инвойс через CryptoBot API
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
    
    # Оплата через YooMoney (Рубли)
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
    """
    Просмотр профиля через callback (при нажатии на кнопку).
    """
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
    """
    Начало активации промокода.
    Запрашивает у пользователя код промокода для ввода.
    """
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
    """
    Обработка ввода промокода.
    Проверяет существование, количество оставшихся активаций,
    и не активировал ли пользователь этот промокод ранее.
    """
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
    
    # Активируем промокод
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
    """
    Выдача подписки пользователю.
    Админ вводит ID пользователя и выбирает срок подписки.
    """
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
    """
    Просмотр списка всех пользователей бота.
    Показывает ID и статус подписки (✅ активна / ❌ неактивна).
    """
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
    """Возврат в главное меню админ-панели"""
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
    """
    Обработка ввода ID пользователя для выдачи подписки.
    После ввода ID показывает выбор срока подписки.
    """
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
    """Завершение выдачи подписки - применение выбранного срока"""
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
    """Создание нового промокода - выбор типа (скидка или подписка)"""
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
    """Установка типа промокода и запрос значения"""
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
    """Установка числового значения промокода"""
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
    """Установка кода промокода"""
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
    """Завершение создания промокода - сохранение в БД"""
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
    """Изменение текста инструкции. Админ вводит новый текст в HTML формате."""
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
    """Сохранение нового текста инструкции"""
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
    """
    Начало процесса добавления нового аккаунта Telegram.
    Проверяет лимит аккаунтов (максимум 100) и запрашивает номер телефона.
    """
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
    """
    Обработка номера телефона.
    Отправляет код подтверждения через Telegram API.
    """
    phone = message.text.strip()
    
    # Создаем клиент Telethon для отправки запроса
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
    
    # Сохраняем сессию для дальнейшей авторизации
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
    """
    Обработка кода подтверждения.
    Завершает авторизацию аккаунта и сохраняет сессию.
    """
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
        # Требуется двухфакторная аутентификация
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
    """
    Обработка пароля двухфакторной аутентификации.
    """
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
    """
    Завершение авторизации аккаунта.
    Сохраняет сессию в базу данных и показывает меню аккаунтов.
    """
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
    """
    Просмотр списка добавленных аккаунтов.
    Для каждого аккаунта показывает телефон и статус.
    """
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
    """Возврат в меню управления аккаунтами"""
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

# ===== ЗАГРУЗКА ЧАТОВ (КАНАЛОВ) ДЛЯ АККАУНТА =====

@dp.callback_query(F.data.startswith("loadchats_"))
async def load_chats(callback: CallbackQuery):
    """
    Загрузка списка чатов (каналов и групп) для аккаунта.
    Сохраняет в БД для использования в функциях бота.
    """
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
        # Подключаемся к аккаунту через Telethon
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
        
        # Получаем список диалогов (чатов)
        dialogs = await client.get_dialogs(limit=200)
        chats_data = []
        
        for dialog in dialogs:
            # Сохраняем только каналы и супергруппы
            if dialog.is_channel or dialog.is_group:
                chat_type = "channel" if dialog.is_channel else "group"
                chats_data.append({
                    'chat_id': dialog.id,
                    'title': dialog.name[:100] if dialog.name else "Без названия",
                    'type': chat_type
                })
        
        # Сохраняем в базу данных
        await db.save_chats(acc_id, chats_data)
        
        await callback.message.edit_text(
            f'<tg-emoji emoji-id="{Emoji.check}">✅</tg-emoji> '
            f'<b>Чаты загружены!</b>\n\n'
            f'Каналов и групп: {len(chats_data)}\n\n'
            f'Теперь вы можете использовать автокомментарии.',
            reply_markup=get_accounts_menu()
        )
        
    except Exception as e:
        logger.error(f"Error loading chats: {e}")
        await callback.message.edit_text(
            f'<tg-emoji emoji-id="{Emoji.cross}">❌</tg-emoji> '
            f'Ошибка при загрузке чатов:\n{str(e)[:200]}'
        )
    finally:
        await client.disconnect()

# ===== СОЗДАНИЕ ИСТОРИЙ =====

@dp.callback_query(F.data == "story_menu")
async def story_menu_handler(callback: CallbackQuery, state: FSMContext):
    """
    Меню создания историй.
    Показывает список аккаунтов для выбора.
    """
    accounts = await db.get_user_accounts(callback.from_user.id)
    if not accounts:
        await callback.answer("Нет аккаунтов", show_alert=True)
        return
    
    kb = InlineKeyboardBuilder()
    for acc in accounts:
        kb.button(
            text=acc['phone'],
            callback_data=f"storyacc_{acc['id']}",
            icon_custom_emoji_id=Emoji.profile
        )
    kb.button(
        text="Назад",
        callback_data="functions_menu",
        icon_custom_emoji_id=Emoji.back
    )
    kb.adjust(1)
    
    await callback.message.edit_text(
        f'<tg-emoji emoji-id="{Emoji.story}">📊</tg-emoji> '
        f'<b>Создание историй</b>\n\n'
        f'<tg-emoji emoji-id="{Emoji.info}">ℹ️</tg-emoji> '
        f'Выберите аккаунт для публикации историй.\n'
        f'Бот будет создавать истории с отметками людей.',
        reply_markup=kb.as_markup()
    )
    await state.set_state(StoryStates.selecting_account)
    await callback.answer()

@dp.callback_query(F.data.startswith("storyacc_"), StoryStates.selecting_account)
async def story_select_account(callback: CallbackQuery, state: FSMContext):
    """
    Выбор аккаунта для историй.
    Запрашивает отправку медиа (фото или видео).
    """
    acc_id = int(callback.data.split("_")[1])
    await state.update_data(story_acc_id=acc_id)
    
    await callback.message.edit_text(
        f'<tg-emoji emoji-id="{Emoji.media}">🖼</tg-emoji> '
        f'<b>Отправьте фото или видео для истории:</b>\n\n'
        f'<tg-emoji emoji-id="{Emoji.info}">ℹ️</tg-emoji> '
        f'Поддерживаются фото и видео файлы.\n'
        f'Это медиа будет использоваться для всех историй.',
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="Назад",
                callback_data="story_menu",
                icon_custom_emoji_id=Emoji.back
            )]
        ])
    )
    await state.set_state(StoryStates.waiting_for_media)
    await callback.answer()

@dp.message(F.photo, StoryStates.waiting_for_media)
async def story_receive_photo(message: Message, state: FSMContext):
    """
    Получение фото для истории.
    Конвертирует в JPEG формат для совместимости с Telegram Stories.
    """
    try:
        # Скачиваем фото в максимальном качестве
        photo = message.photo[-1]
        file_obj = await bot.download(photo)
        
        # Конвертируем в JPEG с помощью PIL
        img = Image.open(file_obj)
        if img.mode in ('RGBA', 'P'):
            img = img.convert('RGB')
        
        output = BytesIO()
        img.save(output, format='JPEG', quality=95)
        output.seek(0)
        output.name = 'story.jpg'  # Важно: имя файла с расширением
        
        await state.update_data(story_media=output, story_is_video=False)
        await message.answer(
            f'<tg-emoji emoji-id="{Emoji.check}">✅</tg-emoji> '
            f'<b>Фото получено!</b>\n\n'
            f'<tg-emoji emoji-id="{Emoji.file_doc}">📁</tg-emoji> '
            f'<b>Теперь отправьте TXT файл со списком юзернеймов:</b>\n\n'
            f'<tg-emoji emoji-id="{Emoji.info}">ℹ️</tg-emoji> '
            f'Каждый юзернейм с новой строки\n'
            f'Бот будет отмечать по 4 человека в каждой истории\n'
            f'Пример файла:\n'
            f'<code>username1\nusername2\nusername3\nusername4</code>'
        )
        await state.set_state(StoryStates.waiting_for_usernames_file)
    except Exception as e:
        logger.error(f"Error processing photo: {e}")
        await message.answer(
            f'<tg-emoji emoji-id="{Emoji.cross}">❌</tg-emoji> '
            f'Ошибка при обработке фото. Попробуйте снова.'
        )

@dp.message(F.video, StoryStates.waiting_for_media)
async def story_receive_video(message: Message, state: FSMContext):
    """
    Получение видео для истории.
    Сохраняет в BytesIO с правильным именем файла.
    """
    try:
        video = message.video
        file_obj = await bot.download(video)
        
        output = BytesIO()
        output.write(file_obj.read() if hasattr(file_obj, 'read') else file_obj)
        output.seek(0)
        output.name = 'story.mp4'  # Важно: имя файла с расширением
        
        await state.update_data(story_media=output, story_is_video=True)
        await message.answer(
            f'<tg-emoji emoji-id="{Emoji.check}">✅</tg-emoji> '
            f'<b>Видео получено!</b>\n\n'
            f'<tg-emoji emoji-id="{Emoji.file_doc}">📁</tg-emoji> '
            f'<b>Теперь отправьте TXT файл со списком юзернеймов:</b>\n\n'
            f'<tg-emoji emoji-id="{Emoji.info}">ℹ️</tg-emoji> '
            f'Каждый юзернейм с новой строки\n'
            f'Бот будет отмечать по 4 человека в каждой истории\n'
            f'Пример файла:\n'
            f'<code>username1\nusername2\nusername3\nusername4</code>'
        )
        await state.set_state(StoryStates.waiting_for_usernames_file)
    except Exception as e:
        logger.error(f"Error processing video: {e}")
        await message.answer(
            f'<tg-emoji emoji-id="{Emoji.cross}">❌</tg-emoji> '
            f'Ошибка при обработке видео. Попробуйте снова.'
        )

@dp.message(F.document, StoryStates.waiting_for_usernames_file)
async def story_receive_usernames(message: Message, state: FSMContext):
    """
    Получение TXT файла со списком юзернеймов для отметок в историях.
    """
    if not message.document.file_name.endswith('.txt'):
        await message.answer(
            f'<tg-emoji emoji-id="{Emoji.cross}">❌</tg-emoji> '
            f'Только TXT файлы!'
        )
        return
    
    try:
        file_content = await bot.download(message.document)
        content = file_content.read().decode('utf-8')
        usernames = [
            u.strip().replace('@', '')
            for u in content.strip().split('\n')
            if u.strip()
        ]
        
        if not usernames:
            await message.answer(
                f'<tg-emoji emoji-id="{Emoji.cross}">❌</tg-emoji> '
                f'Файл пуст или не содержит юзернеймов'
            )
            return
        
        await state.update_data(story_usernames=usernames)
        
        await message.answer(
            f'<tg-emoji emoji-id="{Emoji.check}">✅</tg-emoji> '
            f'<b>Файл получен!</b>\n\n'
            f'<tg-emoji emoji-id="{Emoji.clock}">⏰</tg-emoji> '
            f'<b>Введите задержку между историями (в часах):</b>\n\n'
            f'<tg-emoji emoji-id="{Emoji.info}">ℹ️</tg-emoji> '
            f'Минимум 1 час\n'
            f'<tg-emoji emoji-id="{Emoji.people}">👥</tg-emoji> '
            f'Загружено юзернеймов: {len(usernames)}\n'
            f'<tg-emoji emoji-id="{Emoji.info}">ℹ️</tg-emoji> '
            f'Будет создано примерно {len(usernames) // 4} историй\n'
            f'<tg-emoji emoji-id="{Emoji.info}">ℹ️</tg-emoji> '
            f'Первая история создается сразу после запуска!'
        )
        await state.set_state(StoryStates.waiting_for_delay)
    except Exception as e:
        logger.error(f"Error reading file: {e}")
        await message.answer(
            f'<tg-emoji emoji-id="{Emoji.cross}">❌</tg-emoji> '
            f'Ошибка при чтении файла'
        )

@dp.message(StoryStates.waiting_for_delay)
async def story_start(message: Message, state: FSMContext):
    """
    Запуск создания историй.
    Первая история создается сразу, затем с указанной задержкой.
    """
    try:
        hours = int(message.text)
        if hours < 1:
            await message.answer(
                f'<tg-emoji emoji-id="{Emoji.cross}">❌</tg-emoji> '
                f'Минимум 1 час'
            )
            return
        
        delay = hours * 3600  # Переводим часы в секунды
        state_data = await state.get_data()
        acc_id = state_data.get('story_acc_id')
        account = await db.get_account_by_id(acc_id)
        media_data = state_data.get('story_media')
        is_video = state_data.get('story_is_video', False)
        usernames = state_data.get('story_usernames', [])
        
        if not account or not media_data or not usernames:
            await message.answer(
                f'<tg-emoji emoji-id="{Emoji.cross}">❌</tg-emoji> '
                f'<b>Ошибка данных!</b>\n\n'
                f'Пожалуйста, начните создание истории заново.'
            )
            await state.clear()
            return
        
        # Инициализируем хранилище активных историй
        active_stories[message.from_user.id] = {"stop": False}
        
        await message.answer(
            f'<tg-emoji emoji-id="{Emoji.loading}">🔄</tg-emoji> '
            f'<b>Запуск создания историй!</b>\n\n'
            f'<tg-emoji emoji-id="{Emoji.profile}">👤</tg-emoji> '
            f'Аккаунт: {account["phone"]}\n'
            f'<tg-emoji emoji-id="{Emoji.people}">👥</tg-emoji> '
            f'Юзернеймов: {len(usernames)}\n'
            f'<tg-emoji emoji-id="{Emoji.clock}">⏰</tg-emoji> '
            f'Задержка: {hours} ч.\n'
            f'<tg-emoji emoji-id="{Emoji.info}">ℹ️</tg-emoji> '
            f'Отмечается по 4 человека в истории\n'
            f'<tg-emoji emoji-id="{Emoji.info}">ℹ️</tg-emoji> '
            f'Первая история будет создана сразу же\n\n'
            f'<tg-emoji emoji-id="{Emoji.info}">ℹ️</tg-emoji> '
            f'Нажмите кнопку ниже чтобы остановить',
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text="Остановить",
                    callback_data="stop_stories",
                    icon_custom_emoji_id=Emoji.stop
                )]
            ])
        )
        
        # Запускаем создание историй в фоновом режиме
        asyncio.create_task(
            run_stories(
                message.from_user.id,
                account,
                media_data,
                is_video,
                usernames,
                delay
            )
        )
        await state.clear()
        
    except ValueError:
        await message.answer(
            f'<tg-emoji emoji-id="{Emoji.cross}">❌</tg-emoji> '
            f'Введите число'
        )

async def run_stories(user_id: int, account: Dict, media_data: BytesIO, is_video: bool, usernames: List[str], delay: int):
    """
    Фоновый процесс создания историй.
    Загружает медиа один раз и создает истории для каждой группы из 4 человек.
    Первая история создается сразу, затем ждет указанную задержку.
    """
    try:
        # Создаем клиент Telethon
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
            if user_id in active_stories:
                del active_stories[user_id]
            return
        
        success_count = 0
        error_count = 0
        
        # Загружаем медиа файл один раз для всех историй
        media_data.seek(0)
        filename = getattr(media_data, 'name', 'story.jpg' if not is_video else 'story.mp4')
        uploaded_file = await client.upload_file(media_data, part_size_kb=512)
        
        # Создаем истории для каждой группы из 4 человек
        for i in range(0, len(usernames), 4):
            # Проверяем, не остановлен ли процесс
            if user_id in active_stories and active_stories[user_id]["stop"]:
                break
            
            batch = usernames[i:i+4]  # Берем следующую группу
            
            try:
                # Создаем медиа в зависимости от типа (фото или видео)
                if is_video:
                    media = InputMediaUploadedDocument(
                        file=uploaded_file,
                        mime_type='video/mp4',
                        attributes=[
                            DocumentAttributeVideo(
                                duration=0, w=0, h=0,
                                round_message=False,
                                supports_streaming=True
                            ),
                            DocumentAttributeFilename(file_name=filename)
                        ]
                    )
                else:
                    media = InputMediaUploadedPhoto(
                        file=uploaded_file,
                        stickers=[],
                        ttl_seconds=None
                    )
                
                # Отправляем историю
                await client(SendStoryRequest(
                    peer='me',
                    media=media,
                    privacy_rules=[],
                    random_id=random.randint(100000, 999999)
                ))
                
                success_count += 1
                logger.info(f"Story {success_count} created successfully")
                
            except Exception as e:
                error_count += 1
                logger.error(f"Story creation error: {e}")
            
            # Если это не последняя группа - ждем указанную задержку
            if i + 4 < len(usernames) and delay > 0:
                for _ in range(delay):
                    if user_id in active_stories and active_stories[user_id]["stop"]:
                        break
                    await asyncio.sleep(1)
        
        # Отправляем финальный отчет
        stopped = user_id in active_stories and active_stories[user_id]["stop"]
        status_text = "остановлены" if stopped else "завершены"
        
        await bot.send_message(
            user_id,
            f'<tg-emoji emoji-id="{Emoji.check}">✅</tg-emoji> '
            f'<b>Создание историй {status_text}!</b>\n\n'
            f'<tg-emoji emoji-id="{Emoji.send}">⬆</tg-emoji> '
            f'Создано: {success_count}\n'
            f'<tg-emoji emoji-id="{Emoji.cross}">❌</tg-emoji> '
            f'Ошибок: {error_count}'
        )
        
    except Exception as e:
        logger.error(f"Story task error: {e}")
        await bot.send_message(
            user_id,
            f'<tg-emoji emoji-id="{Emoji.cross}">❌</tg-emoji> '
            f'Ошибка при создании историй: {str(e)[:200]}'
        )
    finally:
        await client.disconnect()
        if user_id in active_stories:
            del active_stories[user_id]

@dp.callback_query(F.data == "stop_stories")
async def stop_stories_handler(callback: CallbackQuery):
    """Остановка процесса создания историй"""
    if callback.from_user.id in active_stories:
        active_stories[callback.from_user.id]["stop"] = True
        await callback.answer("Останавливаю создание историй...", show_alert=True)
    else:
        await callback.answer("Нет активных историй", show_alert=True)

# ===== АВТОКОММЕНТАРИИ =====

@dp.callback_query(F.data == "comment_menu")
async def comment_menu_handler(callback: CallbackQuery, state: FSMContext):
    """
    Меню настройки автокомментариев.
    Показывает список аккаунтов для выбора.
    """
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
    """
    Выбор аккаунта для автокомментариев.
    Проверяет наличие загруженных чатов и показывает список каналов.
    """
    acc_id = int(callback.data.split("_")[1])
    account = await db.get_account_by_id(acc_id)
    
    if not account:
        await callback.answer("Аккаунт не найден", show_alert=True)
        return
    
    # Проверяем, загружены ли чаты для этого аккаунта
    chats, total, _ = await db.get_chats_paginated(acc_id, 1)
    
    if not chats:
        # Предлагаем сначала загрузить чаты
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
    """
    Переключение выбора канала (выбран/не выбран).
    Максимум можно выбрать 20 каналов.
    """
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
    """Переключение страницы при выборе каналов"""
    page = int(callback.data.split("_")[-1])
    state_data = await state.get_data()
    selected_channels = state_data.get('selected_channels', [])
    acc_id = state_data.get('cmt_acc_id')
    
    keyboard = await get_channels_keyboard(acc_id, page, selected_channels)
    await callback.message.edit_reply_markup(reply_markup=keyboard)
    await callback.answer()

@dp.callback_query(F.data == "confirm_channels", CommentStates.selecting_channels)
async def confirm_channels(callback: CallbackQuery, state: FSMContext):
    """
    Подтверждение выбора каналов.
    Запрашивает текст комментария, который будет оставляться под постами.
    """
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
    """
    Запуск автокомментатора.
    Сохраняет настройки и запускает фоновый процесс отслеживания постов.
    """
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
    
    # Получаем реальные chat_id выбранных каналов
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
    
    # Запускаем комментатор
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
    
    # Запускаем в фоновом режиме
    asyncio.create_task(run_commentator(message.from_user.id, account, channel_ids, comment_text))
    await state.clear()

async def run_commentator(user_id: int, account: Dict, channel_ids: List[int], comment_text: str):
    """
    Фоновый процесс автокомментирования.
    Подключается к аккаунту и отслеживает новые посты в выбранных каналах.
    При обнаружении нового поста оставляет заданный комментарий.
    """
    try:
        # Подключаемся к аккаунту
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
        
        # Обработчик новых сообщений
        @client.on(events.NewMessage(chats=channel_ids))
        async def handler(event):
            # Проверяем, не остановлен ли процесс
            if user_id not in active_commentators or active_commentators[user_id]["stop"]:
                return
            
            try:
                # Небольшая задержка для имитации живого человека
                await asyncio.sleep(2)
                
                if user_id not in active_commentators or active_commentators[user_id]["stop"]:
                    return
                
                # Оставляем комментарий под постом
                await client.send_message(
                    entity=event.chat_id,
                    message=comment_text,
                    parse_mode='html',
                    comment_to=event.message.id  # Отвечаем на сообщение (комментарий)
                )
                
                logger.info(f"Comment posted in {event.chat_id}")
                
            except Exception as e:
                logger.error(f"Comment posting error: {e}")
        
        # Держим соединение активным, пока процесс не остановят
        while user_id in active_commentators and not active_commentators[user_id]["stop"]:
            await asyncio.sleep(1)
        
        # Удаляем обработчик при остановке
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
    """Остановка процесса автокомментирования"""
    if callback.from_user.id in active_commentators:
        active_commentators[callback.from_user.id]["stop"] = True
        await callback.answer("Останавливаю автокомментарии...", show_alert=True)
    else:
        await callback.answer("Нет активных автокомментариев", show_alert=True)

@dp.callback_query(F.data == "none")
async def none_callback(callback: CallbackQuery):
    """Заглушка для неактивных кнопок"""
    await callback.answer()

# ===== ЗАПУСК БОТА =====

async def main():
    """
    Главная функция запуска бота.
    Инициализирует базу данных и запускает polling обновлений.
    """
    logger.info("Starting Vest Traffer 2 bot...")
    
    # Инициализируем базу данных
    await db.init()
    
    logger.info("Bot started successfully!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
