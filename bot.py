from aiohttp import web
import threading
import os
import asyncio
import sqlite3
from datetime import datetime, date
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, BufferedInputFile
from aiogram.types import Message, CallbackQuery
from PIL import Image, ImageDraw, ImageFont
import io
import pandas as pd

# ========== КОНФИГУРАЦИЯ ==========
BOT_TOKEN = "8604643943:AAEGfDCzxF1rwiEIBPVz5W_nZbFHdgqao9w"
ADMIN_IDS = [5333876901, 1722007206]

# ========== ИНИЦИАЛИЗАЦИЯ ==========
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# ========== БАЗА ДАННЫХ ==========
class Database:
    def __init__(self, db_file="party_tickets.db"):
        self.db_file = db_file
        self.conn = None
    
    def connect(self):
        self.conn = sqlite3.connect(self.db_file)
        self.conn.row_factory = sqlite3.Row
        return self.conn
    
    def init_tables(self):
        cursor = self.conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                full_name TEXT,
                first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS admins (
                admin_id INTEGER PRIMARY KEY,
                username TEXT,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT,
                event_date DATE NOT NULL,
                event_time TEXT,
                venue TEXT,
                age_restriction TEXT,
                price_male INTEGER,
                price_female INTEGER,
                max_participants INTEGER DEFAULT 60,
                image_url TEXT,
                is_active INTEGER DEFAULT 1,
                created_by INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS registrations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                full_name TEXT NOT NULL,
                birth_date DATE NOT NULL,
                phone TEXT NOT NULL,
                gender TEXT,
                price INTEGER,
                comment TEXT,
                registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS referrals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                referrer_id INTEGER NOT NULL,
                referred_id INTEGER NOT NULL,
                referred_name TEXT,
                registered INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(referred_id)
            )
        ''')
        
        cursor.execute('''
            CREATE UNIQUE INDEX IF NOT EXISTS idx_unique_reg 
            ON registrations(event_id, user_id)
        ''')
        
        self.conn.commit()
        cursor.close()
    
    def save_user(self, user_id, username, full_name):
        cursor = self.conn.cursor()
        cursor.execute('''
            INSERT OR IGNORE INTO users (user_id, username, full_name)
            VALUES (?, ?, ?)
        ''', (user_id, username, full_name))
        self.conn.commit()
        cursor.close()
    
    def find_user_by_username(self, username):
        username = username.lstrip('@').lower()
        cursor = self.conn.cursor()
        cursor.execute('SELECT user_id, username, full_name FROM users WHERE LOWER(username) = ?', (username,))
        user = cursor.fetchone()
        cursor.close()
        return user
    
    def get_all_users(self):
        cursor = self.conn.cursor()
        cursor.execute('SELECT user_id, username, full_name FROM users')
        users = cursor.fetchall()
        cursor.close()
        return users
    
    def get_active_events(self):
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT * FROM events 
            WHERE is_active = 1 AND event_date >= date('now')
            ORDER BY event_date ASC, event_time ASC
        ''')
        events = cursor.fetchall()
        cursor.close()
        return events
    
    def get_all_events_admin(self):
        cursor = self.conn.cursor()
        cursor.execute('SELECT * FROM events ORDER BY event_date DESC LIMIT 20')
        events = cursor.fetchall()
        cursor.close()
        return events
    
    def get_event_by_id(self, event_id):
        cursor = self.conn.cursor()
        cursor.execute('SELECT * FROM events WHERE event_id = ?', (event_id,))
        event = cursor.fetchone()
        cursor.close()
        return event
    
    def add_event(self, data):
        cursor = self.conn.cursor()
        cursor.execute('''
            INSERT INTO events 
            (title, description, event_date, event_time, venue, age_restriction, 
             price_male, price_female, max_participants, image_url, created_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            data['title'], data['description'], data['event_date'],
            data['event_time'], data['venue'],
            data['age_restriction'], data['price_male'], data['price_female'],
            data.get('max_participants', 60), data.get('image_file_id'), data['created_by']
        ))
        self.conn.commit()
        event_id = cursor.lastrowid
        cursor.close()
        return event_id
    
    def delete_event(self, event_id):
        cursor = self.conn.cursor()
        cursor.execute('UPDATE events SET is_active = 0 WHERE event_id = ?', (event_id,))
        self.conn.commit()
        cursor.close()
    
    def check_registration(self, event_id, user_id):
        cursor = self.conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM registrations WHERE event_id = ? AND user_id = ?', (event_id, user_id))
        count = cursor.fetchone()[0]
        cursor.close()
        return count > 0
    
    def get_current_participants_count(self, event_id):
        """Получить текущее количество зарегистрированных участников"""
        cursor = self.conn.cursor()
        cursor.execute('SELECT COUNT(*) as count FROM registrations WHERE event_id = ?', (event_id,))
        count = cursor.fetchone()[0]
        cursor.close()
        return count
    
    def save_registration(self, event_id, user_id, data):
        cursor = self.conn.cursor()
        cursor.execute('''
            INSERT INTO registrations (event_id, user_id, full_name, birth_date, phone, gender, price, comment)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (event_id, user_id, data['full_name'], data['birth_date'], data['phone'], data['gender'], data['price'], data.get('comment', '')))
        self.conn.commit()
        reg_id = cursor.lastrowid
        cursor.close()
        return reg_id
    
    def get_registrations_for_event(self, event_id):
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT r.full_name, r.birth_date, r.phone, r.gender, r.price, r.comment, r.registered_at, u.username
            FROM registrations r
            LEFT JOIN users u ON r.user_id = u.user_id
            WHERE r.event_id = ?
            ORDER BY r.registered_at DESC
        ''', (event_id,))
        data = cursor.fetchall()
        cursor.close()
        return data
    
    def is_admin(self, user_id):
        cursor = self.conn.cursor()
        cursor.execute('SELECT 1 FROM admins WHERE admin_id = ?', (user_id,))
        result = cursor.fetchone()
        cursor.close()
        return result is not None
    
    def add_admin(self, user_id, username=None):
        cursor = self.conn.cursor()
        cursor.execute('INSERT OR IGNORE INTO admins (admin_id, username) VALUES (?, ?)', (user_id, username))
        self.conn.commit()
        cursor.close()
    
    def get_stats(self):
        cursor = self.conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM registrations')
        total = cursor.fetchone()[0]
        cursor.execute('''
            SELECT e.title, COUNT(r.id) as count
            FROM events e
            LEFT JOIN registrations r ON e.event_id = r.event_id
            WHERE e.is_active = 1
            GROUP BY e.event_id
        ''')
        by_event = cursor.fetchall()
        cursor.close()
        return total, by_event
    
    # ========== РЕФЕРАЛЬНЫЕ МЕТОДЫ ==========
    def save_referral(self, referrer_id, referred_id, referred_name):
        cursor = self.conn.cursor()
        try:
            cursor.execute('''
                INSERT OR IGNORE INTO referrals (referrer_id, referred_id, referred_name)
                VALUES (?, ?, ?)
            ''', (referrer_id, referred_id, referred_name))
            self.conn.commit()
            return True
        except:
            return False
    
    def mark_referral_registered(self, user_id):
        cursor = self.conn.cursor()
        cursor.execute('''
            UPDATE referrals SET registered = 1 WHERE referred_id = ?
        ''', (user_id,))
        self.conn.commit()
        return cursor.rowcount > 0
    
    def get_referral_stats(self, user_id):
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT COUNT(*) as total, COALESCE(SUM(registered), 0) as registered_count
            FROM referrals WHERE referrer_id = ?
        ''', (user_id,))
        result = cursor.fetchone()
        cursor.close()
        return result
    
    def get_user_referrals(self, user_id):
        """Получить список приглашённых пользователем с их username"""
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT r.referred_id, r.referred_name, r.registered, u.username
            FROM referrals r
            LEFT JOIN users u ON r.referred_id = u.user_id
            WHERE r.referrer_id = ?
            ORDER BY r.created_at DESC
        ''', (user_id,))
        data = cursor.fetchall()
        cursor.close()
        return data
    
    def get_all_referrals(self):
        """Получить все реферальные связи с username"""
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT r.referrer_id, r.referred_id, r.referred_name, r.registered,
                   CASE WHEN reg.id IS NOT NULL THEN 'Да' ELSE 'Нет' END as registered_on_event,
                   u.username as referred_username
            FROM referrals r
            LEFT JOIN registrations reg ON r.referred_id = reg.user_id
            LEFT JOIN users u ON r.referred_id = u.user_id
            ORDER BY r.created_at DESC
            LIMIT 100
        ''')
        data = cursor.fetchall()
        cursor.close()
        return data

