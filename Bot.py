import asyncio
import logging
import sqlite3
import os
import json
from datetime import datetime
from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
    WebAppInfo, ReplyKeyboardMarkup, KeyboardButton,
    ReplyKeyboardRemove, PhotoSize, Document
)
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# =================== КОНФИГУРАЦИЯ ===================
BOT_TOKEN = os.getenv("BOT_TOKEN", "8381986284:AAHhJWbm3b0dAep7lpIw2porfmQEt2-vvw0")
ADMIN_ID = int(os.getenv("ADMIN_ID", "7725796090"))
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://artureooe.github.io/Jsjjeje/")

# Начальные цены (полностью по сайту)
PRICES = {
    "star_rate": 1.45,      # ₽ за звезду
    "ton_rate": 149.0,      # ₽ за TON (было 167, исправлено на 149 как на сайте)
    "premium_3": 15,        # USDT за 3 месяца
    "premium_6": 19,        # USDT за 6 месяцев
    "premium_12": 28        # USDT за 12 месяцев
}

# Крипто-боты (по сайту)
CRYPTO_BOT_LINKS = {
    "stars": "http://t.me/send?start=IVokAO7ctuXg",
    "premium_3": "http://t.me/send?start=IV5IHNwgpM4N",
    "premium_6": "http://t.me/send?start=IVeOFirLP2TH",
    "premium_12": "http://t.me/send?start=IVnDUj6uGHGb",
    "ton": "http://t.me/send?start=IVSio1teZ6JJ"
}

# BEP20 кошелек (по сайту)
BEP20_WALLET = "0x798236f6980A595FE823b595d71816Dc713fAFdE"

# =================== БАЗА ДАННЫХ ===================
class Database:
    def __init__(self):
        db_path = os.path.join(os.path.expanduser('~'), 'art_stars_full.db')
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.create_tables()
        self.load_prices()
        print(f"📦 База данных: {db_path}")
    
    def create_tables(self):
        cursor = self.conn.cursor()
        
        # Пользователи
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                full_name TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Заказы (добавлены новые поля)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                product TEXT,
                quantity REAL,
                total REAL,
                currency TEXT,
                username TEXT,
                payment_method TEXT,
                crypto_bot_link TEXT,
                bep20_wallet TEXT,
                screenshot TEXT,
                status TEXT DEFAULT 'pending',
                admin_comment TEXT,
                completed_by INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # ТП-админы с уровнями
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS support_admins (
                user_id INTEGER PRIMARY KEY,
                added_by INTEGER,
                admin_level INTEGER DEFAULT 1,  -- 1 = ТП, 2 = Админ
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Заявки поддержки
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS support_tickets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                user_name TEXT,
                message TEXT,
                file_id TEXT,
                file_type TEXT,
                status TEXT DEFAULT 'new',
                admin_id INTEGER,
                admin_name TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Ответы на заявки поддержки
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS ticket_replies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticket_id INTEGER,
                admin_id INTEGER,
                admin_name TEXT,
                message TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Настройки (цены)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        ''')
        
        # Главный админ (уровень 2)
        cursor.execute('INSERT OR IGNORE INTO support_admins (user_id, added_by, admin_level) VALUES (?, ?, ?)', 
                      (ADMIN_ID, ADMIN_ID, 2))
        
        # Начальные цены
        for key, value in PRICES.items():
            cursor.execute('INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)', 
                          (key, str(value)))
        
        # Индексы для производительности
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_orders_user_id ON orders(user_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_tickets_status ON support_tickets(status)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_tickets_user_id ON support_tickets(user_id)')
        
        self.conn.commit()
        print("✅ Таблицы созданы/обновлены")
    
    def load_prices(self):
        cursor = self.conn.cursor()
        cursor.execute('SELECT key, value FROM settings')
        for key, value in cursor.fetchall():
            if key in PRICES:
                try:
                    PRICES[key] = float(value)
                except:
                    PRICES[key] = value
        print("💰 Цены загружены")
    
    def update_price(self, key, value):
        cursor = self.conn.cursor()
        cursor.execute('INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)', 
                      (key, str(value)))
        self.conn.commit()
        PRICES[key] = value
        return True
    
    def add_user(self, user_id, username, full_name):
        cursor = self.conn.cursor()
        cursor.execute('''
            INSERT OR IGNORE INTO users (user_id, username, full_name)
            VALUES (?, ?, ?)
        ''', (user_id, username, full_name))
        self.conn.commit()
    
    def get_admin_level(self, user_id):
        """Возвращает уровень админа: 0 = не админ, 1 = ТП, 2 = Админ"""
        cursor = self.conn.cursor()
        cursor.execute('SELECT admin_level FROM support_admins WHERE user_id = ?', (user_id,))
        result = cursor.fetchone()
        return result[0] if result else 0
    
    def is_support_admin(self, user_id):
        """Проверяет, является ли пользователь ТП или Админом (уровень 1 или 2)"""
        return self.get_admin_level(user_id) >= 1
    
    def is_admin(self, user_id):
        """Проверяет, является ли пользователь Админом (уровень 2)"""
        return self.get_admin_level(user_id) >= 2
    
    def add_support_admin(self, admin_id, added_by, admin_level=1):
        cursor = self.conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO support_admins (user_id, added_by, admin_level)
            VALUES (?, ?, ?)
        ''', (admin_id, added_by, admin_level))
        self.conn.commit()
        return True
    
    def update_admin_level(self, admin_id, new_level):
        cursor = self.conn.cursor()
        cursor.execute('''
            UPDATE support_admins 
            SET admin_level = ?
            WHERE user_id = ?
        ''', (new_level, admin_id))
        self.conn.commit()
        return cursor.rowcount > 0
    
    def remove_support_admin(self, admin_id):
        cursor = self.conn.cursor()
        cursor.execute('DELETE FROM support_admins WHERE user_id = ?', (admin_id,))
        self.conn.commit()
        return cursor.rowcount > 0
    
    def get_all_support_admins(self):
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT sa.user_id, u.username, u.full_name, sa.admin_level, sa.added_at 
            FROM support_admins sa
            LEFT JOIN users u ON sa.user_id = u.user_id
            ORDER BY sa.admin_level DESC, sa.added_at
        ''')
        return cursor.fetchall()
    
    def create_support_ticket(self, user_id, user_name, message, file_id=None, file_type=None):
        cursor = self.conn.cursor()
        cursor.execute('''
            INSERT INTO support_tickets (user_id, user_name, message, file_id, file_type)
            VALUES (?, ?, ?, ?, ?)
        ''', (user_id, user_name, message, file_id, file_type))
        self.conn.commit()
        return cursor.lastrowid
    
    def get_new_tickets(self):
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT * FROM support_tickets 
            WHERE status = 'new'
            ORDER BY created_at DESC
        ''')
        return cursor.fetchall()
    
    def get_my_tickets(self, admin_id):
        """Получить заявки, взятые в работу конкретным админом"""
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT * FROM support_tickets 
            WHERE admin_id = ? AND status = 'in_progress'
            ORDER BY created_at DESC
        ''', (admin_id,))
        return cursor.fetchall()
    
    def get_all_tickets(self):
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT * FROM support_tickets 
            ORDER BY created_at DESC
        ''')
        return cursor.fetchall()
    
    def get_ticket_by_id(self, ticket_id):
        cursor = self.conn.cursor()
        cursor.execute('SELECT * FROM support_tickets WHERE id = ?', (ticket_id,))
        return cursor.fetchone()
    
    def assign_ticket(self, ticket_id, admin_id, admin_name):
        cursor = self.conn.cursor()
        cursor.execute('''
            UPDATE support_tickets 
            SET status = 'in_progress', admin_id = ?, admin_name = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (admin_id, admin_name, ticket_id))
        self.conn.commit()
    
    def close_ticket(self, ticket_id):
        cursor = self.conn.cursor()
        cursor.execute('''
            UPDATE support_tickets 
            SET status = 'closed', updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (ticket_id,))
        self.conn.commit()
    
    def add_ticket_reply(self, ticket_id, admin_id, admin_name, message):
        cursor = self.conn.cursor()
        cursor.execute('''
            INSERT INTO ticket_replies (ticket_id, admin_id, admin_name, message)
            VALUES (?, ?, ?, ?)
        ''', (ticket_id, admin_id, admin_name, message))
        self.conn.commit()
    
    def get_ticket_replies(self, ticket_id):
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT * FROM ticket_replies 
            WHERE ticket_id = ?
            ORDER BY created_at ASC
        ''', (ticket_id,))
        return cursor.fetchall()
    
    def create_order(self, user_id, product, quantity, total, currency, username, 
                     payment_method=None, crypto_bot_link=None, bep20_wallet=None, screenshot=None):
        cursor = self.conn.cursor()
        cursor.execute('''
            INSERT INTO orders (user_id, product, quantity, total, currency, username, 
                              payment_method, crypto_bot_link, bep20_wallet, screenshot)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (user_id, product, quantity, total, currency, username, 
              payment_method, crypto_bot_link, bep20_wallet, screenshot))
        self.conn.commit()
        return cursor.lastrowid
    
    def get_orders_by_user(self, user_id):
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT * FROM orders 
            WHERE user_id = ? 
            ORDER BY created_at DESC
        ''', (user_id,))
        return cursor.fetchall()
    
    def get_all_orders(self):
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT o.*, u.username, u.full_name 
            FROM orders o
            LEFT JOIN users u ON o.user_id = u.user_id
            ORDER BY o.created_at DESC
        ''')
        return cursor.fetchall()
    
    def get_pending_orders(self):
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT o.*, u.username, u.full_name 
            FROM orders o
            LEFT JOIN users u ON o.user_id = u.user_id
            WHERE o.status = 'pending'
            ORDER BY o.created_at DESC
        ''')
        return cursor.fetchall()
    
    def get_order_by_id(self, order_id):
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT o.*, u.username, u.full_name 
            FROM orders o
            LEFT JOIN users u ON o.user_id = u.user_id
            WHERE o.id = ?
        ''', (order_id,))
        return cursor.fetchone()
    
    def update_order_status(self, order_id, status, admin_id=None, comment=None):
        cursor = self.conn.cursor()
        if admin_id:
            cursor.execute('''
                UPDATE orders 
                SET status = ?, completed_by = ?, admin_comment = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (status, admin_id, comment, order_id))
        else:
            cursor.execute('''
                UPDATE orders 
                SET status = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (status, order_id))
        self.conn.commit()
        return cursor.rowcount > 0
    
    def get_stats(self):
        cursor = self.conn.cursor()
        
        cursor.execute('SELECT COUNT(*) FROM users')
        users = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM orders')
        orders = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM orders WHERE status = "pending"')
        pending_orders = cursor.fetchone()[0]
        
        cursor.execute('SELECT SUM(total) FROM orders WHERE status = "completed" AND currency = "RUB"')
        total_rub = cursor.fetchone()[0] or 0
        
        cursor.execute('SELECT SUM(total) FROM orders WHERE status = "completed" AND currency = "USDT"')
        total_usdt = cursor.fetchone()[0] or 0
        
        cursor.execute('SELECT COUNT(*) FROM support_tickets WHERE status = "new"')
        new_tickets = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM support_admins WHERE admin_level >= 1')
        all_admins = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM support_admins WHERE admin_level = 1')
        support_admins = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM support_admins WHERE admin_level = 2')
        full_admins = cursor.fetchone()[0]
        
        return {
            'users': users,
            'orders': orders,
            'pending_orders': pending_orders,
            'total_rub': round(total_rub, 2),
            'total_usdt': round(total_usdt, 2),
            'new_tickets': new_tickets,
            'all_admins': all_admins,
            'support_admins': support_admins,
            'full_admins': full_admins,
            'prices': PRICES
        }