db = Database("party_tickets.db")
db.connect()
db.init_tables()
for admin_id in ADMIN_IDS:
    db.add_admin(admin_id)

# ========== СОСТОЯНИЯ ==========
class RegStates(StatesGroup):
    full_name = State()
    birth_date = State()
    phone = State()
    gender = State()
    confirm = State()

class AdminStates(StatesGroup):
    title = State()
    description = State()
    event_date = State()
    event_time = State()
    venue = State()
    age_restriction = State()
    price_male = State()
    price_female = State()
    max_participants = State()
    image_file_id = State()

class ReferralStates(StatesGroup):
    waiting_user_input = State()

class BroadcastStates(StatesGroup):
    waiting_text = State()
    waiting_photo = State()
    confirm = State()

# ========== КЛАВИАТУРЫ ==========
def main_keyboard():
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎪 Афиша мероприятий", callback_data="afisha")],
        [InlineKeyboardButton(text="👤 Мои билеты", callback_data="my_tickets")],
        [InlineKeyboardButton(text="🤝 Реферальная программа", callback_data="referral")],
        [InlineKeyboardButton(text="❓ Помощь", callback_data="help")]
    ])
    return keyboard

def admin_main_keyboard():
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить ивент", callback_data="admin_add_event")],
        [InlineKeyboardButton(text="📋 Список ивентов", callback_data="admin_list_events")],
        [InlineKeyboardButton(text="📊 Выгрузить участников", callback_data="admin_export")],
        [InlineKeyboardButton(text="📈 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="👥 Приглашения пользователя", callback_data="admin_user_referrals")],
        [InlineKeyboardButton(text="📋 Все приглашения", callback_data="admin_all_referrals")],
        [InlineKeyboardButton(text="📢 Рассылка", callback_data="admin_broadcast")],
        [InlineKeyboardButton(text="❌ Удалить ивент", callback_data="admin_delete_event")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_main")]
    ])
    return keyboard

def admin_back_keyboard():
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад в админку", callback_data="back_to_admin")]
    ])
    return keyboard

def back_keyboard():
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_main")]
    ])
    return keyboard

def cancel_keyboard():
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отменить регистрацию", callback_data="cancel_registration")]
    ])
    return keyboard

def gender_keyboard(price_male, price_female):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"👨 Мужской — {price_male} ₽", callback_data="gender_male")],
        [InlineKeyboardButton(text=f"👩 Женский — {price_female} ₽", callback_data="gender_female")],
        [InlineKeyboardButton(text="❌ Отменить регистрацию", callback_data="cancel_registration")]
    ])
    return keyboard

# ========== ГЕНЕРАЦИЯ БИЛЕТА ==========
def generate_ticket(user_name, username, event_title, event_date, phone, gender, price):
    width, height = 800, 500
    img = Image.new('RGB', (width, height), color='#2d1b4e')
    draw = ImageDraw.Draw(img)
    
    # Рисуем градиентный фон
    for i in range(height):
        r = 45 + int(i / height * 30)
        g = 27 + int(i / height * 40)
        b = 78 + int(i / height * 60)
        draw.line([(0, i), (width, i)], fill=(r, g, b))
    
    # Рамки
    draw.rectangle([10, 10, width-10, height-10], outline='#e94560', width=3)
    draw.rectangle([15, 15, width-15, height-15], outline='#e94560', width=1)
    draw.rectangle([20, 20, width-20, height-20], outline='#e94560', width=1)
    
    # Загружаем шрифт из файла в репозитории
    try:
        font_path = "DejaVuLGCSans.ttf"
        font_title = ImageFont.truetype(font_path, 40)
        font_normal = ImageFont.truetype(font_path, 24)
        font_small = ImageFont.truetype(font_path, 18)
    except:
        font_title = ImageFont.load_default()
        font_normal = ImageFont.load_default()
        font_small = ImageFont.load_default()
    
    # Очищаем название от эмодзи
    clean_title = event_title.replace('🎉', '').replace('🏝', '').replace('🎽', '').replace('⭐', '').replace('✨', '').replace('❗', '').replace('️', '').strip()
    
    draw.text((40, 40), "БИЛЕТ НА СОБЫТИЕ", fill='#e94560', font=font_title)
    draw.text((40, 110), f"Мероприятие: {clean_title}", fill='white', font=font_normal)
    draw.text((40, 160), f"Дата: {event_date}", fill='#cccccc', font=font_normal)
    draw.text((40, 210), f"Участник: {user_name}", fill='white', font=font_normal)
    
    username_text = f"@{username}" if username else "Не указан"
    draw.text((40, 260), f"Telegram: {username_text}", fill='#aaffdd', font=font_normal)
    
    draw.text((40, 310), f"Телефон: {phone}", fill='white', font=font_normal)
    draw.text((40, 360), f"Пол: {'Мужской' if gender == 'male' else 'Женский'}", fill='white', font=font_normal)
    draw.text((40, 410), f"Сумма: {price} ₽", fill='#e94560', font=font_normal)
    
    img_bytes = io.BytesIO()
    img.save(img_bytes, format='PNG')
    img_bytes.seek(0)
    return img_bytes.getvalue()