# =================== FSM СОСТОЯНИЯ ===================
class Form(StatesGroup):
    waiting_support_message = State()
    admin_reply = State()
    waiting_new_admin = State()
    waiting_remove_admin = State()
    waiting_set_price = State()
    waiting_change_admin_level = State()
    waiting_order_username = State()
    waiting_screenshot = State()
    waiting_quantity = State()  # Для ввода количества
    waiting_admin_comment = State()  # Для комментария админа

# =================== ИНИЦИАЛИЗАЦИЯ ===================
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
router = Router()
dp.include_router(router)

db = Database()

# =================== КЛАВИАТУРЫ ===================
def main_menu(user_id):
    admin_level = db.get_admin_level(user_id)
    
    if admin_level >= 1:
        keyboard = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="🛍️ Магазин"), KeyboardButton(text="🛒 Мои заказы")],
                [KeyboardButton(text="💰 Курсы"), KeyboardButton(text="🆘 Техподдержка")],
                [KeyboardButton(text="👑 Админ-панель")]
            ],
            resize_keyboard=True
        )
    else:
        keyboard = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="🛍️ Магазин"), KeyboardButton(text="🛒 Мои заказы")],
                [KeyboardButton(text="💰 Курсы"), KeyboardButton(text="🆘 Техподдержка")]
            ],
            resize_keyboard=True
        )
    return keyboard

def shop_keyboard():
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="⭐ Звёзды", callback_data="buy_stars"),
                InlineKeyboardButton(text="👑 Premium", callback_data="buy_premium")
            ],
            [
                InlineKeyboardButton(text="💎 TON", callback_data="buy_ton"),
                InlineKeyboardButton(text="🌐 Веб-магазин", web_app=WebAppInfo(url=WEBAPP_URL))
            ],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main")]
        ]
    )
    return keyboard

def premium_options_keyboard():
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="3 мес - 15 USDT", callback_data="premium_3"),
                InlineKeyboardButton(text="6 мес - 19 USDT", callback_data="premium_6")
            ],
            [
                InlineKeyboardButton(text="12 мес - 28 USDT", callback_data="premium_12"),
                InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_shop")
            ]
        ]
    )
    return keyboard

def payment_methods_keyboard():
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🤖 Crypto Bot", callback_data="pay_crypto_bot"),
                InlineKeyboardButton(text="💼 BEP20", callback_data="pay_bep20")
            ],
            [
                InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_shop"),
                InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")
            ]
        ]
    )
    return keyboard

def admin_menu(user_level):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Новые заявки", callback_data="admin_new_tickets")],
        [InlineKeyboardButton(text="📝 Мои заявки", callback_data="admin_my_tickets")],
        [InlineKeyboardButton(text="📚 Все заявки", callback_data="all_tickets")],
        [InlineKeyboardButton(text="🛒 Новые заказы", callback_data="admin_pending_orders")],
        [InlineKeyboardButton(text="📦 Все заказы", callback_data="admin_all_orders")],
        [InlineKeyboardButton(text="👨‍💼 Управление ТП", callback_data="admin_manage_support")],
        [InlineKeyboardButton(text="💰 Управление ценами", callback_data="admin_manage_prices")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")]
    ])
    
    # Только для админов (уровень 2)
    if user_level >= 2:
        keyboard.inline_keyboard.append(
            [InlineKeyboardButton(text="🔐 Управление уровнями", callback_data="admin_manage_levels")]
        )
    
    return keyboard

def support_management_menu(user_level):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить ТП-админа", callback_data="admin_add_support")],
        [InlineKeyboardButton(text="➖ Удалить ТП-админа", callback_data="admin_remove_support")],
        [InlineKeyboardButton(text="📝 Список ТП-админов", callback_data="admin_list_support")]
    ])
    
    if user_level >= 2:
        keyboard.inline_keyboard.append(
            [InlineKeyboardButton(text="📊 Управление уровнями", callback_data="admin_manage_levels")]
        )
    
    keyboard.inline_keyboard.append(
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_back")]
    )
    
    return keyboard

def levels_management_menu():
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Список с уровнями", callback_data="admin_list_with_levels")],
        [InlineKeyboardButton(text="🔼 Повысить уровень", callback_data="admin_promote")],
        [InlineKeyboardButton(text="🔽 Понизить уровень", callback_data="admin_demote")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_manage_support")]
    ])
    return keyboard

def prices_management_menu():
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⭐ Цена звезды", callback_data="price_star")],
            [InlineKeyboardButton(text="💎 Цена TON", callback_data="price_ton")],
            [InlineKeyboardButton(text="🏆 Premium 3 мес", callback_data="price_premium_3")],
            [InlineKeyboardButton(text="🏆 Premium 6 мес", callback_data="price_premium_6")],
            [InlineKeyboardButton(text="🏆 Premium 12 мес", callback_data="price_premium_12")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_back")]
        ]
    )
    return keyboard

def cancel_keyboard():
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")]
        ]
    )
    return keyboard

def order_management_keyboard(order_id):
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"complete_order_{order_id}"),
                InlineKeyboardButton(text="❌ Отменить", callback_data=f"cancel_order_{order_id}")
            ],
            [
                InlineKeyboardButton(text="💬 Комментарий", callback_data=f"comment_order_{order_id}"),
                InlineKeyboardButton(text="📋 Все заказы", callback_data="admin_all_orders")
            ]
        ]
    )
    return keyboard

def ticket_management_keyboard(ticket_id, status):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    
    if status == 'new':
        keyboard.inline_keyboard.append([
            InlineKeyboardButton(text="✅ Взять в работу", callback_data=f"take_ticket_{ticket_id}")
        ])
    elif status == 'in_progress':
        keyboard.inline_keyboard.append([
            InlineKeyboardButton(text="💬 Ответить", callback_data=f"reply_ticket_{ticket_id}")
        ])
    
    keyboard.inline_keyboard.append([
        InlineKeyboardButton(text="✅ Закрыть", callback_data=f"close_ticket_{ticket_id}")
    ])
    
    keyboard.inline_keyboard.append([
        InlineKeyboardButton(text="📚 Все заявки", callback_data="all_tickets"),
        InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_back")
    ])
    
    return keyboard

# =================== ОСНОВНЫЕ КОМАНДЫ ===================
@router.message(CommandStart())
async def cmd_start(message: Message):
    db.add_user(message.from_user.id, 
                message.from_user.username, 
                message.from_user.full_name)
    
    await message.answer(
        "✨ Art Stars - Официальный бот\n\n"
        "Здесь ты можешь:\n"
        "• 🛍️ Купить звёзды, Premium и TON\n"
        "• 💰 Посмотреть курсы\n"
        "• 🛍 Проверить свои заказы\n"
        "• 🆘 Написать в поддержку\n\n"
        "👇 Используй кнопки ниже:",
        reply_markup=main_menu(message.from_user.id)
    )

@router.message(F.text == "🛍️ Магазин")
async def open_shop(message: Message):
    await message.answer(
        "🛍️ Магазин Art Stars\n\n"
        "Что хочешь купить? 👇",
        reply_markup=shop_keyboard()
    )