# ========== ОСНОВНЫЕ ОБРАБОТЧИКИ ==========
@dp.callback_query(lambda c: c.data == "cancel_registration")
async def cancel_registration_global(callback: CallbackQuery, state: FSMContext):
    current_state = await state.get_state()
    if current_state:
        await state.clear()
        await callback.message.answer(
            "❌ Регистрация отменена.\n\n"
            "👇 Выберите действие:",
            reply_markup=main_keyboard(),
            parse_mode="Markdown"
        )
    else:
        await callback.message.answer(
            "❌ Нет активной регистрации для отмены.",
            reply_markup=main_keyboard(),
            parse_mode="Markdown"
        )
    await callback.answer()

@dp.message(Command("start"))
async def start(message: Message):
    db.save_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
    
    args = message.text.split()
    if len(args) > 1 and args[1].startswith("ref_"):
        try:
            referrer_id = int(args[1].split("_")[1])
            if referrer_id != message.from_user.id:
                db.save_referral(referrer_id, message.from_user.id, message.from_user.full_name)
        except:
            pass
    
    if message.from_user.id in ADMIN_IDS and not db.is_admin(message.from_user.id):
        db.add_admin(message.from_user.id, message.from_user.username)
    
    text = (
        "Ну да, это FESTiX и у нас есть бот😎\n\n"
        "Делай че хочешь👇\n\n"
    )
    await message.answer(text, reply_markup=main_keyboard(), parse_mode="Markdown")

@dp.callback_query(lambda c: c.data == "back_to_main")
async def back_to_main(callback: CallbackQuery):
    await callback.message.edit_text(
        "Ну да, это FESTiX и у нас есть бот😎\n\n"
        "Делай че хочешь👇\n\n",
        reply_markup=main_keyboard(),
        parse_mode="Markdown"
    )
    await callback.answer()

@dp.callback_query(lambda c: c.data == "help")
async def show_help(callback: CallbackQuery):
    text = (
        "❓ **Помощь**\n\n"
        "📌 **Как пользоваться ботом:**\n"
        "1. Нажмите «Афиша мероприятий»\n"
        "2. Выберите интересующее событие\n"
        "3. Заполните анкету (ФИО, дата рождения, телефон, пол)\n"
        "4. После регистрации с вами свяжется организатор\n\n"
        "🤝 **Реферальная программа:**\n"
        "• Приглашайте друзей по вашей ссылке\n"
        "• Ты получаешь бонус за каждого приглашенного гостя🎁\n\n"
        "📞 По всем вопросам: @chev5211"
    )
    await callback.message.edit_text(text, reply_markup=back_keyboard(), parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(lambda c: c.data == "my_tickets")
async def my_tickets(callback: CallbackQuery):
    cursor = db.conn.cursor()
    cursor.execute('''
        SELECT r.id, e.title, e.event_date, r.full_name, r.phone, r.price, u.username
        FROM registrations r
        JOIN events e ON r.event_id = e.event_id
        LEFT JOIN users u ON r.user_id = u.user_id
        WHERE r.user_id = ?
        ORDER BY r.registered_at DESC
    ''', (callback.from_user.id,))
    tickets = cursor.fetchall()
    cursor.close()
    
    if not tickets:
        await callback.message.edit_text(
            "🎫 У вас пока нет билетов.\n\nПерейдите в «Афишу мероприятий» и зарегистрируйтесь!",
            reply_markup=back_keyboard(),
            parse_mode="Markdown"
        )
        await callback.answer()
        return
    
    text = "🎫 **Ваши билеты:**\n\n"
    for t in tickets:
        text += f"📌 *{t['title']}*\n"
        text += f"   📅 {t['event_date']}\n"
        text += f"   👤 {t['full_name']}\n"
        text += f"   💰 {t['price']} ₽\n\n"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_main")]
    ])
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(lambda c: c.data == "referral")
async def referral_program(callback: CallbackQuery):
    user_id = callback.from_user.id
    stats = db.get_referral_stats(user_id)
    
    bot_info = await bot.get_me()
    referral_link = f"https://t.me/{bot_info.username}?start=ref_{user_id}"
    
    total = stats['total'] if stats else 0
    registered = stats['registered_count'] if stats else 0
    
    text = f"""
🤝 **Твоя реферальная ссылка:**

`{referral_link}`

📊 **Твоя статистика:**
• Приглашено друзей: {total}
• Зарегистрировались на ивент: {registered}

**Как это работает:**
1. Отправь ссылку другу
2. Друг регистрируется на мероприятие
3. Ты получаешь бонус за каждого приглашенного гостя🎁
    """
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📤 Поделиться ссылкой", url=f"https://t.me/share/url?url={referral_link}&text=Приглашаю%20на%20вечеринку%20FESTiX!")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_main")]
    ])
    
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(lambda c: c.data == "afisha")
async def show_afisha(callback: CallbackQuery):
    events = db.get_active_events()
    if not events:
        await callback.message.edit_text(
            "📭 На данный момент нет активных мероприятий.\n\nЗагляните позже!",
            reply_markup=back_keyboard(),
            parse_mode="Markdown"
        )
        await callback.answer()
        return
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    for event in events:
        try:
            date_obj = datetime.strptime(event['event_date'], '%Y-%m-%d').date()
            date_str = date_obj.strftime('%d.%m')
        except:
            date_str = event['event_date']
        
        # Получаем количество свободных мест
        current_count = db.get_current_participants_count(event['event_id'])
        max_count = event['max_participants'] if event['max_participants'] else 60
        places_left = max_count - current_count
        
        keyboard.inline_keyboard.append([
            InlineKeyboardButton(text=f"{event['title']} — {date_str} | 🎟️ {places_left} мест", callback_data=f"event_{event['event_id']}")
        ])
    
    keyboard.inline_keyboard.append([InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_main")])
    
    try:
        await callback.message.delete()
    except:
        pass
    await callback.message.answer(
        "🎪 **Афиша ближайших событий:**\n\nВыберите мероприятие:",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )
    await callback.answer()

@dp.callback_query(lambda c: c.data and c.data.startswith('event_'))
async def show_event_details(callback: CallbackQuery, state: FSMContext):
    event_id = int(callback.data.split('_')[1])
    event = db.get_event_by_id(event_id)
    
    if not event:
        await callback.message.edit_text("❌ Событие не найдено", reply_markup=back_keyboard())
        return
    
    # Проверяем лимит участников
    current_count = db.get_current_participants_count(event_id)
    max_count = event['max_participants'] if event['max_participants'] else 60
    
    if current_count >= max_count:
        await callback.message.edit_text(
            f"😔 К сожалению, на мероприятие «{event['title']}» уже зарегистрировано {max_count} человек.\n\n"
            f"**Места закончились!**\n\n"
            f"Следите за нашими следующими тусовками!",
            reply_markup=back_keyboard(),
            parse_mode="Markdown"
        )
        await callback.answer()
        return
    
    if db.check_registration(event_id, callback.from_user.id):
        await callback.message.edit_text(
            f"⚠️ Вы уже зарегистрированы на событие «{event['title']}»!\n\n"
            f"Один пользователь может зарегистрироваться только один раз.",
            reply_markup=back_keyboard()
        )
        await callback.answer()
        return
    
    try:
        event_date = datetime.strptime(event['event_date'], '%Y-%m-%d').strftime('%d.%m.%Y')
    except:
        event_date = event['event_date']
    
    text = f"""
**{event['title']}**

📖 {event['description']}

📅 **Дата:** {event_date} в {event['event_time']}
📍 **Место:** {event['venue']}
🔞 **Возраст:** {event['age_restriction']}
💰 **Цена билета:** {event['price_female']}-{event['price_male']} ₽ (зависит от пола)
👥 **Осталось мест:** {max_count - current_count} из {max_count}

❗ Для регистрации потребуется:
• ФИО
• Дата рождения
• Номер телефона
• Пол (цена зависит от пола)
    """
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Зарегистрироваться", callback_data=f"reg_{event_id}")],
        [InlineKeyboardButton(text="◀️ Назад к афише", callback_data="afisha")]
    ])
    
    if event['image_url']:
        try:
            await callback.message.delete()
        except:
            pass
        await callback.message.answer_photo(
            photo=event['image_url'],
            caption=text,
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
    else:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="Markdown")
    
    await callback.answer()