@router.message(F.text == "💰 Курсы")
async def show_rates(message: Message):
    rates_text = (
        "💰 Текущие курсы:\n\n"
        f"⭐ Звезда: {PRICES['star_rate']}₽\n"
        f"💎 TON: {PRICES['ton_rate']}₽\n"
        f"👑 Premium 3 мес: {PRICES['premium_3']} USDT\n"
        f"👑 Premium 6 мес: {PRICES['premium_6']} USDT\n"
        f"👑 Premium 12 мес: {PRICES['premium_12']} USDT\n\n"
        "🔄 Курсы обновляются автоматически\n"
        "💎 Самый выгодный курс на рынке!"
    )
    await message.answer(rates_text)

@router.message(F.text == "🛒 Мои заказы")
async def my_orders(message: Message):
    orders = db.get_orders_by_user(message.from_user.id)
    
    if not orders:
        await message.answer("📭 У тебя пока нет заказов.\n\nНажми «🛍️ Магазин» чтобы сделать покупку!")
        return
    
    text = "🛒 Твои заказы:\n\n"
    for order in orders[:10]:  # Показываем последние 10 заказов
        status_emoji = {
            'pending': '🕐 Ожидает',
            'processing': '🔄 В обработке',
            'completed': '✅ Выполнен',
            'cancelled': '❌ Отменён'
        }.get(order[7], '❓ Неизвестно')
        
        text += f"📦 Заказ #{order[0]}\n"
        text += f"Товар: {order[2]}\n"
        text += f"Количество: {order[3]} шт\n"
        text += f"Сумма: {order[4]} {order[5]}\n"
        text += f"Статус: {status_emoji}\n"
        
        if order[12]:  # admin_comment
            text += f"Комментарий: {order[12]}\n"
        
        text += f"Дата: {order[13].split()[0] if ' ' in str(order[13]) else order[13][:10]}\n\n"
    
    if len(orders) > 10:
        text += f"... и ещё {len(orders) - 10} заказов"
    
    await message.answer(text)

@router.message(F.text == "👑 Админ-панель")
async def admin_panel_access(message: Message):
    admin_level = db.get_admin_level(message.from_user.id)
    
    if admin_level < 1:
        await message.answer("❌ У тебя нет доступа к админ-панели!", 
                           reply_markup=main_menu(message.from_user.id))
        return
    
    await message.answer(
        f"👑 Админ-панель | Уровень: {'Админ' if admin_level >= 2 else 'ТП'}\n\n"
        "Выбери раздел для управления:",
        reply_markup=admin_menu(admin_level)
    )

# =================== ПОКУПКА ТОВАРОВ ===================
@router.callback_query(F.data == "buy_stars")
async def buy_stars_start(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "⭐ Покупка звёзд\n\n"
        f"Цена: {PRICES['star_rate']}₽ за звезду\n"
        "Минимум: 100 звёзд\n"
        "Максимум: 25,000 звёзд\n\n"
        "Введи количество звёзд (от 100 до 25000):\n\n"
        "Используй /cancel для отмены"
    )
    await state.set_state(Form.waiting_quantity)
    await state.update_data(product_type="stars", min_value=100, max_value=25000)
    await callback.answer()

@router.callback_query(F.data == "buy_premium")
async def buy_premium_start(callback: CallbackQuery):
    await callback.message.edit_text(
        "👑 Покупка Premium\n\n"
        "Выбери срок подписки:",
        reply_markup=premium_options_keyboard()
    )
    await callback.answer()

@router.callback_query(F.data.startswith("premium_"))
async def select_premium_option(callback: CallbackQuery, state: FSMContext):
    months = int(callback.data.split("_")[1])
    price_key = f"premium_{months}"
    price = PRICES[price_key]
    
    await callback.message.edit_text(
        f"👑 Premium на {months} месяцев\n\n"
        f"Цена: {price} USDT\n\n"
        f"Выбери способ оплаты👇",
        reply_markup=payment_methods_keyboard()
    )
    await state.update_data(product_type="premium", months=months, quantity=1, total=price, currency="USDT")
    await callback.answer()

@router.callback_query(F.data == "buy_ton")
async def buy_ton_start(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "💎 Покупка TON\n\n"
        f"Цена: {PRICES['ton_rate']}₽ за TON\n"
        "Минимум: 2 TON\n"
        "Максимум: 165 TON\n\n"
        "Введи количество TON (от 2 до 165):\n\n"
        "Используй /cancel для отмены"
    )
    await state.set_state(Form.waiting_quantity)
    await state.update_data(product_type="ton", min_value=2, max_value=165)
    await callback.answer()

@router.message(Form.waiting_quantity)
async def process_quantity(message: Message, state: FSMContext):
    if message.text and message.text.startswith('/cancel'):
        await state.clear()
        await message.answer("❌ Покупка отменена", 
                           reply_markup=main_menu(message.from_user.id))
        return
    
    data = await state.get_data()
    product_type = data.get('product_type')
    
    try:
        quantity = float(message.text.replace(',', '.'))
        min_val = data.get('min_value')
        max_val = data.get('max_value')
        
        if quantity < min_val or quantity > max_val:
            await message.answer(f"❌ Введи число от {min_val} до {max_val}!")
            return
        
        # Рассчитываем сумму
        if product_type == 'stars':
            total = quantity * PRICES['star_rate']
            product_name = "Звёзды"
            currency = "RUB"
        else:  # ton
            total = quantity * PRICES['ton_rate']
            product_name = "TON"
            currency = "RUB"
        
        await state.update_data(
            quantity=quantity,
            total=total,
            product_name=product_name,
            currency=currency
        )
        
        await message.answer(
            f"✅ {product_name}: {quantity} шт\n"
            f"💰 Сумма: {total:.2f} {currency}\n\n"
            f"Выбери способ оплаты👇",
            reply_markup=payment_methods_keyboard()
        )
        await state.set_state(Form.waiting_screenshot)
        
    except ValueError:
        await message.answer("❌ Введи число! Например: 1000 или 5.5")

# =================== ВЫБОР СПОСОБА ОПЛАТЫ ===================
@router.callback_query(F.data.startswith("pay_"))
async def select_payment_method(callback: CallbackQuery, state: FSMContext):
    payment_method = callback.data.split("_")[1]
    data = await state.get_data()
    
    if payment_method == "crypto_bot":
        # Получаем ссылку на крипто-бота
        product_type = data.get('product_type')
        crypto_bot_link = ""
        
        if product_type == "stars":
            crypto_bot_link = CRYPTO_BOT_LINKS["stars"]
            product_name = "Звёзды"
        elif product_type == "premium":
            months = data.get('months')
            crypto_bot_link = CRYPTO_BOT_LINKS[f"premium_{months}"]
            product_name = f"Premium {months} мес"
        elif product_type == "ton":
            crypto_bot_link = CRYPTO_BOT_LINKS["ton"]
            product_name = "TON"
        
        await callback.message.edit_text(
            f"🤖 Оплата через Crypto Bot\n\n"
            f"📦 Товар: {product_name}\n"
            f"💰 Сумма: {data.get('total', 0)} {data.get('currency', '')}\n\n"
            f"1. Нажми на кнопку ниже\n"
            f"2. В открывшемся боте нажми START\n"
            f"3. Оплати указанную сумму\n"
            f"4. Вернись сюда и отправь скриншот оплаты\n\n"
            f"📸 После оплаты пришли скриншот сюда!",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="🤖 Перейти к оплате", url=crypto_bot_link)],
                    [InlineKeyboardButton(text="📸 У меня есть скриншот", callback_data="ready_screenshot")],
                    [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")]
                ]
            )
        )
        await state.update_data(
            payment_method="crypto_bot", 
            crypto_bot_link=crypto_bot_link,
            product_name=product_name
        )
    
    elif payment_method == "bep20":
        product_type = data.get('product_type')
        if product_type == "stars":
            product_name = "Звёзды"
        elif product_type == "premium":
            months = data.get('months')
            product_name = f"Premium {months} мес"
        elif product_type == "ton":
            product_name = "TON"
        else:
            product_name = "Товар"
        
        await callback.message.edit_text(
            f"💼 Оплата через BEP20 (BSC)\n\n"
            f"📦 Товар: {product_name}\n"
            f"💰 Сумма: {data.get('total', 0)} USDT\n\n"
            f"1. Отправь {data.get('total', 0)} USDT на адрес:\n"
            f"<code>{BEP20_WALLET}</code>\n\n"
            f"2. Обязательно отправляй только USDT в сети BEP20!\n"
            f"3. После отправки пришли скриншот подтверждения\n\n"
            f"⚠️ ВАЖНО: Отправляй только USDT (BEP20)!\n\n"
            f"📸 После оплаты пришли скриншот сюда!",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="📋 Скопировать адрес", callback_data="copy_wallet")],
                    [InlineKeyboardButton(text="📸 У меня есть скриншот", callback_data="ready_screenshot")],
                    [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")]
                ]
            )
        )
        await state.update_data(
            payment_method="bep20", 
            bep20_wallet=BEP20_WALLET,
            product_name=product_name
        )
    
    await callback.answer()

@router.callback_query(F.data == "copy_wallet")
async def copy_wallet_address(callback: CallbackQuery):
    await callback.answer("Адрес скопирован в буфер обмена! Отправляй только USDT (BEP20)", show_alert=True)

@router.callback_query(F.data == "ready_screenshot")
async def request_screenshot(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer(
        "📸 Пришли скриншот подтверждения оплаты:\n\n"
        "1. Сделай скриншот успешной оплаты\n"
        "2. Отправь его сюда как фото\n"
        "3. Подожди подтверждения от администратора\n\n"
        "Используй /cancel для отмены"
    )
    await callback.answer()

# =================== ОБРАБОТКА СКРИНШОТОВ ===================
@router.message(Form.waiting_screenshot)
async def process_screenshot(message: Message, state: FSMContext):
    if message.text and message.text.startswith('/cancel'):
        await state.clear()
        await message.answer("❌ Покупка отменена", 
                           reply_markup=main_menu(message.from_user.id))
        return
    
    # Проверяем, есть ли фото
    if not message.photo:
        await message.answer("❌ Пожалуйста, отправь скриншот как фото!")
        return
    
    data = await state.get_data()
    
    # Получаем информацию о файле
    file_id = message.photo[-1].file_id
    file_type = "photo"
    
    # Создаем заказ в базе
    order_id = db.create_order(
        message.from_user.id,
        data.get('product_name', 'Товар'),
        data.get('quantity', 0),
        data.get('total', 0),
        data.get('currency', ''),
        message.from_user.username or "",
        data.get('payment_method'),
        data.get('crypto_bot_link'),
        data.get('bep20_wallet'),
        f"{file_id}_{file_type}"  # Сохраняем ID файла
    )
    
    # Отправляем уведомление всем админам (и ТП и Админам)
    admins = db.get_all_support_admins()
    
    for admin in admins:
        try:
            await bot.send_photo(
                admin[0],
                photo=file_id,
                caption=(
                    f"🛒 НОВЫЙ ЗАКАЗ #{order_id}\n\n"
                    f"👤 Клиент: {message.from_user.full_name or 'Без имени'}\n"
                    f"🆔 ID: {message.from_user.id}\n"
                    f"📦 Товар: {data.get('product_name', 'Товар')}\n"
                    f"📊 Количество: {data.get('quantity', 0)}\n"
                    f"💰 Сумма: {data.get('total', 0)} {data.get('currency', '')}\n"
                    f"💳 Способ: {'Crypto Bot' if data.get('payment_method') == 'crypto_bot' else 'BEP20'}\n"
                    f"📝 Username: @{message.from_user.username or 'нет'}\n\n"
                    f"Ожидает проверки и подтверждения!\n"
                    f"Для управления: /order_{order_id}"
                )
            )
        except Exception as e:
            print(f"Не удалось отправить админу {admin[0]}: {e}")
    
    await message.answer(
        f"✅ Заказ #{order_id} создан!\n\n"
        f"📦 Товар: {data.get('product_name', 'Товар')}\n"
        f"💰 Сумма: {data.get('total', 0)} {data.get('currency', '')}\n"
        f"💳 Способ: {'Crypto Bot' if data.get('payment_method') == 'crypto_bot' else 'BEP20'}\n\n"
        f"Администратор проверит оплату и активирует заказ в течение 15 минут.\n"
        f"Следи за уведомлениями! 🎉",
        reply_markup=main_menu(message.from_user.id)
    )
    
    await state.clear()

# =================== ТЕХПОДДЕРЖКА ===================
@router.message(F.text == "🆘 Техподдержка")
async def support_start(message: Message, state: FSMContext):
    await message.answer(
        "🆘 Техническая поддержка\n\n"
        "Опиши свою проблему:\n"
        "• Проблема с оплатой\n"
        "• Не пришёл товар\n"
        "• Вопрос по заказу\n"
        "• Другое\n\n"
        "Можешь прикрепить фото/документ\n\n"
        "Просто напиши сообщение ниже ⬇️\n\n"
        "Используй /cancel для отмены",
        reply_markup=ReplyKeyboardRemove()
    )
    await state.set_state(Form.waiting_support_message)

@router.message(Form.waiting_support_message)
async def support_message_received(message: Message, state: FSMContext):
    if message.text and message.text.startswith('/cancel'):
        await state.clear()
        await message.answer("❌ Создание заявки отменено", 
                           reply_markup=main_menu(message.from_user.id))
        return
    
    # Получаем текст сообщения или описание вложения
    user_message = message.text or message.caption or "📎 Вложение"
    
    # Очищаем сообщение от markdown символов
    if isinstance(user_message, str):
        clean_text = user_message.replace('*', '').replace('_', '').replace('`', '').replace('[', '').replace(']', '')
    else:
        clean_text = str(user_message)
    
    # Получаем информацию о файле, если есть
    file_id = None
    file_type = None
    
    if message.photo:
        file_id = message.photo[-1].file_id
        file_type = "photo"
        if not clean_text or clean_text == "📎 Вложение":
            clean_text = "📸 Фото"
    elif message.document:
        file_id = message.document.file_id
        file_type = "document"
        doc_name = message.document.file_name or "документ"
        if not clean_text or clean_text == "📎 Вложение":
            clean_text = f"📎 Файл: {doc_name}"
    
    # Создаём заявку
    ticket_id = db.create_support_ticket(
        message.from_user.id,
        message.from_user.full_name or f"User_{message.from_user.id}",
        clean_text,
        file_id,
        file_type
    )
    
    # Отправляем всем админам уведомление (и ТП и Админам)
    admins = db.get_all_support_admins()
    
    for admin in admins:
        try:
            # Если есть файл - отправляем его
            if file_id:
                if file_type == "photo":
                    await bot.send_photo(
                        admin[0],
                        photo=file_id,
                        caption=(
                            f"🆘 НОВАЯ ЗАЯВКА #{ticket_id}\n\n"
                            f"👤 Клиент: {message.from_user.full_name or 'Без имени'}\n"
                            f"🆔 ID: {message.from_user.id}\n"
                            f"📝 Сообщение: {clean_text[:100]}...\n\n"
                            f"Для ответа нажми: /ticket_{ticket_id}"
                        )
                    )
                elif file_type == "document":
                    await bot.send_document(
                        admin[0],
                        document=file_id,
                        caption=(
                            f"🆘 НОВАЯ ЗАЯВКА #{ticket_id}\n\n"
                            f"👤 Клиент: {message.from_user.full_name or 'Без имени'}\n"
                            f"🆔 ID: {message.from_user.id}\n"
                            f"📝 Сообщение: {clean_text[:100]}...\n\n"
                            f"Для ответа нажми: /ticket_{ticket_id}"
                        )
                    )
            else:
                # Если нет файла - просто текст
                await bot.send_message(
                    admin[0],
                    (
                        f"🆘 НОВАЯ ЗАЯВКА #{ticket_id}\n\n"
                        f"👤 Клиент: {message.from_user.full_name or 'Без имени'}\n"
                        f"🆔 ID: {message.from_user.id}\n"
                        f"📝 Сообщение: {clean_text[:200]}...\n\n"
                        f"Для ответа нажми: /ticket_{ticket_id}"
                    )
                )
        except Exception as e:
            print(f"Не удалось отправить админу {admin[0]}: {e}")
    
    # Ответ пользователю
    await message.answer(
        f"✅ Заявка создана!\n\n"
        f"Номер: #{ticket_id}\n"
        "ТП-админы уже получили твоё сообщение и скоро ответят.\n\n"
        "Жди ответа здесь в чате!",
        reply_markup=main_menu(message.from_user.id)
    )
    await state.clear()

# =================== КОМАНДЫ ДЛЯ АДМИНОВ ===================
@router.message(F.text.startswith("/ticket_"))
async def admin_view_ticket(message: Message):
    if not db.is_support_admin(message.from_user.id):
        await message.answer("❌ Ты не ТП-админ!")
        return
    
    try:
        ticket_id = int(message.text.split("_")[1])
        ticket = db.get_ticket_by_id(ticket_id)
        
        if not ticket:
            await message.answer("❌ Заявка не найдена!")
            return
        
        # Показываем детали заявки
        await show_ticket_details(message, ticket_id, ticket)
        
    except:
        await message.answer("❌ Ошибка! Используй: /ticket_номер")

async def show_ticket_details(message: Message, ticket_id, ticket=None):
    if not ticket:
        ticket = db.get_ticket_by_id(ticket_id)
    
    if not ticket:
        await message.answer("❌ Заявка не найдена!")
        return
    
    # Форматируем текст заявки
    has_file = ticket[4] is not None  # file_id
    file_info = ""
    
    if has_file:
        if ticket[5] == "photo":
            file_info = "📸 Есть фото"
        elif ticket[5] == "document":
            file_info = "📎 Есть документ"
    
    # Получаем ответы на заявку
    replies = db.get_ticket_replies(ticket_id)
    
    text = (
        f"🆘 Заявка #{ticket[0]}\n\n"
        f"👤 Клиент: {ticket[2]}\n"
        f"🆔 ID: {ticket[1]}\n"
        f"📅 Создана: {ticket[9].split()[0] if ' ' in str(ticket[9]) else ticket[9][:10]}\n"
        f"📊 Статус: {ticket[6]}\n"
        f"{file_info}\n"
    )
    
    if ticket[7]:  # admin_id
        text += f"👨‍💼 Админ: {ticket[8] or 'Не указан'}\n"
    
    text += f"\n📝 Сообщение клиента:\n{ticket[3]}\n"
    
    if replies:
        text += f"\n📋 Ответы ({len(replies)}):\n"
        for reply in replies:
            text += f"\n👨‍💼 {reply[3]} ({reply[5].split()[1][:5]}):\n{reply[4]}\n"
    
    # Отправляем с кнопками управления
    if has_file and ticket[4]:
        try:
            if ticket[5] == "photo":
                await bot.send_photo(
                    message.chat.id,
                    photo=ticket[4],
                    caption=text,
                    reply_markup=ticket_management_keyboard(ticket_id, ticket[6])
                )
            elif ticket[5] == "document":
                await bot.send_document(
                    message.chat.id,
                    document=ticket[4],
                    caption=text,
                    reply_markup=ticket_management_keyboard(ticket_id, ticket[6])
                )
        except:
            await message.answer(
                text + "\n\n⚠️ Файл не доступен",
                reply_markup=ticket_management_keyboard(ticket_id, ticket[6])
            )
    else:
        await message.answer(
            text,
            reply_markup=ticket_management_keyboard(ticket_id, ticket[6])
        )

@router.message(F.text.startswith("/order_"))
async def admin_view_order(message: Message):
    if not db.is_support_admin(message.from_user.id):
        await message.answer("❌ Ты не ТП-админ!")
        return
    
    try:
        order_id = int(message.text.split("_")[1])
        await show_order_admin(message, order_id)
        
    except:
        await message.answer("❌ Ошибка! Используй: /order_номер")

async def show_order_admin(message: Message, order_id):
    order = db.get_order_by_id(order_id)
    
    if not order:
        await message.answer("❌ Заказ не найден!")
        return
    
    # Форматируем статус
    status_emoji = {
        'pending': '🕐 Ожидает',
        'processing': '🔄 В обработке',
        'completed': '✅ Выполнен',
        'cancelled': '❌ Отменён'
    }.get(order[7], '❓ Неизвестно')
    
    payment_method = {
        'crypto_bot': '🤖 Crypto Bot',
        'bep20': '💼 BEP20'
    }.get(order[8], 'Не указан')
    
    text = (
        f"🛒 Заказ #{order[0]}\n\n"
        f"{status_emoji}\n"
        f"👤 Клиент: {order[18] or 'Без имени'} (@{order[17] or 'нет'})\n"
        f"🆔 ID: {order[1]}\n"
        f"📦 Товар: {order[2]}\n"
        f"📊 Количество: {order[3]}\n"
        f"💰 Сумма: {order[4]} {order[5]}\n"
        f"💳 Способ: {payment_method}\n"
        f"📅 Дата: {order[13].split()[0] if ' ' in str(order[13]) else order[13][:10]}\n"
    )
    
    if order[12]:  # admin_comment
        text += f"💬 Комментарий: {order[12]}\n"
    
    if order[11]:  # screenshot
        text += f"📸 Есть скриншот оплаты\n"
    
    await message.answer(
        text,
        reply_markup=order_management_keyboard(order_id)
    )

# =================== УПРАВЛЕНИЕ ЗАЯВКАМИ ===================
@router.callback_query(F.data == "admin_new_tickets")
async def show_new_tickets(callback: CallbackQuery):
    if not db.is_support_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа!")
        return
    
    tickets = db.get_new_tickets()
    
    if not tickets:
        await callback.message.edit_text(
            "✅ Нет новых заявок!\n\n"
            "Все заявки обработаны 🎉",
            reply_markup=admin_menu(db.get_admin_level(callback.from_user.id))
        )
        await callback.answer()
        return
    
    # Показываем первую заявку
    await show_ticket_details_callback(callback, tickets[0][0])
    await callback.answer()

async def show_ticket_details_callback(callback: CallbackQuery, ticket_id):
    ticket = db.get_ticket_by_id(ticket_id)
    
    if not ticket:
        await callback.message.edit_text("❌ Заявка не найдена!", 
                                       reply_markup=admin_menu(db.get_admin_level(callback.from_user.id)))
        return
    
    # Форматируем текст заявки
    has_file = ticket[4] is not None  # file_id
    file_info = ""
    
    if has_file:
        if ticket[5] == "photo":
            file_info = "📸 Есть фото"
        elif ticket[5] == "document":
            file_info = "📎 Есть документ"
    
    # Получаем ответы на заявку
    replies = db.get_ticket_replies(ticket_id)
    
    text = (
        f"🆘 Заявка #{ticket[0]}\n\n"
        f"👤 Клиент: {ticket[2]}\n"
        f"🆔 ID: {ticket[1]}\n"
        f"📅 Создана: {ticket[9].split()[0] if ' ' in str(ticket[9]) else ticket[9][:10]}\n"
        f"📊 Статус: {ticket[6]}\n"
        f"{file_info}\n"
    )
    
    if ticket[7]:  # admin_id
        text += f"👨‍💼 Админ: {ticket[8] or 'Не указан'}\n"
    
    text += f"\n📝 Сообщение клиента:\n{ticket[3]}\n"
    
    if replies:
        text += f"\n📋 Ответы ({len(replies)}):\n"
        for reply in replies:
            text += f"\n👨‍💼 {reply[3]} ({reply[5].split()[1][:5]}):\n{reply[4]}\n"
    
    # Обрезаем текст если слишком длинный
    if len(text) > 4000:
        text = text[:4000] + "\n\n... (сообщение слишком длинное)"
    
    # Для callback_query мы не можем отправлять фото, только текст
    await callback.message.edit_text(
        text,
        reply_markup=ticket_management_keyboard(ticket_id, ticket[6])
    )

@router.callback_query(F.data == "admin_my_tickets")
async def show_my_tickets(callback: CallbackQuery):
    if not db.is_support_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа!")
        return
    
    tickets = db.get_my_tickets(callback.from_user.id)
    
    if not tickets:
        await callback.message.edit_text(
            "📭 У тебя нет заявок в работе.\n\n"
            "Возьми заявку из «Новых заявок»!",
            reply_markup=admin_menu(db.get_admin_level(callback.from_user.id))
        )
        await callback.answer()
        return
    
    # Показываем первую заявку
    await show_ticket_details_callback(callback, tickets[0][0])
    await callback.answer()

@router.callback_query(F.data.startswith("take_ticket_"))
async def take_ticket(callback: CallbackQuery):
    if not db.is_support_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа!")
        return
    
    try:
        ticket_id = int(callback.data.split("_")[2])
        db.assign_ticket(ticket_id, callback.from_user.id, callback.from_user.full_name or f"Admin_{callback.from_user.id}")
        
        ticket = db.get_ticket_by_id(ticket_id)
        
        # Уведомляем клиента
        try:
            await bot.send_message(
                ticket[1],
                f"🔄 Заявка #{ticket_id} взята в работу\n\n"
                f"Админ уже рассматривает вашу проблему.\n"
                f"Ответ будет отправлен здесь в чате."
            )
        except:
            pass
        
        await callback.answer(f"✅ Заявка #{ticket_id} взята в работу!")
        await show_ticket_details_callback(callback, ticket_id)
        
    except Exception as e:
        await callback.answer(f"❌ Ошибка: {str(e)}")

@router.callback_query(F.data.startswith("reply_ticket_"))
async def reply_ticket_start(callback: CallbackQuery, state: FSMContext):
    if not db.is_support_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа!")
        return
    
    try:
        ticket_id = int(callback.data.split("_")[2])
        await state.update_data(ticket_id=ticket_id)
        
        await callback.message.answer(
            f"💬 Ответ на заявку #{ticket_id}\n\n"
            f"Напиши ответ для клиента:",
            reply_markup=cancel_keyboard()
        )
        await state.set_state(Form.admin_reply)
        await callback.answer()
        
    except Exception as e:
        await callback.answer(f"❌ Ошибка: {str(e)}")

@router.message(Form.admin_reply)
async def admin_reply_send(message: Message, state: FSMContext):
    data = await state.get_data()
    ticket_id = data['ticket_id']
    ticket = db.get_ticket_by_id(ticket_id)
    
    if not ticket:
        await message.answer("❌ Заявка не найдена!")
        await state.clear()
        return
    
    try:
        reply_text = message.text or "📎 Ответ с вложением"
        
        if isinstance(reply_text, str):
            clean_text = reply_text.replace('*', '').replace('_', '').replace('`', '').replace('[', '').replace(']', '')
        else:
            clean_text = str(reply_text)
        
        # Отправляем ответ клиенту
        await bot.send_message(
            ticket[1],
            f"💬 Ответ от поддержки (заявка #{ticket_id})\n\n"
            f"{clean_text}\n\n"
            f"Если проблема решена — сообщи об этом!"
        )
        
        # Сохраняем ответ в базе
        db.add_ticket_reply(
            ticket_id,
            message.from_user.id,
            message.from_user.full_name or f"Admin_{message.from_user.id}",
            clean_text
        )
        
        await message.answer(
            f"✅ Ответ отправлен клиенту!\n"
            f"Заявка #{ticket_id}",
            reply_markup=main_menu(message.from_user.id)
        )
    except Exception as e:
        await message.answer(f"❌ Не удалось отправить ответ!\nОшибка: {str(e)[:100]}")
    
    await state.clear()

@router.callback_query(F.data.startswith("close_ticket_"))
async def close_ticket(callback: CallbackQuery):
    if not db.is_support_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа!")
        return
    
    try:
        ticket_id = int(callback.data.split("_")[2])
        db.close_ticket(ticket_id)
        
        ticket = db.get_ticket_by_id(ticket_id)
        
        # Уведомляем клиента
        try:
            await bot.send_message(
                ticket[1],
                f"✅ Заявка #{ticket_id} закрыта\n\n"
                f"Если у тебя ещё остались вопросы — создай новую заявку!"
            )
        except:
            pass
        
        await callback.answer(f"✅ Заявка #{ticket_id} закрыта!")
        await callback.message.edit_text(
            f"✅ Заявка #{ticket_id} закрыта!\n\n"
            f"Клиент уведомлён.",
            reply_markup=admin_menu(db.get_admin_level(callback.from_user.id))
        )
        
    except Exception as e:
        await callback.answer(f"❌ Ошибка: {str(e)}")

@router.callback_query(F.data == "all_tickets")
async def show_all_tickets(callback: CallbackQuery):
    if not db.is_support_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа!")
        return
    
    tickets = db.get_all_tickets()
    
    if not tickets:
        await callback.message.edit_text("📋 Заявок нет!", 
                                       reply_markup=admin_menu(db.get_admin_level(callback.from_user.id)))
        await callback.answer()
        return
    
    # Показываем статистику
    new_count = len([t for t in tickets if t[6] == 'new'])
    in_progress_count = len([t for t in tickets if t[6] == 'in_progress'])
    closed_count = len([t for t in tickets if t[6] == 'closed'])
    
    text = f"📋 Все заявки: {len(tickets)}\n\n"
    text += f"🆕 Новых: {new_count}\n"
    text += f"🔄 В работе: {in_progress_count}\n"
    text += f"✅ Закрыто: {closed_count}\n\n"
    
    # Показываем последние 5 заявок
    text += "Последние заявки:\n"
    for i, ticket in enumerate(tickets[:5], 1):
        status_emoji = "🆕" if ticket[6] == 'new' else "🔄" if ticket[6] == 'in_progress' else "✅"
        text += f"{i}. {status_emoji} #{ticket[0]} - {ticket[2]}\n"
    
    if len(tickets) > 5:
        text += f"\n... и ещё {len(tickets) - 5} заявок"
    
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🆕 Новые заявки", callback_data="admin_new_tickets")],
            [InlineKeyboardButton(text="👨‍💼 Мои заявки", callback_data="admin_my_tickets")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_back")]
        ]
    )
    
    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()