@dp.callback_query(lambda c: c.data and c.data.startswith('reg_'))
async def start_registration(callback: CallbackQuery, state: FSMContext):
    event_id = int(callback.data.split('_')[1])
    event = db.get_event_by_id(event_id)
    
    # Проверяем лимит ещё раз (на случай, если места закончились между просмотром и регистрацией)
    current_count = db.get_current_participants_count(event_id)
    max_count = event['max_participants'] if event['max_participants'] else 60
    
    if current_count >= max_count:
        await callback.message.answer(
            f"😔 К сожалению, пока вы думали, все места на «{event['title']}» закончились!",
            reply_markup=back_keyboard(),
            parse_mode="Markdown"
        )
        await callback.answer()
        return
    
    await state.update_data(event_id=event_id, event_title=event['title'], 
                           event_price_male=event['price_male'], event_price_female=event['price_female'])
    await callback.message.answer(
        "📝 **Регистрация на мероприятие**\n\nВведите ваше полное имя (Фамилия Имя):",
        reply_markup=cancel_keyboard(),
        parse_mode="Markdown"
    )
    await state.set_state(RegStates.full_name)
    await callback.answer()

@dp.message(RegStates.full_name)
async def reg_full_name(message: Message, state: FSMContext):
    if len(message.text) < 3:
        await message.answer("❌ Введите реальное имя (минимум 3 символа)", reply_markup=cancel_keyboard())
        return
    await state.update_data(full_name=message.text)
    await message.answer(
        "🎂 Введите вашу дату рождения в формате ДД.ММ.ГГГГ:",
        reply_markup=cancel_keyboard()
    )
    await state.set_state(RegStates.birth_date)

@dp.message(RegStates.birth_date)
async def reg_birth_date(message: Message, state: FSMContext):
    try:
        birth_date = datetime.strptime(message.text, "%d.%m.%Y").date()
        age = (date.today() - birth_date).days // 365
        if age < 16:
            await message.answer("❌ Извините, мероприятие для посетителей 16+", reply_markup=cancel_keyboard())
            await state.clear()
            return
        await state.update_data(birth_date=birth_date)
        await message.answer(
            "📞 Введите ваш номер телефона:\n(например: +7 999 123-45-67)",
            reply_markup=cancel_keyboard()
        )
        await state.set_state(RegStates.phone)
    except ValueError:
        await message.answer("❌ Неверный формат. Введите дату как ДД.ММ.ГГГГ", reply_markup=cancel_keyboard())

@dp.message(RegStates.phone)
async def reg_phone(message: Message, state: FSMContext):
    phone = message.text.replace(' ', '').replace('-', '').replace('(', '').replace(')', '')
    if not (phone.startswith('+') and len(phone) >= 10):
        await message.answer("❌ Введите корректный номер телефона (например: +79991234567)", reply_markup=cancel_keyboard())
        return
    await state.update_data(phone=message.text)
    
    data = await state.get_data()
    price_male = data.get('event_price_male', 1000)
    price_female = data.get('event_price_female', 1000)
    
    await message.answer(
        f"👫 **Выберите ваш пол:**\n\n"
        f"💰 Цены билета:\n"
        f"• Мужской — {price_male} ₽\n"
        f"• Женский — {price_female} ₽",
        reply_markup=gender_keyboard(price_male, price_female),
        parse_mode="Markdown"
    )
    await state.set_state(RegStates.gender)

@dp.callback_query(lambda c: c.data in ["gender_male", "gender_female"])
async def reg_gender(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    gender = "male" if callback.data == "gender_male" else "female"
    price = data['event_price_male'] if gender == "male" else data['event_price_female']
    
    await state.update_data(gender=gender, price=price)
    
    data = await state.get_data()
    birth_date_str = data['birth_date'].strftime('%d.%m.%Y')
    gender_text = "Мужской 👨" if gender == "male" else "Женский 👩"
    
    text = f"""
✅ **Проверьте данные:**

👤 ФИО: {data['full_name']}
🎂 Дата рождения: {birth_date_str}
📞 Телефон: {data['phone']}
👫 Пол: {gender_text}
💰 Стоимость: {data['price']} ₽

🎉 Мероприятие: {data['event_title']}

Всё верно?
    """
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, зарегистрироваться", callback_data="confirm_reg")],
        [InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_registration")]
    ])
    
    await callback.message.answer(text, reply_markup=keyboard, parse_mode="Markdown")
    await state.set_state(RegStates.confirm)
    await callback.answer()