# =================== УПРАВЛЕНИЕ ЗАКАЗАМИ (АДМИН) ===================
@router.callback_query(F.data == "admin_pending_orders")
async def show_pending_orders(callback: CallbackQuery):
    if not db.is_support_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа!")
        return
    
    orders = db.get_pending_orders()
    
    if not orders:
        await callback.message.edit_text("✅ Нет новых заказов!", 
                                       reply_markup=admin_menu(db.get_admin_level(callback.from_user.id)))
        await callback.answer()
        return
    
    # Показываем первый заказ
    await show_order_admin_callback(callback, orders[0][0])
    await callback.answer()

@router.callback_query(F.data == "admin_all_orders")
async def show_all_orders(callback: CallbackQuery):
    if not db.is_support_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа!")
        return
    
    orders = db.get_all_orders()
    
    if not orders:
        await callback.message.edit_text("📭 Заказов пока нет!", 
                                       reply_markup=admin_menu(db.get_admin_level(callback.from_user.id)))
        await callback.answer()
        return
    
    # Показываем статистику
    pending_count = len([o for o in orders if o[7] == 'pending'])
    completed_count = len([o for o in orders if o[7] == 'completed'])
    cancelled_count = len([o for o in orders if o[7] == 'cancelled'])
    
    total_rub = sum([o[4] for o in orders if o[5] == 'RUB' and o[7] == 'completed'])
    total_usdt = sum([o[4] for o in orders if o[5] == 'USDT' and o[7] == 'completed'])
    
    text = f"📦 Все заказы: {len(orders)}\n\n"
    text += f"🕐 Ожидают: {pending_count}\n"
    text += f"✅ Выполнены: {completed_count}\n"
    text += f"❌ Отменены: {cancelled_count}\n\n"
    text += f"💰 Выручка:\n"
    text += f"   • {total_rub:.2f}₽\n"
    text += f"   • {total_usdt} USDT\n\n"
    
    # Показываем последние 5 заказов
    text += "Последние заказы:\n"
    for i, order in enumerate(orders[:5], 1):
        status_emoji = "🕐" if order[7] == 'pending' else "✅" if order[7] == 'completed' else "❌"
        text += f"{i}. {status_emoji} #{order[0]} - {order[2]} ({order[4]} {order[5]})\n"
    
    if len(orders) > 5:
        text += f"\n... и ещё {len(orders) - 5} заказов"
    
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🕐 Новые заказы", callback_data="admin_pending_orders")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_back")]
        ]
    )
    
    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()

async def show_order_admin_callback(callback: CallbackQuery, order_id):
    order = db.get_order_by_id(order_id)
    
    if not order:
        await callback.message.edit_text("❌ Заказ не найден!")
        return
    
    # Форматируем статус
    status_emoji = {
        'pending': '🕐 Ожидает',
        'processing': '🔄 В обработке',
        'completed': '✅ Выполнен',
        'cancelled': '❌ Отменён'
    }.get(order[7], '❓ Неизвестно')
    
    payment_method = {
        'crypto_bot': '🤖 Crypto Bot',
        'bep20': '💼 BEP20'
    }.get(order[8], 'Не указан')
    
    text = (
        f"🛒 Заказ #{order[0]}\n\n"
        f"{status_emoji}\n"
        f"👤 Клиент: {order[18] or 'Без имени'} (@{order[17] or 'нет'})\n"
        f"🆔 ID: {order[1]}\n"
        f"📦 Товар: {order[2]}\n"
        f"📊 Количество: {order[3]}\n"
        f"💰 Сумма: {order[4]} {order[5]}\n"
        f"💳 Способ: {payment_method}\n"
        f"📅 Дата: {order[13].split()[0] if ' ' in str(order[13]) else order[13][:10]}\n"
    )
    
    if order[12]:  # admin_comment
        text += f"💬 Комментарий: {order[12]}\n"
    
    if order[11]:  # screenshot
        text += f"📸 Есть скриншот оплаты\n"
    
    await callback.message.edit_text(
        text,
        reply_markup=order_management_keyboard(order_id)
    )

@router.callback_query(F.data.startswith("complete_order_"))
async def complete_order(callback: CallbackQuery):
    if not db.is_support_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа!")
        return
    
    order_id = int(callback.data.split("_")[2])
    
    # Обновляем статус заказа
    db.update_order_status(order_id, "completed", callback.from_user.id, "Заказ выполнен")
    
    # Получаем информацию о заказе
    order = db.get_order_by_id(order_id)
    
    if order:
        user_id, product = order[1], order[2]
        
        # Уведомляем пользователя
        try:
            await bot.send_message(
                user_id,
                f"🎉 Заказ #{order_id} выполнен!\n\n"
                f"📦 {product} активирован и отправлен.\n"
                f"Спасибо за покупку! 🎊\n\n"
                f"Если есть вопросы — пиши в поддержку!"
            )
        except Exception as e:
            print(f"Не удалось уведомить пользователя {user_id}: {e}")
    
    await callback.answer("✅ Заказ подтверждён!", show_alert=True)
    await show_order_admin_callback(callback, order_id)

@router.callback_query(F.data.startswith("cancel_order_"))
async def cancel_order(callback: CallbackQuery):
    if not db.is_support_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа!")
        return
    
    order_id = int(callback.data.split("_")[2])
    
    # Обновляем статус заказа
    db.update_order_status(order_id, "cancelled", callback.from_user.id, "Заказ отменён")
    
    # Получаем информацию о заказе
    order = db.get_order_by_id(order_id)
    
    if order:
        user_id, product = order[1], order[2]
        
        # Уведомляем пользователя
        try:
            await bot.send_message(
                user_id,
                f"❌ Заказ #{order_id} отменён\n\n"
                f"📦 {product}\n"
                f"Если у тебя были проблемы с оплатой,\n"
                f"обратись в поддержку для решения вопроса."
            )
        except Exception as e:
            print(f"Не удалось уведомить пользователя {user_id}: {e}")
    
    await callback.answer("❌ Заказ отменён!", show_alert=True)
    await show_order_admin_callback(callback, order_id)

@router.callback_query(F.data.startswith("comment_order_"))
async def comment_order_start(callback: CallbackQuery, state: FSMContext):
    if not db.is_support_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа!")
        return
    
    try:
        order_id = int(callback.data.split("_")[2])
        await state.update_data(order_id=order_id)
        
        await callback.message.answer(
            f"💬 Комментарий к заказу #{order_id}\n\n"
            f"Напиши комментарий (будет виден пользователю):",
            reply_markup=cancel_keyboard()
        )
        await state.set_state(Form.waiting_admin_comment)
        await callback.answer()
        
    except Exception as e:
        await callback.answer(f"❌ Ошибка: {str(e)}")

@router.message(Form.waiting_admin_comment)
async def process_order_comment(message: Message, state: FSMContext):
    data = await state.get_data()
    order_id = data['order_id']
    
    try:
        comment = message.text or ""
        
        # Обновляем заказ с комментарием
        order = db.get_order_by_id(order_id)
        if order:
            # Сохраняем текущий статус
            current_status = order[7]
            db.update_order_status(order_id, current_status, message.from_user.id, comment)
            
            # Уведомляем пользователя о комментарии
            try:
                await bot.send_message(
                    order[1],
                    f"💬 Комментарий к заказу #{order_id}\n\n"
                    f"{comment}\n\n"
                    f"Статус заказа: {current_status}"
                )
            except:
                pass
        
        await message.answer(
            f"✅ Комментарий добавлен к заказу #{order_id}!",
            reply_markup=main_menu(message.from_user.id)
        )
        
    except Exception as e:
        await message.answer(f"❌ Ошибка: {str(e)}")
    
    await state.clear()