@dp.callback_query(lambda c: c.data == "confirm_reg")
async def confirm_registration(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    event = db.get_event_by_id(data['event_id'])
    event_date = event['event_date'] if event else 'дата уточняется'
    event_date_formatted = datetime.strptime(event_date, '%Y-%m-%d').strftime('%d.%m.%Y') if event else 'дата уточняется'
    
    # Проверяем лимит в последний раз
    current_count = db.get_current_participants_count(data['event_id'])
    max_count = event['max_participants'] if event['max_participants'] else 60
    
    if current_count >= max_count:
        await callback.message.answer(
            f"😔 К сожалению, места на «{event['title']}» закончились. Регистрация не сохранена.",
            reply_markup=main_keyboard(),
            parse_mode="Markdown"
        )
        await state.clear()
        await callback.answer()
        return
    
    # Берём username прямо из Telegram
    username = callback.from_user.username
    
    reg_id = db.save_registration(data['event_id'], callback.from_user.id, data)
    db.mark_referral_registered(callback.from_user.id)
    
    ticket_data = generate_ticket(
        data['full_name'],
        username,
        data['event_title'],
        event_date_formatted,
        data['phone'],
        data['gender'],
        data['price']
    )
    
    await callback.message.answer("🎉 **Регистрация успешна!**")
    await callback.message.answer_photo(
        photo=BufferedInputFile(ticket_data, filename=f"ticket_{reg_id}.png"),
        caption=f"🎫 Ваш билет на мероприятие «{data['event_title']}»\n\n"
                f"💳 Сумма к оплате: {data['price']} ₽\n\n"
                f"**Отлично, скоро с вами свяжется наш босс для оплаты!**\n\n"
                f"Сохраните это сообщение. При входе покажите билет организаторам.\n\n"
                f"❗️ Пригласи друга по реферальной программе и получи подарок на тусовке)",
        parse_mode="Markdown"
    )
    
    await callback.message.answer(
        "👇 **Выберите действие:**",
        reply_markup=main_keyboard(),
        parse_mode="Markdown"
    )
    await state.clear()
    await callback.answer()

# ========== АДМИН-ПАНЕЛЬ ==========
@dp.message(Command("admin"))
async def admin_panel(message: Message):
    if not db.is_admin(message.from_user.id):
        await message.answer("⛔ У вас нет прав администратора")
        return
    
    await message.answer(
        "🛡️ **Панель администратора**\n\nВыберите действие:",
        reply_markup=admin_main_keyboard(),
        parse_mode="Markdown"
    )

@dp.callback_query(lambda c: c.data == "admin_add_event")
async def add_event_start(callback: CallbackQuery, state: FSMContext):
    if not db.is_admin(callback.from_user.id):
        await callback.answer("Нет прав", show_alert=True)
        return
    
    await callback.message.edit_text("📝 **Добавление нового ивента**\n\nВведите название мероприятия:", parse_mode="Markdown")
    await state.set_state(AdminStates.title)
    await callback.answer()

@dp.message(AdminStates.title)
async def add_event_title(message: Message, state: FSMContext):
    await state.update_data(title=message.text)
    await message.answer("📖 Введите описание мероприятия:")
    await state.set_state(AdminStates.description)

@dp.message(AdminStates.description)
async def add_event_desc(message: Message, state: FSMContext):
    await state.update_data(description=message.text)
    await message.answer("📅 Введите дату в формате ДД.ММ.ГГГГ\nНапример: 25.12.2026")
    await state.set_state(AdminStates.event_date)

@dp.message(AdminStates.event_date)
async def add_event_date(message: Message, state: FSMContext):
    try:
        event_date = datetime.strptime(message.text, "%d.%m.%Y").date()
        await state.update_data(event_date=event_date)
        await message.answer("⏰ Введите время в формате ЧЧ:ММ\nНапример: 20:00")
        await state.set_state(AdminStates.event_time)
    except ValueError:
        await message.answer("❌ Неверный формат. Введите дату как ДД.ММ.ГГГГ")

@dp.message(AdminStates.event_time)
async def add_event_time(message: Message, state: FSMContext):
    await state.update_data(event_time=message.text)
    await message.answer("📍 Введите место проведения:")
    await state.set_state(AdminStates.venue)

@dp.message(AdminStates.venue)
async def add_event_venue(message: Message, state: FSMContext):
    await state.update_data(venue=message.text)
    await message.answer("🔞 Введите возрастное ограничение:\n(18+ / 16+ / Без ограничений)")
    await state.set_state(AdminStates.age_restriction)

@dp.message(AdminStates.age_restriction)
async def add_event_age(message: Message, state: FSMContext):
    await state.update_data(age_restriction=message.text)
    await message.answer("💰 Введите стоимость билета для **МАЛЬЧИКОВ** (в рублях):\nНапример: 3000", parse_mode="Markdown")
    await state.set_state(AdminStates.price_male)

@dp.message(AdminStates.price_male)
async def add_event_price_male(message: Message, state: FSMContext):
    try:
        price = int(message.text.strip())
        if price <= 0:
            await message.answer("❌ Цена должна быть положительным числом")
            return
        await state.update_data(price_male=price)
        await message.answer("💰 Введите стоимость билета для **ДЕВУШЕК** (в рублях):\nНапример: 2000", parse_mode="Markdown")
        await state.set_state(AdminStates.price_female)
    except ValueError:
        await message.answer("❌ Введите число (например: 3000)")

@dp.message(AdminStates.price_female)
async def add_event_price_female(message: Message, state: FSMContext):
    try:
        price = int(message.text.strip())
        if price <= 0:
            await message.answer("❌ Цена должна быть положительным числом")
            return
        await state.update_data(price_female=price)
        await message.answer("👥 Введите максимальное количество участников (по умолчанию 60):\n\nПросто напишите число или отправьте 'нет' для стандартного лимита 60", parse_mode="Markdown")
        await state.set_state(AdminStates.max_participants)
    except ValueError:
        await message.answer("❌ Введите число (например: 2000)")

@dp.message(AdminStates.max_participants)
async def add_event_max_participants(message: Message, state: FSMContext):
    if message.text.lower() == 'нет':
        max_participants = 60
    else:
        try:
            max_participants = int(message.text.strip())
            if max_participants <= 0:
                await message.answer("❌ Число должно быть положительным")
                return
        except ValueError:
            await message.answer("❌ Введите число или 'нет'")
            return
    
    await state.update_data(max_participants=max_participants)
    await message.answer("🖼️ **Теперь отправьте фото афиши** (просто отправьте картинку)\n\nИли напишите 'нет', если фото не нужно:", parse_mode="Markdown")
    await state.set_state(AdminStates.image_file_id)

@dp.message(AdminStates.image_file_id)
async def add_event_image(message: Message, state: FSMContext):
    image_file_id = None
    
    if message.photo:
        image_file_id = message.photo[-1].file_id
        await state.update_data(image_file_id=image_file_id)
    elif message.text and message.text.lower() == 'нет':
        await state.update_data(image_file_id=None)
    else:
        await message.answer("❌ Пожалуйста, отправьте **фото** афиши или напишите 'нет'", parse_mode="Markdown")
        return
    
    data = await state.get_data()
    
    preview = f"""
✅ **Предпросмотр ивента:**

📌 **Название:** {data.get('title', 'Не указано')}
📖 **Описание:** {data.get('description', 'Не указано')[:100]}...
📅 **Дата:** {data.get('event_date', 'Не указана')}
⏰ **Время:** {data.get('event_time', 'Не указано')}
📍 **Место:** {data.get('venue', 'Не указано')}
🔞 **Возраст:** {data.get('age_restriction', 'Не указано')}
💰 **Цены:** Мужской — {data.get('price_male', '?')} ₽, Женский — {data.get('price_female', '?')} ₽
👥 **Лимит участников:** {data.get('max_participants', 60)} человек
🖼️ **Изображение:** {'✅ Есть' if image_file_id else '❌ Нет'}

Подтверждаете добавление?
    """
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, добавить", callback_data="confirm_add")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_add")]
    ])
    
    if image_file_id:
        await message.answer_photo(
            photo=image_file_id,
            caption=preview,
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
    else:
        await message.answer(preview, reply_markup=keyboard, parse_mode="Markdown")

@dp.callback_query(lambda c: c.data == "confirm_add")
async def confirm_add_event(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    
    # Проверяем, что все необходимые данные есть
    required_fields = ['title', 'description', 'event_date', 'event_time', 'venue', 'age_restriction', 'price_male', 'price_female']
    missing = [f for f in required_fields if f not in data]
    if missing:
        await callback.message.answer(f"❌ Ошибка: не хватает данных: {missing}\nПопробуйте добавить ивент заново.")
        await state.clear()
        await callback.answer()
        return
    
    data['created_by'] = callback.from_user.id
    
    db.add_event(data)
    await callback.message.answer(f"✅ Ивент «{data['title']}» успешно добавлен!")
    await callback.message.answer(
        "🛡️ **Панель администратора**\n\nВыберите действие:",
        reply_markup=admin_main_keyboard(),
        parse_mode="Markdown"
    )
    await state.clear()
    await callback.answer()

@dp.callback_query(lambda c: c.data == "cancel_add")
async def cancel_add_event(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("❌ Добавление ивента отменено.")
    await callback.message.answer(
        "🛡️ **Панель администратора**\n\nВыберите действие:",
        reply_markup=admin_main_keyboard(),
        parse_mode="Markdown"
    )
    await state.clear()
    await callback.answer()

@dp.callback_query(lambda c: c.data == "admin_list_events")
async def list_events_admin(callback: CallbackQuery):
    if not db.is_admin(callback.from_user.id):
        await callback.answer("Нет прав")
        return
    
    events = db.get_all_events_admin()
    if not events:
        await callback.message.edit_text("📭 Нет ивентов в базе", reply_markup=admin_back_keyboard())
        return
    
    text = "📋 **Все ивенты:**\n\n"
    for e in events:
        status = "✅ Активен" if e['is_active'] == 1 else "❌ Завершён"
        current_count = db.get_current_participants_count(e['event_id'])
        max_count = e['max_participants'] if e['max_participants'] else 60
        text += f"*{e['title']}*\n"
        text += f"   📅 {e['event_date']} в {e['event_time']}\n"
        text += f"   📍 {e['venue']}\n"
        text += f"   💰 М: {e['price_male']} ₽ / Ж: {e['price_female']} ₽\n"
        text += f"   👥 {current_count}/{max_count} чел.\n"
        text += f"   🆔 ID: `{e['event_id']}` | {status}\n\n"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад в админку", callback_data="back_to_admin")]
    ])
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(lambda c: c.data == "admin_stats")
async def admin_stats(callback: CallbackQuery):
    if not db.is_admin(callback.from_user.id):
        await callback.answer("Нет прав")
        return
    
    total_regs, by_event = db.get_stats()
    
    text = f"📊 **Статистика:**\n\n"
    text += f"👥 Всего регистраций: **{total_regs}**\n\n"
    
    if by_event:
        text += "📈 **По мероприятиям:**\n"
        for event in by_event:
            text += f"   • {event['title']}: {event['count']} чел.\n"
    else:
        text += "Нет регистраций"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад в админку", callback_data="back_to_admin")]
    ])
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(lambda c: c.data == "admin_user_referrals")
async def admin_user_referrals(callback: CallbackQuery, state: FSMContext):
    if not db.is_admin(callback.from_user.id):
        await callback.answer("Нет прав")
        return
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад в админку", callback_data="back_to_admin")]
    ])
    
    await callback.message.edit_text(
        "👥 **Просмотр приглашений пользователя**\n\n"
        "Введите **username** (`@username`) или **Telegram ID** пользователя:\n\n"
        "Примеры:\n"
        "• `@username`\n"
        "• `123456789`",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )
    await state.set_state(ReferralStates.waiting_user_input)
    await callback.answer()