# =================== УПРАВЛЕНИЕ ЦЕНАМИ ===================
@router.callback_query(F.data == "admin_manage_prices")
async def manage_prices_menu(callback: CallbackQuery):
    if not db.is_support_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа!")
        return
    
    text = "💰 Текущие цены:\n\n"
    text += f"⭐ Звезда: {PRICES['star_rate']}₽\n"
    text += f"💎 TON: {PRICES['ton_rate']}₽\n"
    text += f"🏆 Premium 3 мес: {PRICES['premium_3']} USDT\n"
    text += f"🏆 Premium 6 мес: {PRICES['premium_6']} USDT\n"
    text += f"🏆 Premium 12 мес: {PRICES['premium_12']} USDT\n\n"
    text += "👇 Выбери цену для изменения:"
    
    await callback.message.edit_text(
        text,
        reply_markup=prices_management_menu()
    )
    await callback.answer()

@router.callback_query(F.data.startswith("price_"))
async def change_price_start(callback: CallbackQuery, state: FSMContext):
    if not db.is_support_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа!")
        return
    
    price_key = callback.data.replace("price_", "")
    
    price_names = {
        "star": "⭐ Цена одной звезды (в рублях)",
        "ton": "💎 Цена одного TON (в рублях)",
        "premium_3": "🏆 Цена Premium на 3 месяца (в USDT)",
        "premium_6": "🏆 Цена Premium на 6 месяцев (в USDT)",
        "premium_12": "🏆 Цена Premium на 12 месяцев (в USDT)"
    }
    
    current_price = PRICES.get(f"{price_key}", 0)
    
    await state.update_data(price_key=price_key)
    
    await callback.message.answer(
        f"💰 Изменение цены\n\n"
        f"{price_names.get(price_key, 'Цена')}\n"
        f"Текущая цена: {current_price}\n\n"
        f"Введи новую цену (число):\n\n"
        f"Используй /cancel для отмены",
        reply_markup=cancel_keyboard()
    )
    await state.set_state(Form.waiting_set_price)
    await callback.answer()

@router.message(Form.waiting_set_price)
async def change_price_process(message: Message, state: FSMContext):
    if message.text and message.text.startswith('/cancel'):
        await state.clear()
        await message.answer("❌ Изменение цены отменено", 
                           reply_markup=main_menu(message.from_user.id))
        return
    
    try:
        data = await state.get_data()
        price_key = data['price_key']
        
        new_price = float(message.text.replace(',', '.'))
        
        if new_price <= 0:
            await message.answer("❌ Цена должна быть больше 0!")
            return
        
        db.update_price(price_key, new_price)
        
        price_names = {
            "star": "⭐ Цена звезды",
            "ton": "💎 Цена TON",
            "premium_3": "🏆 Premium 3 мес",
            "premium_6": "🏆 Premium 6 мес",
            "premium_12": "🏆 Premium 12 мес"
        }
        
        await message.answer(
            f"✅ Цена изменена!\n\n"
            f"{price_names.get(price_key, 'Цена')}: {new_price}\n\n"
            f"Изменение вступит в силу сразу!",
            reply_markup=main_menu(message.from_user.id)
        )
        
    except ValueError:
        await message.answer("❌ Введи число! Например: 1.45 или 167")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {str(e)}")
    
    await state.clear()

# =================== УПРАВЛЕНИЕ ТП-АДМИНАМИ ===================
@router.callback_query(F.data == "admin_manage_support")
async def manage_support_menu(callback: CallbackQuery):
    if not db.is_support_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа!")
        return
    
    admin_level = db.get_admin_level(callback.from_user.id)
    
    await callback.message.edit_text(
        "👨‍💼 Управление ТП-админами\n\n"
        "Добавляй или удаляй тех, кто будет отвечать на заявки:",
        reply_markup=support_management_menu(admin_level)
    )
    await callback.answer()

@router.callback_query(F.data == "admin_add_support")
async def add_support_admin_start(callback: CallbackQuery, state: FSMContext):
    if not db.is_support_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа!")
        return
    
    await callback.message.answer(
        "👨‍💼 Добавление ТП-админа\n\n"
        "Пришли ID пользователя (цифры):\n"
        "Пример: 1234567890\n\n"
        "Используй /cancel для отмены",
        reply_markup=cancel_keyboard()
    )
    await state.set_state(Form.waiting_new_admin)
    await callback.answer()

@router.message(Form.waiting_new_admin)
async def add_support_admin_process(message: Message, state: FSMContext):
    if message.text and message.text.startswith('/cancel'):
        await state.clear()
        await message.answer("❌ Добавление отменено", 
                           reply_markup=main_menu(message.from_user.id))
        return
    
    try:
        admin_id = int(message.text)
        
        if db.is_support_admin(admin_id):
            await message.answer("❌ Этот пользователь уже ТП-админ!")
            return
        
        # Добавляем как ТП (уровень 1)
        db.add_support_admin(admin_id, message.from_user.id, admin_level=1)
        
        try:
            await bot.send_message(
                admin_id,
                "🎉 Ты теперь ТП-админ Art Stars!\n\n"
                "Теперь ты будешь получать все заявки от клиентов.\n"
                "Для ответа используй команду:\n"
                "/ticket_номер_заявки\n\n"
                "Удачи в работе! 💪"
            )
        except:
            pass
        
        await message.answer(
            f"✅ ТП-админ {admin_id} добавлен (уровень: ТП)!\n"
            f"Он получил уведомление.",
            reply_markup=main_menu(message.from_user.id)
        )
    except ValueError:
        await message.answer("❌ Пришли только цифры (ID пользователя)!")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {str(e)}")
    
    await state.clear()

@router.callback_query(F.data == "admin_remove_support")
async def remove_support_admin_start(callback: CallbackQuery):
    if not db.is_support_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа!")
        return
    
    admins = db.get_all_support_admins()
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    
    for admin in admins:
        if admin[0] != ADMIN_ID:  # Не показываем главного админа
            admin_name = admin[2] or admin[1] or str(admin[0])
            admin_level = "👑 Админ" if admin[3] >= 2 else "👨‍💼 ТП"
            keyboard.inline_keyboard.append([
                InlineKeyboardButton(
                    text=f"❌ {admin_name} ({admin_level})",
                    callback_data=f"remove_admin_{admin[0]}"
                )
            ])
    
    keyboard.inline_keyboard.append([
        InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_manage_support")
    ])
    
    await callback.message.edit_text(
        "➖ Удаление ТП-админа\n\n"
        "Выбери админа для удаления:",
        reply_markup=keyboard
    )
    await callback.answer()

@router.callback_query(F.data.startswith("remove_admin_"))
async def remove_support_admin_process(callback: CallbackQuery):
    if not db.is_support_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа!")
        return
    
    try:
        admin_id = int(callback.data.split("_")[2])
        
        if admin_id == ADMIN_ID:
            await callback.answer("❌ Нельзя удалить главного админа!", show_alert=True)
            return
        
        admin_level = db.get_admin_level(admin_id)
        
        # Проверяем права
        user_level = db.get_admin_level(callback.from_user.id)
        if admin_level >= 2 and user_level < 2:
            await callback.answer("❌ Ты не можешь удалить админа!", show_alert=True)
            return
        
        db.remove_support_admin(admin_id)
        
        try:
            await bot.send_message(
                admin_id,
                "⚠️ Ты больше не ТП-админ Art Stars!\n\n"
                "Твои права админа были отозваны."
            )
        except:
            pass
        
        await callback.message.edit_text(
            f"✅ Админ {admin_id} удалён!",
            reply_markup=support_management_menu(user_level)
        )
    except Exception as e:
        await callback.message.edit_text(f"❌ Ошибка: {str(e)}")
    
    await callback.answer()

@router.callback_query(F.data == "admin_list_support")
async def list_support_admins(callback: CallbackQuery):
    if not db.is_support_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа!")
        return
    
    admins = db.get_all_support_admins()
    
    text = "👨‍💼 Список ТП-админов:\n\n"
    
    for admin in admins:
        role = "👑 Админ" if admin[3] >= 2 else "👨‍💼 ТП"
        added_date = admin[4].split()[0] if isinstance(admin[4], str) and ' ' in str(admin[4]) else str(admin[4])[:10]
        text += f"{role} | ID: {admin[0]}\n"
        text += f"Имя: {admin[2] or admin[1] or 'Без имени'}\n"
        text += f"Добавлен: {added_date}\n\n"
    
    text += f"Всего: {len(admins)} админов"
    
    await callback.message.edit_text(
        text,
        reply_markup=support_management_menu(db.get_admin_level(callback.from_user.id))
    )
    await callback.answer()

# =================== УПРАВЛЕНИЕ УРОВНЯМИ ===================
@router.callback_query(F.data == "admin_manage_levels")
async def manage_levels_menu(callback: CallbackQuery):
    if not db.is_admin(callback.from_user.id):
        await callback.answer("❌ Только для админов!", show_alert=True)
        return
    
    await callback.message.edit_text(
        "🔐 Управление уровнями админов\n\n"
        "Повышай или понижай уровни доступа:",
        reply_markup=levels_management_menu()
    )
    await callback.answer()

@router.callback_query(F.data == "admin_list_with_levels")
async def list_admins_with_levels(callback: CallbackQuery):
    if not db.is_admin(callback.from_user.id):
        await callback.answer("❌ Только для админов!", show_alert=True)
        return
    
    admins = db.get_all_support_admins()
    
    text = "📊 Список админов с уровнями:\n\n"
    
    for admin in admins:
        level_text = "👑 Админ (уровень 2)" if admin[3] >= 2 else "👨‍💼 ТП (уровень 1)"
        text += f"{level_text}\n"
        text += f"ID: {admin[0]}\n"
        text += f"Имя: {admin[2] or admin[1] or 'Без имени'}\n\n"
    
    await callback.message.edit_text(
        text,
        reply_markup=levels_management_menu()
    )
    await callback.answer()