@dp.message(ReferralStates.waiting_user_input)
async def show_user_referrals(message: Message, state: FSMContext):
    if not db.is_admin(message.from_user.id):
        await message.answer("⛔ Нет прав")
        await state.clear()
        return
    
    input_text = message.text.strip()
    user = None
    user_id = None
    
    if input_text.isdigit():
        user_id = int(input_text)
    else:
        user = db.find_user_by_username(input_text)
        if user:
            user_id = user['user_id']
    
    if not user_id:
        await message.answer(
            f"❌ Пользователь `{input_text}` не найден.\n\n"
            f"Убедитесь, что пользователь запускал бота хотя бы раз",
            parse_mode="Markdown",
            reply_markup=admin_back_keyboard()
        )
        await state.clear()
        return
    
    referrals = db.get_user_referrals(user_id)
    
    if not referrals:
        await message.answer(
            f"📭 Пользователь `{user_id}` никого не пригласил",
            parse_mode="Markdown",
            reply_markup=admin_back_keyboard()
        )
        await state.clear()
        return
    
    text = f"👥 **Приглашения пользователя `{user_id}`:**\n\n"
    for ref in referrals:
        status = "✅ Зарегистрирован" if ref['registered'] == 1 else "⏳ Ещё не регистрировался"
        username_display = f"@{ref['username']}" if ref['username'] else "нет username"
        text += f"📨 ID: `{ref['referred_id']}`\n"
        text += f"   👤 Имя: {ref['referred_name']}\n"
        text += f"   📱 Username: {username_display}\n"
        text += f"   📊 Статус: {status}\n\n"
    
    if len(text) > 4000:
        parts = [text[i:i+4000] for i in range(0, len(text), 4000)]
        for part in parts:
            await message.answer(part, parse_mode="Markdown")
    else:
        await message.answer(text, parse_mode="Markdown")
    
    await message.answer("🔙 Выберите действие:", reply_markup=admin_back_keyboard())
    await state.clear()