@router.callback_query(F.data == "admin_promote")
async def promote_admin_start(callback: CallbackQuery):
    if not db.is_admin(callback.from_user.id):
        await callback.answer("❌ Только для админов!", show_alert=True)
        return
    
    admins = db.get_all_support_admins()
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    
    for admin in admins:
        if admin[3] == 1:  # Только ТП-админы (уровень 1)
            admin_name = admin[2] or admin[1] or str(admin[0])
            keyboard.inline_keyboard.append([
                InlineKeyboardButton(
                    text=f"🔼 {admin_name}",
                    callback_data=f"promote_admin_{admin[0]}"
                )
            ])
    
    keyboard.inline_keyboard.append([
        InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_manage_levels")
    ])
    
    await callback.message.edit_text(
        "🔼 Повышение уровня\n\n"
        "Выбери ТП-админа для повышения до Админа:",
        reply_markup=keyboard
    )
    await callback.answer()

@router.callback_query(F.data.startswith("promote_admin_"))
async def promote_admin_process(callback: CallbackQuery):
    if not db.is_admin(callback.from_user.id):
        await callback.answer("❌ Только для админов!", show_alert=True)
        return
    
    try:
        admin_id = int(callback.data.split("_")[2])
        
        if admin_id == ADMIN_ID:
            await callback.answer("❌ Это главный админ!", show_alert=True)
            return
        
        db.update_admin_level(admin_id, 2)
        
        try:
            await bot.send_message(
                admin_id,
                "🎉 Ты теперь Админ Art Stars!\n\n"
                "Теперь у тебя есть полный доступ:\n"
                "• Управление ценами\n"
                "• Управление уровнями админов\n"
                "• Полная статистика\n\n"
                "Будь ответственным! 👑"
            )
        except:
            pass
        
        await callback.message.edit_text(
            f"✅ Пользователь {admin_id} повышен до Админа!",
            reply_markup=levels_management_menu()
        )
    except Exception as e:
        await callback.message.edit_text(f"❌ Ошибка: {str(e)}")
    
    await callback.answer()

@router.callback_query(F.data == "admin_demote")
async def demote_admin_start(callback: CallbackQuery):
    if not db.is_admin(callback.from_user.id):
        await callback.answer("❌ Только для админов!", show_alert=True)
        return
    
    admins = db.get_all_support_admins()
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    
    for admin in admins:
        if admin[3] >= 2 and admin[0] != ADMIN_ID:  # Админы, кроме главного
            admin_name = admin[2] or admin[1] or str(admin[0])
            keyboard.inline_keyboard.append([
                InlineKeyboardButton(
                    text=f"🔽 {admin_name}",
                    callback_data=f"demote_admin_{admin[0]}"
                )
            ])
    
    keyboard.inline_keyboard.append([
        InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_manage_levels")
    ])
    
    await callback.message.edit_text(
        "🔽 Понижение уровня\n\n"
        "Выбери Админа для понижения до ТП:",
        reply_markup=keyboard
    )
    await callback.answer()

@router.callback_query(F.data.startswith("demote_admin_"))
async def demote_admin_process(callback: CallbackQuery):
    if not db.is_admin(callback.from_user.id):
        await callback.answer("❌ Только для админов!", show_alert=True)
        return
    
    try:
        admin_id = int(callback.data.split("_")[2])
        
        if admin_id == ADMIN_ID:
            await callback.answer("❌ Нельзя понизить главного админа!", show_alert=True)
            return
        
        db.update_admin_level(admin_id, 1)
        
        try:
            await bot.send_message(
                admin_id,
                "⚠️ Твой уровень админа понижен!\n\n"
                "Теперь ты ТП-админ.\n"
                "У тебя остался доступ к заявкам,\n"
                "но управление уровнями недоступно."
            )
        except:
            pass
        
        await callback.message.edit_text(
            f"✅ Пользователь {admin_id} понижен до ТП-админа!",
            reply_markup=levels_management_menu()
        )
    except Exception as e:
        await callback.message.edit_text(f"❌ Ошибка: {str(e)}")
    
    await callback.answer()

# =================== СТАТИСТИКА ===================
@router.callback_query(F.data == "admin_stats")
async def show_stats(callback: CallbackQuery):
    if not db.is_support_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа!")
        return
    
    stats = db.get_stats()
    
    text = (
        "📊 Статистика магазина\n\n"
        f"👥 Пользователей: {stats['users']}\n"
        f"🛒 Заказов всего: {stats['orders']}\n"
        f"   • Ожидают: {stats['pending_orders']}\n"
        f"💰 Общая выручка:\n"
        f"   • {stats['total_rub']:,}₽ (рубли)\n"
        f"   • {stats['total_usdt']} USDT\n"
        f"🆘 Заявок:\n"
        f"   • Новых: {stats['new_tickets']}\n\n"
        f"👨‍💼 Админов всего: {stats['all_admins']}\n"
        f"   • ТП-админов: {stats['support_admins']}\n"
        f"   • Полных админов: {stats['full_admins']}\n\n"
        "💰 Текущие цены:\n"
        f"⭐ Звезда: {stats['prices']['star_rate']}₽\n"
        f"💎 TON: {stats['prices']['ton_rate']}₽\n"
        f"🏆 Premium: {stats['prices']['premium_3']}/{stats['prices']['premium_6']}/{stats['prices']['premium_12']} USDT\n\n"
        "✅ Магазин работает! 🚀"
    ).replace(",", " ")
    
    await callback.message.edit_text(
        text,
        reply_markup=admin_menu(db.get_admin_level(callback.from_user.id))
    )
    await callback.answer()

# =================== ОБРАБОТКА ЗАКАЗОВ ИЗ САЙТА ===================
@router.message(F.web_app_data)
async def handle_web_app_data(message: Message):
    try:
        data = json.loads(message.web_app_data.data)
        
        if data.get('type') == 'new_order':
            order_id = db.create_order(
                message.from_user.id,
                data['data']['product'],
                data['data']['quantity'],
                data['data']['total'],
                data['data']['currency'],
                data['data']['username'],
                data['data'].get('payment_method'),
                data['data'].get('crypto_bot_link'),
                data['data'].get('bep20_wallet'),
                data['data'].get('screenshot')
            )
            
            # Отправляем всем админам (и ТП и Админам)
            admins = db.get_all_support_admins()
            
            for admin in admins:
                try:
                    await bot.send_message(
                        admin[0],
                        f"🛒 НОВЫЙ ЗАКАЗ #{order_id}\n\n"
                        f"👤 Клиент: {message.from_user.full_name}\n"
                        f"🆔 ID: {message.from_user.id}\n"
                        f"📦 Товар: {data['data']['product']}\n"
                        f"📊 Количество: {data['data']['quantity']}\n"
                        f"💰 Сумма: {data['data']['total']} {data['data']['currency']}\n"
                        f"💳 Способ: {data['data'].get('payment_name', 'Не указан')}\n"
                        f"📝 Username: @{data['data']['username']}\n\n"
                        f"Ожидает оплаты и подтверждения!\n"
                        f"Для управления: /order_{order_id}"
                    )
                except:
                    pass
            
            await message.answer(
                f"✅ Заказ #{order_id} создан!\n\n"
                f"После оплаты отправь скриншот в этот чат.\n"
                f"Мы активируем заказ в течение 15 минут.\n\n"
                f"Спасибо за покупку! 🎉",
                reply_markup=main_menu(message.from_user.id)
            )
    except Exception as e:
        await message.answer(f"❌ Ошибка обработки заказа: {str(e)}")

# =================== КНОПКИ НАЗАД ===================
@router.callback_query(F.data == "back_to_shop")
async def back_to_shop(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(
        "🛍️ Магазин Art Stars\n\n"
        "Что хочешь купить? 👇",
        reply_markup=shop_keyboard()
    )
    await callback.answer()

@router.callback_query(F.data == "back_to_main")
async def back_to_main(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(
        "✨ Art Stars - Официальный бот\n\n"
        "Выбери действие:",
        reply_markup=main_menu(callback.from_user.id)
    )
    await callback.answer()

@router.callback_query(F.data == "cancel")
async def cancel_action(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer("❌ Действие отменено", 
                                reply_markup=main_menu(callback.from_user.id))
    await callback.answer()

@router.callback_query(F.data == "admin_back")
async def admin_back(callback: CallbackQuery):
    if not db.is_support_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа!")
        return
    
    admin_level = db.get_admin_level(callback.from_user.id)
    await callback.message.edit_text(
        f"👑 Админ-панель | Уровень: {'Админ' if admin_level >= 2 else 'ТП'}\n\n"
        "Выбери раздел для управления:",
        reply_markup=admin_menu(admin_level)
    )
    await callback.answer()

# =================== ЗАПУСК БОТА ===================
async def main():
    print("🤖 Art Stars Bot запускается...")
    print(f"👑 Главный админ: {ADMIN_ID}")
    print(f"🌐 Сайт: {WEBAPP_URL}")
    print("💰 Курсы:")
    print(f"   ⭐ Звезда: {PRICES['star_rate']}₽")
    print(f"   💎 TON: {PRICES['ton_rate']}₽")
    print(f"   👑 Premium: {PRICES['premium_3']}/{PRICES['premium_6']}/{PRICES['premium_12']} USDT")
    print("🚀 Бот готов к работе!")
    
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