@dp.callback_query(lambda c: c.data == "admin_all_referrals")
async def admin_all_referrals(callback: CallbackQuery):
    if not db.is_admin(callback.from_user.id):
        await callback.answer("Нет прав")
        return
    
    referrals = db.get_all_referrals()
    
    if not referrals:
        await callback.message.edit_text("📭 Пока нет реферальных приглашений", reply_markup=admin_back_keyboard())
        return
    
    text = "📋 **Все реферальные связи:**\n\n"
    for ref in referrals:
        username_display = f"@{ref['referred_username']}" if ref['referred_username'] else "нет username"
        text += f"👤 Пригласивший: `{ref['referrer_id']}`\n"
        text += f"   → Приглашённый: `{ref['referred_id']}`\n"
        text += f"   👤 Имя: {ref['referred_name']}\n"
        text += f"   📱 Username: {username_display}\n"
        text += f"   📊 Регистрация на ивент: {ref['registered_on_event']}\n\n"
        
        if len(text) > 3900:
            text += "\n... показаны не все записи (слишком много)"
            break
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📥 Выгрузить в Excel", callback_data="export_referrals")],
        [InlineKeyboardButton(text="◀️ Назад в админку", callback_data="back_to_admin")]
    ])
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(lambda c: c.data == "export_referrals")
async def export_referrals(callback: CallbackQuery):
    if not db.is_admin(callback.from_user.id):
        await callback.answer("Нет прав")
        return
    
    cursor = db.conn.cursor()
    cursor.execute('''
        SELECT 
            r.referrer_id as "ID пригласившего",
            r.referred_id as "ID приглашённого",
            r.referred_name as "Имя приглашённого",
            u.username as "Username приглашённого",
            CASE WHEN r.registered = 1 THEN 'Да' ELSE 'Нет' END as "Зарегистрировался на ивент",
            r.created_at as "Дата приглашения"
        FROM referrals r
        LEFT JOIN users u ON r.referred_id = u.user_id
        ORDER BY r.created_at DESC
    ''')
    data = cursor.fetchall()
    cursor.close()
    
    if not data:
        await callback.message.answer("Нет данных для экспорта")
        return
    
    data_list = []
    for row in data:
        data_list.append({
            'ID пригласившего': row['ID пригласившего'],
            'ID приглашённого': row['ID приглашённого'],
            'Имя приглашённого': row['Имя приглашённого'],
            'Username приглашённого': f"@{row['Username приглашённого']}" if row['Username приглашённого'] else "-",
            'Зарегистрировался на ивент': row['Зарегистрировался на ивент'],
            'Дата приглашения': row['Дата приглашения']
        })
    
    df = pd.DataFrame(data_list)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name="Рефералы", index=False)
    
    output.seek(0)
    
    await callback.message.answer_document(
        BufferedInputFile(output.getvalue(), filename=f"referrals_{datetime.now().strftime('%Y%m%d')}.xlsx"),
        caption="📊 Полная выгрузка реферальных связей"
    )
    await callback.answer()

@dp.callback_query(lambda c: c.data == "admin_export")
async def export_registrations(callback: CallbackQuery):
    if not db.is_admin(callback.from_user.id):
        await callback.answer("Нет прав")
        return
    
    events = db.get_all_events_admin()
    if not events:
        await callback.message.edit_text("📭 Нет ивентов для выгрузки", reply_markup=admin_back_keyboard())
        await callback.answer()
        return
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    for e in events:
        keyboard.inline_keyboard.append([
            InlineKeyboardButton(text=f"📥 {e['title']} ({e['event_date']})", callback_data=f"export_{e['event_id']}")
        ])
    keyboard.inline_keyboard.append([InlineKeyboardButton(text="◀️ Назад в админку", callback_data="back_to_admin")])
    
    await callback.message.edit_text("📥 Выберите ивент для выгрузки участников:", reply_markup=keyboard)
    await callback.answer()

@dp.callback_query(lambda c: c.data and c.data.startswith("export_"))
async def do_export(callback: CallbackQuery):
    event_id = int(callback.data.split('_')[1])
    event = db.get_event_by_id(event_id)
    registrations = db.get_registrations_for_event(event_id)
    
    if not registrations:
        await callback.message.edit_text("📭 Нет регистраций на этот ивент", reply_markup=admin_back_keyboard())
        await callback.answer()
        return
    
    data_list = []
    for reg in registrations:
        gender_text = "Мужской" if reg['gender'] == 'male' else "Женский" if reg['gender'] == 'female' else "-"
        username_text = f"@{reg['username']}" if reg['username'] else "-"
        data_list.append({
            'Telegram Username': username_text,
            'ФИО': reg['full_name'],
            'Дата рождения': reg['birth_date'],
            'Телефон': reg['phone'],
            'Пол': gender_text,
            'Сумма (₽)': reg['price'],
            'Комментарий': reg['comment'] or '',
            'Дата регистрации': reg['registered_at']
        })
    
    df = pd.DataFrame(data_list)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name=event['title'][:31], index=False)
    
    output.seek(0)
    
    await callback.message.answer_document(
        BufferedInputFile(output.getvalue(), filename=f"{event['title']}_{event['event_date']}.xlsx"),
        caption=f"📊 Участники ивента «{event['title']}»\nВсего: {len(registrations)} человек"
    )
    
    await callback.message.delete()
    await callback.message.answer(
        "🛡️ **Панель администратора**\n\nВыберите действие:",
        reply_markup=admin_main_keyboard(),
        parse_mode="Markdown"
    )
    await callback.answer()

@dp.callback_query(lambda c: c.data == "admin_delete_event")
async def delete_event_menu(callback: CallbackQuery):
    if not db.is_admin(callback.from_user.id):
        await callback.answer("Нет прав")
        return
    
    events = db.get_all_events_admin()
    if not events:
        await callback.message.edit_text("📭 Нет ивентов для удаления", reply_markup=admin_back_keyboard())
        await callback.answer()
        return
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    for e in events:
        if e['is_active'] == 1:
            keyboard.inline_keyboard.append([
                InlineKeyboardButton(text=f"❌ {e['title']} ({e['event_date']})", callback_data=f"delete_{e['event_id']}")
            ])
    keyboard.inline_keyboard.append([InlineKeyboardButton(text="◀️ Назад в админку", callback_data="back_to_admin")])
    
    await callback.message.edit_text("⚠️ Выберите ивент для удаления:", reply_markup=keyboard)
    await callback.answer()

@dp.callback_query(lambda c: c.data and c.data.startswith("delete_"))
async def confirm_delete_event(callback: CallbackQuery):
    event_id = int(callback.data.split('_')[1])
    event = db.get_event_by_id(event_id)
    
    if event:
        db.delete_event(event_id)
        await callback.message.answer(f"✅ Ивент «{event['title']}» удалён")
    
    await callback.message.answer(
        "🛡️ **Панель администратора**\n\nВыберите действие:",
        reply_markup=admin_main_keyboard(),
        parse_mode="Markdown"
    )
    await callback.answer()

@dp.callback_query(lambda c: c.data == "admin_broadcast")
async def admin_broadcast(callback: CallbackQuery, state: FSMContext):
    if not db.is_admin(callback.from_user.id):
        await callback.answer("Нет прав")
        return
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад в админку", callback_data="back_to_admin")]
    ])
    
    await callback.message.edit_text(
        "📢 **Рассылка пользователям**\n\n"
        "Введите **текст** сообщения для рассылки:\n\n"
        "*(можно будет добавить изображение на следующем шаге)*",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )
    await state.set_state(BroadcastStates.waiting_text)
    await callback.answer()

@dp.message(BroadcastStates.waiting_text)
async def broadcast_text(message: Message, state: FSMContext):
    await state.update_data(broadcast_text=message.text)
    await message.answer(
        "🖼️ **Теперь отправьте изображение** (или напишите 'нет', если без фото):",
        parse_mode="Markdown"
    )
    await state.set_state(BroadcastStates.waiting_photo)

@dp.message(BroadcastStates.waiting_photo)
async def broadcast_photo(message: Message, state: FSMContext):
    data = await state.get_data()
    text = data['broadcast_text']
    photo_file_id = None
    
    if message.photo:
        photo_file_id = message.photo[-1].file_id
    elif message.text and message.text.lower() == 'нет':
        photo_file_id = None
    else:
        await message.answer("❌ Отправьте **фото** или напишите 'нет'", parse_mode="Markdown")
        return
    
    await state.update_data(broadcast_photo=photo_file_id)
    
    preview_text = f"📢 **Предпросмотр рассылки:**\n\n{text}"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Отправить", callback_data="confirm_broadcast")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_broadcast")]
    ])
    
    if photo_file_id:
        await message.answer_photo(
            photo=photo_file_id,
            caption=preview_text,
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
    else:
        await message.answer(preview_text, reply_markup=keyboard, parse_mode="Markdown")
    
    await state.set_state(BroadcastStates.confirm)

@dp.callback_query(lambda c: c.data == "confirm_broadcast")
async def confirm_broadcast(callback: CallbackQuery, state: FSMContext):
    if not db.is_admin(callback.from_user.id):
        await callback.answer("Нет прав")
        return
    
    data = await state.get_data()
    text = data['broadcast_text']
    photo = data.get('broadcast_photo')
    
    users = db.get_all_users()
    
    if not users:
        await callback.message.answer("📭 Нет пользователей для рассылки")
        await state.clear()
        await callback.answer()
        return
    
    sent = 0
    failed = 0
    
    status_msg = await callback.message.answer("🔄 Отправка рассылки...")
    
    for user in users:
        try:
            if photo:
                await bot.send_photo(chat_id=user['user_id'], photo=photo, caption=text, parse_mode="Markdown")
            else:
                await bot.send_message(chat_id=user['user_id'], text=text, parse_mode="Markdown")
            sent += 1
        except Exception as e:
            failed += 1
        
        await asyncio.sleep(0.05)
    
    await status_msg.edit_text(
        f"✅ **Рассылка завершена!**\n\n"
        f"📨 Отправлено: {sent}\n"
        f"❌ Ошибок: {failed}\n"
        f"👥 Всего пользователей: {len(users)}"
    )
    
    await callback.message.answer(
        "🛡️ **Панель администратора**\n\nВыберите действие:",
        reply_markup=admin_main_keyboard(),
        parse_mode="Markdown"
    )
    await state.clear()
    await callback.answer()

@dp.callback_query(lambda c: c.data == "cancel_broadcast")
async def cancel_broadcast(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("❌ Рассылка отменена.")
    await callback.message.answer(
        "🛡️ **Панель администратора**\n\nВыберите действие:",
        reply_markup=admin_main_keyboard(),
        parse_mode="Markdown"
    )
    await state.clear()
    await callback.answer()

@dp.callback_query(lambda c: c.data == "back_to_admin")
async def back_to_admin(callback: CallbackQuery):
    await callback.message.edit_text(
        "🛡️ **Панель администратора**\n\nВыберите действие:",
        reply_markup=admin_main_keyboard(),
        parse_mode="Markdown"
    )
    await callback.answer()

# ========== ВЕБ-СЕРВЕР ДЛЯ RENDER.COM ==========
async def health_check(request):
    return web.Response(text="✅ Бот работает!", status=200)

async def run_web_server():
    app = web.Application()
    app.router.add_get('/', health_check)
    app.router.add_get('/health', health_check)
    
    port = int(os.environ.get('PORT', 8080))
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    print(f"✅ Веб-сервер запущен на порту {port}")
    
    await asyncio.Event().wait()

def start_web_server():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(run_web_server())

# ========== ЗАПУСК ==========
async def main():
    print("🤖 Бот запущен!")
    print("✅ База данных: party_tickets.db")
    print("✅ Админы:", ADMIN_IDS)
    
    thread = threading.Thread(target=start_web_server, daemon=True)
    thread.start()
    
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
