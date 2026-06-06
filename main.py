import asyncio
import logging
import time
import random
import os
import sqlite3
from datetime import datetime, timezone
# dotenv не нужен на хостинге — переменные уже в окружении
# Локально можно установить: pip install python-dotenv и раскомментировать:
# from dotenv import load_dotenv; load_dotenv()

from aiogram import Bot, Dispatcher, Router, F
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
    BotCommand, BotCommandScopeAllGroupChats, BotCommandScopeAllPrivateChats,
    FSInputFile
)
from aiogram.filters import Command

# ===== КОНФИГ =====

# Токен бота (строго из переменных окружения)
BOT_TOKEN = os.getenv("BOT_TOKEN")
# ID администратора
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
# Юзернейм создателя
CREATOR_USERNAME = os.getenv("CREATOR_USERNAME", "@default_username")
# Ссылка на канал создателя
CREATOR_CHANNEL = os.getenv("CREATOR_CHANNEL", "https://t.me")
# Юзернейм бота (без @)
BOT_USERNAME = os.getenv("BOT_USERNAME", "YourDefaultBot_bot").lstrip("@")

# ===== БАЗА ДАННЫХ =====

class Database:
    def __init__(self):
        self.conn = sqlite3.connect('bot.db', check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.create_tables()
        self.initialize_default_top()

    def create_tables(self):
        cursor = self.conn.cursor()

        cursor.execute('''CREATE TABLE IF NOT EXISTS users
                         (user_id INTEGER PRIMARY KEY,
                          username TEXT,
                          first_name TEXT,
                          date_added TEXT)''')

        cursor.execute('''CREATE TABLE IF NOT EXISTS chats
                         (chat_id INTEGER PRIMARY KEY,
                          chat_type TEXT,
                          title TEXT,
                          date_added TEXT)''')

        cursor.execute('''CREATE TABLE IF NOT EXISTS top_bomjsfera
                         (place INTEGER PRIMARY KEY,
                          user_id INTEGER,
                          username TEXT,
                          tag TEXT)''')

        cursor.execute('''CREATE TABLE IF NOT EXISTS logs
                         (id INTEGER PRIMARY KEY AUTOINCREMENT,
                          user_id INTEGER,
                          action TEXT,
                          timestamp TEXT)''')

        cursor.execute('''CREATE TABLE IF NOT EXISTS bot_settings
                         (key TEXT PRIMARY KEY,
                          value TEXT)''')

        cursor.execute('''CREATE TABLE IF NOT EXISTS tency_stats
                         (id INTEGER PRIMARY KEY AUTOINCREMENT,
                          chat_id INTEGER NOT NULL,
                          user_id INTEGER NOT NULL,
                          username TEXT,
                          count INTEGER DEFAULT 0,
                          last_updated TEXT,
                          UNIQUE(chat_id, user_id))''')

        cursor.execute('''CREATE TABLE IF NOT EXISTS tency_cooldowns
                         (chat_id INTEGER NOT NULL,
                          user_id INTEGER NOT NULL,
                          timestamp TEXT,
                          PRIMARY KEY(chat_id, user_id))''')

        self.conn.commit()

    def initialize_default_top(self):
        cursor = self.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM top_bomjsfera")
        count = cursor.fetchone()[0]

        if count == 0:
            default_top = [
                (8100791773, "@usertency", "маня доксер"),
                (6292332140, "@Tocioezz", "рейдер")
            ]
            for place, (user_id, username, tag) in enumerate(default_top, 1):
                cursor.execute('''INSERT OR REPLACE INTO top_bomjsfera (place, user_id, username, tag)
                                  VALUES (?, ?, ?, ?)''', (place, user_id, username, tag))
            self.conn.commit()

    # ===== МЕТОДЫ ДЛЯ TENCY =====

    def check_tency_cooldown(self, chat_id, user_id, cooldown_minutes=15):
        cursor = self.conn.cursor()
        cursor.execute("SELECT timestamp FROM tency_cooldowns WHERE chat_id = ? AND user_id = ?",
                       (chat_id, user_id))
        result = cursor.fetchone()

        if not result:
            return True, 0

        last_time = datetime.strptime(result[0], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        current_time = datetime.now(timezone.utc)
        time_diff = (current_time - last_time).total_seconds()
        remaining = cooldown_minutes * 60 - time_diff

        if remaining <= 0:
            return True, 0

        return False, int(remaining // 60) + 1

    def set_tency_cooldown(self, chat_id, user_id):
        cursor = self.conn.cursor()
        timestamp = self._get_utc_timestamp()
        cursor.execute('''INSERT OR REPLACE INTO tency_cooldowns (chat_id, user_id, timestamp)
                          VALUES (?, ?, ?)''', (chat_id, user_id, timestamp))
        self.conn.commit()

    def add_tency_count(self, chat_id, user_id, username, added_count):
        cursor = self.conn.cursor()
        timestamp = self._get_utc_timestamp()

        cursor.execute('''SELECT count FROM tency_stats
                          WHERE chat_id = ? AND user_id = ?''', (chat_id, user_id))
        result = cursor.fetchone()

        if result:
            new_count = result[0] + added_count
            cursor.execute('''UPDATE tency_stats
                              SET count = ?, username = ?, last_updated = ?
                              WHERE chat_id = ? AND user_id = ?''',
                           (new_count, username, timestamp, chat_id, user_id))
        else:
            cursor.execute('''INSERT INTO tency_stats (chat_id, user_id, username, count, last_updated)
                              VALUES (?, ?, ?, ?, ?)''',
                           (chat_id, user_id, username, added_count, timestamp))

        self.conn.commit()
        return added_count

    def get_tency_user_total(self, chat_id, user_id):
        cursor = self.conn.cursor()
        cursor.execute('''SELECT count FROM tency_stats
                          WHERE chat_id = ? AND user_id = ?''', (chat_id, user_id))
        result = cursor.fetchone()
        return result[0] if result else 0

    def get_tency_chat_top(self, chat_id, limit=10):
        cursor = self.conn.cursor()
        cursor.execute('''SELECT username, count FROM tency_stats
                          WHERE chat_id = ?
                          ORDER BY count DESC, last_updated DESC
                          LIMIT ?''', (chat_id, limit))
        return cursor.fetchall()

    def get_tency_chat_stats(self, chat_id):
        cursor = self.conn.cursor()
        cursor.execute('''SELECT COUNT(DISTINCT user_id) as users, SUM(count) as total
                          FROM tency_stats WHERE chat_id = ?''', (chat_id,))
        result = cursor.fetchone()
        if result:
            return {'users': result[0] or 0, 'total': result[1] or 0}
        return {'users': 0, 'total': 0}

    def reset_tency_chat_stats(self, chat_id):
        cursor = self.conn.cursor()
        cursor.execute('DELETE FROM tency_stats WHERE chat_id = ?', (chat_id,))
        cursor.execute('DELETE FROM tency_cooldowns WHERE chat_id = ?', (chat_id,))
        self.conn.commit()
        return cursor.rowcount

    # ===== ОСНОВНЫЕ МЕТОДЫ =====

    def _get_utc_timestamp(self):
        return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    def get_bot_status(self):
        cursor = self.conn.cursor()
        cursor.execute("SELECT value FROM bot_settings WHERE key = 'active'")
        result = cursor.fetchone()
        return result[0] == '1' if result else True

    def set_bot_status(self, active):
        cursor = self.conn.cursor()
        status = '1' if active else '0'
        cursor.execute("INSERT OR REPLACE INTO bot_settings (key, value) VALUES ('active', ?)", (status,))
        self.conn.commit()

    def log_action(self, user_id, action):
        cursor = self.conn.cursor()
        timestamp = self._get_utc_timestamp()
        cursor.execute('''INSERT INTO logs (user_id, action, timestamp)
                          VALUES (?, ?, ?)''', (user_id, action, timestamp))
        self.conn.commit()

    def add_user(self, user_id, username, first_name):
        cursor = self.conn.cursor()
        timestamp = self._get_utc_timestamp()
        cursor.execute('''INSERT OR IGNORE INTO users (user_id, username, first_name, date_added)
                          VALUES (?, ?, ?, ?)''', (user_id, username, first_name, timestamp))
        self.conn.commit()

    def add_chat(self, chat_id, chat_type, title):
        cursor = self.conn.cursor()
        timestamp = self._get_utc_timestamp()
        cursor.execute('''INSERT OR IGNORE INTO chats (chat_id, chat_type, title, date_added)
                          VALUES (?, ?, ?, ?)''', (chat_id, chat_type, title, timestamp))
        self.conn.commit()

    def get_all_users(self):
        cursor = self.conn.cursor()
        cursor.execute("SELECT user_id FROM users")
        return [row[0] for row in cursor.fetchall()]

    def get_all_chats(self):
        cursor = self.conn.cursor()
        cursor.execute("SELECT chat_id FROM chats")
        return [row[0] for row in cursor.fetchall()]

    def get_users_data(self):
        cursor = self.conn.cursor()
        cursor.execute("SELECT user_id, username, first_name, date_added FROM users")
        return cursor.fetchall()

    def get_chats_data(self):
        cursor = self.conn.cursor()
        cursor.execute("SELECT chat_id, chat_type, title, date_added FROM chats")
        return cursor.fetchall()

    def get_logs(self, limit=100):
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM logs ORDER BY timestamp DESC LIMIT ?", (limit,))
        return cursor.fetchall()

    def get_top(self):
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM top_bomjsfera ORDER BY place")
        return cursor.fetchall()

    def check_user_in_top(self, user_id):
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM top_bomjsfera WHERE user_id = ?", (user_id,))
        return cursor.fetchone()

    def get_all_top_users(self):
        cursor = self.conn.cursor()
        cursor.execute("SELECT user_id, username, tag FROM top_bomjsfera")
        return cursor.fetchall()

    def update_top(self, top_data):
        cursor = self.conn.cursor()
        cursor.execute("DELETE FROM top_bomjsfera")
        for place, (user_id, username, tag) in enumerate(top_data, 1):
            cursor.execute('''INSERT INTO top_bomjsfera (place, user_id, username, tag)
                              VALUES (?, ?, ?, ?)''', (place, user_id, username, tag))
        self.conn.commit()

    def add_to_top(self, user_id, username, tag):
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM top_bomjsfera WHERE user_id = ?", (user_id,))
        if cursor.fetchone():
            return False, "Пользователь уже в топе"

        cursor.execute("SELECT MAX(place) FROM top_bomjsfera")
        max_place = cursor.fetchone()[0]
        new_place = max_place + 1 if max_place else 1

        cursor.execute('''INSERT INTO top_bomjsfera (place, user_id, username, tag)
                          VALUES (?, ?, ?, ?)''', (new_place, user_id, username, tag))
        self.conn.commit()
        return True, f"Добавлен на {new_place} место"

    def remove_from_top(self, user_id):
        cursor = self.conn.cursor()
        cursor.execute("SELECT place FROM top_bomjsfera WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()

        if not result:
            return False, "Пользователь не найден в топе"

        old_place = result[0]
        cursor.execute("DELETE FROM top_bomjsfera WHERE user_id = ?", (user_id,))
        cursor.execute("UPDATE top_bomjsfera SET place = place - 1 WHERE place > ?", (old_place,))
        self.conn.commit()
        return True, f"Удален с {old_place} места"

    def edit_tag(self, user_id, new_tag):
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM top_bomjsfera WHERE user_id = ?", (user_id,))
        if not cursor.fetchone():
            return False, "Пользователь не найден в топе"

        cursor.execute("UPDATE top_bomjsfera SET tag = ? WHERE user_id = ?", (new_tag, user_id))
        self.conn.commit()
        return True, "Метка обновлена"

    def get_full_top(self):
        cursor = self.conn.cursor()
        cursor.execute("SELECT place, user_id, username, tag FROM top_bomjsfera ORDER BY place")
        return cursor.fetchall()


# ===== ХЭНДЛЕРЫ =====

db = Database()
router = Router()

COOLDOWN_PHRASES = [
    "Мать тенси строит мегахуй из лего, закончит через {minutes} минут.",
    "Твой хуй попал в чёрную дыру, вылезет через {minutes} минут.",
    "Твой хуй на карантине после контакта с матерью тенси, жди {minutes} минут.",
    "У тебя не хватает спермы для ёбли матери тенси, подожди {minutes} минут.",
    "Мать тенси устала. Дай ей {minutes} минут передышки.",
    "Мать тенси пошла за пивом, вернётся через {minutes} минут.",
    "Мать тенси чинит трактор, жди {minutes} минут.",
    "Мать тенси в бане с друзьями, подожди {minutes} минут.",
    "Мать тенси ушла на битву с бомжами, вернётся через {minutes} минут.",
    "Мать тенси на кулдауне. Вернись через {minutes} минут.",
]

FUCK_PHRASES = [
    "Ты выебал(-а) мать тенси {count} раз.",
    "Только что было вломано {count} дырок в матери тенси.",
    "Мать тенси получила {count} раз по самое не балуй.",
    "Добавлено {count} раз в коллекцию матери тенси.",
]


def check_bot_active():
    return db.get_bot_status()


# ===== /start =====

@router.message(Command("start"))
async def cmd_start(message: Message):
    if not check_bot_active() and message.from_user.id != ADMIN_ID:
        return

    user = message.from_user
    db.add_user(user.id, user.username, user.first_name)

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="Добавить в группу",
            url=f"https://t.me/{BOT_USERNAME}?startgroup=true",
            icon_custom_emoji_id="5222148368955877900"
        )],
        [InlineKeyboardButton(
            text="О создателе",
            callback_data="about",
            icon_custom_emoji_id="5350375974787630168"
        )],
    ])

    text = (
        "<blockquote><tg-emoji emoji-id=\"5350596259365273418\">👋</tg-emoji> Привет!</blockquote>\n\n"
        "Я богоподобный мега крутой бот созданный отцом всея сферы реикарне\n\n"
        "<blockquote><tg-emoji emoji-id=\"5350356823528455446\">✨</tg-emoji> Функционал</blockquote>\n\n"
        "Я составляю списки различных негативных личностей сферы. "
        "Помимо прочего являюсь развлекательным ботом для твоего проекта.\n\n"
        "<blockquote><tg-emoji emoji-id=\"5348412779596365405\">⚙️</tg-emoji> Команды</blockquote>\n\n"
        "/top — лист плохих людей сферы\n"
        "/scan — сканировать чат на наличие плохих людей сферы\n"
        "/tency — выебать мать тенси <i>(только в группах)</i>\n"
        "/top_fuck — топ ебателей в чате <i>(только в группах)</i>"
    )

    await message.answer(text, reply_markup=keyboard, parse_mode="HTML")


# ===== /tency =====

@router.message(Command("tency"))
async def cmd_tency(message: Message):
    if not check_bot_active() and message.from_user.id != ADMIN_ID:
        return

    if message.chat.type not in ["group", "supergroup"]:
        await message.answer("Команда /tency работает только в группах.")
        return

    chat_id = message.chat.id
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name

    allowed, remaining = db.check_tency_cooldown(chat_id, user_id)

    if not allowed:
        phrase = random.choice(COOLDOWN_PHRASES)
        await message.answer(phrase.format(minutes=remaining))
        return

    added_count = random.randint(1, 5)
    display_name = message.from_user.first_name or message.from_user.username or "Аноним"
    db.add_tency_count(chat_id, user_id, display_name, added_count)
    db.set_tency_cooldown(chat_id, user_id)

    user_total = db.get_tency_user_total(chat_id, user_id)

    response = (
        f"🌟 Ты выебал мать тенси <b>{added_count} раз!</b>\n"
        f"Всего выебано: <b>{user_total} раз.</b>\n\n"
        f"Следующая попытка через 15 минут."
    )
    await message.answer(response, parse_mode="HTML")


# ===== /top_fuck =====

@router.message(Command("top_fuck"))
async def cmd_top_fuck(message: Message):
    if not check_bot_active() and message.from_user.id != ADMIN_ID:
        return

    if message.chat.type not in ["group", "supergroup"]:
        await message.answer("Команда /top_fuck работает только в группах.")
        return

    chat_id = message.chat.id
    top_data = db.get_tency_chat_top(chat_id, limit=10)
    chat_stats = db.get_tency_chat_stats(chat_id)

    if not top_data:
        await message.answer("В этом чате ещё никто не ебал мать тенси. Используй /tency чтобы быть первым.")
        return

    top_text = "🏆 <b>Топ 10 пользователей:</b>\n\n"
    for i, (username, count) in enumerate(top_data, 1):
        top_text += f"{i} | {username}: <b>{count} очков</b>\n"

    top_text += f"\n<b>Всего выебано раз:</b> {chat_stats['total']}\n"
    top_text += f"Участников: {chat_stats['users']}"

    await message.answer(top_text, parse_mode="HTML")


# ===== /top =====

@router.message(Command("top"))
async def cmd_top(message: Message):
    if not check_bot_active() and message.from_user.id != ADMIN_ID:
        await message.answer("Бот на технических работах.")
        return

    top_data = db.get_top()
    if not top_data:
        await message.answer("Топ пока пуст.")
        return

    text = "Топ плохих людей сферы:\n\n"
    for row in top_data:
        place, user_id, username, tag = row
        text += f"{place}. {username}  ID: {user_id}  [{tag}]\n"

    text += f"\nДобавить кого-то? Пишите {CREATOR_USERNAME}"
    await message.answer(text)


# ===== /scan =====

@router.message(Command("scan"))
async def cmd_scan(message: Message):
    if not check_bot_active() and message.from_user.id != ADMIN_ID:
        await message.answer("Бот на технических работах.")
        return

    if message.chat.type not in ["group", "supergroup"]:
        await message.answer("Эта команда работает только в группах.")
        return

    try:
        chat_id = message.chat.id
        top_users = db.get_all_top_users()

        if not top_users:
            await message.answer("База пуста.")
            return

        found_users = []
        for user_id, username, tag in top_users:
            try:
                chat_member = await message.bot.get_chat_member(chat_id, user_id)
                if chat_member.status not in ["left", "kicked", "banned"]:
                    found_users.append(f"{username}  ID: {user_id}  [{tag}]")
            except:
                continue

        if found_users:
            text = "Внимание. В чате обнаружены нежелательные личности:\n\n"
            for user_info in found_users:
                text += f"— {user_info}\n"
            text += f"\nСообщите {CREATOR_USERNAME} если заметили активность."
        else:
            text = "Нежелательных личностей из базы в чате не обнаружено."

        await message.answer(text)

    except Exception:
        await message.answer("Ошибка сканирования. Убедитесь что бот имеет права администратора.")


# ===== CALLBACK: О СОЗДАТЕЛЕ =====

@router.callback_query(F.data == "about")
async def show_about(callback: CallbackQuery):
    if not check_bot_active() and callback.from_user.id != ADMIN_ID:
        await callback.answer("Бот на технических работах")
        return

    text = (
        "<tg-emoji emoji-id=\"5348582551063641258\">👤</tg-emoji> Создатель бота: "
        f"{CREATOR_USERNAME}\n\n"
        "<tg-emoji emoji-id=\"5350626912546865231\">📢</tg-emoji> Канал создателя: "
        f"{CREATOR_CHANNEL}\n\n"
        f"По вопросам сотрудничества и добавления в топ пишите {CREATOR_USERNAME}"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="Назад",
            callback_data="back_start",
            icon_custom_emoji_id="5291960936343561099"
        )]
    ])

    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "back_start")
async def back_to_start(callback: CallbackQuery):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="Добавить в группу",
            url=f"https://t.me/{BOT_USERNAME}?startgroup=true",
            icon_custom_emoji_id="5222148368955877900"
        )],
        [InlineKeyboardButton(
            text="О создателе",
            callback_data="about",
            icon_custom_emoji_id="5350375974787630168"
        )],
    ])

    text = (
        "<blockquote><tg-emoji emoji-id=\"5350596259365273418\">👋</tg-emoji> Привет!</blockquote>\n\n"
        "Я богоподобный мега крутой бот созданный отцом всея сферы реикарне\n\n"
        "<blockquote><tg-emoji emoji-id=\"5350356823528455446\">✨</tg-emoji> Функционал</blockquote>\n\n"
        "Я составляю списки различных негативных личностей сферы. "
        "Помимо прочего являюсь развлекательным ботом для твоего проекта.\n\n"
        "<blockquote><tg-emoji emoji-id=\"5348412779596365405\">⚙️</tg-emoji> Команды</blockquote>\n\n"
        "/top — лист плохих людей сферы\n"
        "/scan — сканировать чат на наличие плохих людей сферы\n"
        "/tency — выебать мать тенси <i>(только в группах)</i>\n"
        "/top_fuck — топ ебателей в чате <i>(только в группах)</i>"
    )

    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    await callback.answer()


# ===== АДМИН ПАНЕЛЬ =====

@router.message(Command("admin"))
async def cmd_admin(message: Message):
    if message.from_user.id != ADMIN_ID:
        return

    bot_status = "включен" if check_bot_active() else "выключен"

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="Пользователи", callback_data="admin_users_list")],
        [InlineKeyboardButton(text="Чаты", callback_data="admin_chats_list")],
        [InlineKeyboardButton(text="Управление топом", callback_data="admin_manage_top")],
        [InlineKeyboardButton(text="Рассылка всем", callback_data="admin_broadcast_all")],
        [InlineKeyboardButton(text="Рассылка юзерам", callback_data="admin_broadcast_users")],
        [InlineKeyboardButton(text="Рассылка в чаты", callback_data="admin_broadcast_groups")],
        [InlineKeyboardButton(text="Управление tency", callback_data="admin_tency")],
        [InlineKeyboardButton(
            text="Выключить бота" if check_bot_active() else "Включить бота",
            callback_data="admin_toggle_bot"
        )],
        [InlineKeyboardButton(text="Экспорт базы", callback_data="admin_export")],
        [InlineKeyboardButton(text="Закрыть", callback_data="admin_close")],
    ])

    await message.answer(
        f"Админ панель\nСтатус: {bot_status}\nСоздатель: {CREATOR_USERNAME}",
        reply_markup=keyboard
    )


@router.callback_query(F.data == "admin_close")
async def admin_close(callback: CallbackQuery):
    await callback.message.delete()
    await callback.answer()


@router.callback_query(F.data == "admin_stats")
async def admin_stats(callback: CallbackQuery):
    users = db.get_users_data()
    chats = db.get_chats_data()

    text = (
        f"Статистика бота:\n\n"
        f"Пользователей: {len(users)}\n"
        f"Чатов: {len(chats)}\n"
        f"В черном списке: {len(db.get_top())}"
    )

    await callback.message.edit_text(text)
    await callback.answer()


@router.callback_query(F.data == "admin_users_list")
async def admin_users_list(callback: CallbackQuery):
    users = db.get_users_data()
    text = f"Список пользователей ({len(users)}):\n\n"

    for user in users[-20:]:
        user_id, username, first_name, date_added = user
        text += f"ID: {user_id}\nЮзер: @{username or 'нет'}\nИмя: {first_name}\nДата: {date_added}\n"
        text += "─" * 20 + "\n"

    await callback.message.edit_text(text[:4000])
    await callback.answer()


@router.callback_query(F.data == "admin_chats_list")
async def admin_chats_list(callback: CallbackQuery):
    chats = db.get_chats_data()
    text = f"Список чатов ({len(chats)}):\n\n"

    for chat in chats:
        chat_id, chat_type, title, date_added = chat
        text += f"ID: {chat_id}\nТип: {chat_type}\nНазвание: {title}\nДата: {date_added}\n"
        text += "─" * 20 + "\n"

    await callback.message.edit_text(text[:4000])
    await callback.answer()


@router.callback_query(F.data == "admin_manage_top")
async def admin_manage_top(callback: CallbackQuery):
    text = (
        "Управление черным списком\n\n"
        "Команды:\n"
        "/add_user ID @username метка\n"
        "/remove_user ID\n"
        "/edit_tag ID новая_метка\n"
        "/full_top — полный список с ID\n"
        "/search_user ID/@username — поиск"
    )
    await callback.message.edit_text(text)
    await callback.answer()


@router.callback_query(F.data == "admin_broadcast_all")
async def admin_broadcast_all_cb(callback: CallbackQuery):
    await callback.message.edit_text(
        "Рассылка всем:\n/broadcast_all ваш текст"
    )
    await callback.answer()


@router.callback_query(F.data == "admin_broadcast_users")
async def admin_broadcast_users_cb(callback: CallbackQuery):
    await callback.message.edit_text(
        "Рассылка юзерам:\n/broadcast_users ваш текст"
    )
    await callback.answer()


@router.callback_query(F.data == "admin_broadcast_groups")
async def admin_broadcast_groups_cb(callback: CallbackQuery):
    await callback.message.edit_text(
        "Рассылка в чаты:\n/broadcast_groups ваш текст"
    )
    await callback.answer()


@router.callback_query(F.data == "admin_tency")
async def admin_tency(callback: CallbackQuery):
    text = (
        "Управление статистикой tency\n\n"
        "/reset_tency [chat_id] — сбросить статистику в чате\n"
        "/tency_stats [chat_id] — статистика по чату"
    )
    await callback.message.edit_text(text)
    await callback.answer()


@router.callback_query(F.data == "admin_toggle_bot")
async def admin_toggle_bot(callback: CallbackQuery):
    current_status = check_bot_active()
    db.set_bot_status(not current_status)

    new_status = "включен" if not current_status else "выключен"
    await callback.answer(f"Бот {new_status}")

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="Пользователи", callback_data="admin_users_list")],
        [InlineKeyboardButton(text="Чаты", callback_data="admin_chats_list")],
        [InlineKeyboardButton(text="Управление топом", callback_data="admin_manage_top")],
        [InlineKeyboardButton(text="Рассылка всем", callback_data="admin_broadcast_all")],
        [InlineKeyboardButton(text="Рассылка юзерам", callback_data="admin_broadcast_users")],
        [InlineKeyboardButton(text="Рассылка в чаты", callback_data="admin_broadcast_groups")],
        [InlineKeyboardButton(text="Управление tency", callback_data="admin_tency")],
        [InlineKeyboardButton(
            text="Выключить бота" if not current_status else "Включить бота",
            callback_data="admin_toggle_bot"
        )],
        [InlineKeyboardButton(text="Экспорт базы", callback_data="admin_export")],
        [InlineKeyboardButton(text="Закрыть", callback_data="admin_close")],
    ])

    await callback.message.edit_text(
        f"Админ панель\nСтатус: {new_status}\nСоздатель: {CREATOR_USERNAME}",
        reply_markup=keyboard
    )


@router.callback_query(F.data == "admin_export")
async def admin_export(callback: CallbackQuery):
    if os.path.exists("bot.db"):
        file = FSInputFile("bot.db")
        await callback.message.bot.send_document(
            callback.message.chat.id, file, caption="База данных бота"
        )
    else:
        await callback.message.edit_text("Файл базы данных не найден")
    await callback.answer()


# ===== РАССЫЛКА =====

@router.message(Command("broadcast_all"))
async def cmd_broadcast_all(message: Message):
    if message.from_user.id != ADMIN_ID:
        return

    broadcast_text = message.text.replace("/broadcast_all", "").strip()
    if not broadcast_text:
        await message.answer("Введите текст рассылки после команды")
        return

    users = db.get_all_users()
    chats = db.get_all_chats()
    await message.answer(f"Начинаю рассылку... Пользователей: {len(users)}, чатов: {len(chats)}")

    sent_users = sent_chats = 0
    for user_id in users:
        try:
            await message.bot.send_message(user_id, broadcast_text)
            sent_users += 1
        except:
            pass
    for chat_id in chats:
        try:
            await message.bot.send_message(chat_id, broadcast_text)
            sent_chats += 1
        except:
            pass

    db.log_action(message.from_user.id, "broadcast_all")
    await message.answer(f"Рассылка завершена. Пользователям: {sent_users}, чатам: {sent_chats}")


@router.message(Command("broadcast_users"))
async def cmd_broadcast_users(message: Message):
    if message.from_user.id != ADMIN_ID:
        return

    broadcast_text = message.text.replace("/broadcast_users", "").strip()
    if not broadcast_text:
        await message.answer("Введите текст рассылки после команды")
        return

    users = db.get_all_users()
    sent = 0
    for user_id in users:
        try:
            await message.bot.send_message(user_id, broadcast_text)
            sent += 1
        except:
            pass

    db.log_action(message.from_user.id, "broadcast_users")
    await message.answer(f"Рассылка пользователям завершена. Доставлено: {sent}")


@router.message(Command("broadcast_groups"))
async def cmd_broadcast_groups(message: Message):
    if message.from_user.id != ADMIN_ID:
        return

    broadcast_text = message.text.replace("/broadcast_groups", "").strip()
    if not broadcast_text:
        await message.answer("Введите текст рассылки после команды")
        return

    chats = db.get_all_chats()
    sent = 0
    for chat_id in chats:
        try:
            await message.bot.send_message(chat_id, broadcast_text)
            sent += 1
        except:
            pass

    db.log_action(message.from_user.id, "broadcast_groups")
    await message.answer(f"Рассылка в чаты завершена. Доставлено: {sent}")


# ===== УПРАВЛЕНИЕ ТОПОМ =====

@router.message(Command("add_user"))
async def cmd_add_user(message: Message):
    if message.from_user.id != ADMIN_ID:
        return

    args = message.text.split(maxsplit=3)
    if len(args) < 4:
        await message.answer("Формат: /add_user ID username метка")
        return

    try:
        user_id = int(args[1])
        username = args[2] if args[2].startswith('@') else f"@{args[2]}"
        tag = args[3]
        success, result = db.add_to_top(user_id, username, tag)
        await message.answer(result)
    except ValueError:
        await message.answer("ID должен быть числом")


@router.message(Command("remove_user"))
async def cmd_remove_user(message: Message):
    if message.from_user.id != ADMIN_ID:
        return

    args = message.text.split()
    if len(args) < 2:
        await message.answer("Формат: /remove_user ID")
        return

    try:
        user_id = int(args[1])
        success, result = db.remove_from_top(user_id)
        await message.answer(result)
    except ValueError:
        await message.answer("ID должен быть числом")


@router.message(Command("edit_tag"))
async def cmd_edit_tag(message: Message):
    if message.from_user.id != ADMIN_ID:
        return

    args = message.text.split(maxsplit=2)
    if len(args) < 3:
        await message.answer("Формат: /edit_tag ID новая_метка")
        return

    try:
        user_id = int(args[1])
        new_tag = args[2]
        success, result = db.edit_tag(user_id, new_tag)
        await message.answer(result)
    except ValueError:
        await message.answer("ID должен быть числом")


@router.message(Command("full_top"))
async def cmd_full_top(message: Message):
    if message.from_user.id != ADMIN_ID:
        return

    top_data = db.get_full_top()
    if not top_data:
        await message.answer("Топ пуст")
        return

    text = "Полный список топа:\n\n"
    for place, user_id, username, tag in top_data:
        text += f"{place}. {username} (ID: {user_id})\n   Метка: {tag}\n\n"
    text += f"Всего записей: {len(top_data)}"
    await message.answer(text)


@router.message(Command("search_user"))
async def cmd_search_user(message: Message):
    if message.from_user.id != ADMIN_ID:
        return

    args = message.text.split()
    if len(args) < 2:
        await message.answer("Формат: /search_user ID или /search_user @username")
        return

    search_term = args[1]
    cursor = db.conn.cursor()

    if search_term.isdigit():
        cursor.execute("SELECT place, user_id, username, tag FROM top_bomjsfera WHERE user_id = ?", (int(search_term),))
    elif search_term.startswith('@'):
        cursor.execute("SELECT place, user_id, username, tag FROM top_bomjsfera WHERE username LIKE ?", (f"%{search_term}%",))
    else:
        cursor.execute("SELECT place, user_id, username, tag FROM top_bomjsfera WHERE username LIKE ?", (f"%@{search_term}%",))

    result = cursor.fetchall()
    if not result:
        await message.answer("Пользователь не найден в топе")
        return

    text = "Результаты поиска:\n\n"
    for place, user_id, username, tag in result:
        text += f"Место: {place}\nЮзер: {username}\nID: {user_id}\nМетка: {tag}\n"
        text += "─" * 20 + "\n"
    await message.answer(text)


# ===== ADMIN TENCY COMMANDS =====

@router.message(Command("reset_tency"))
async def cmd_reset_tency(message: Message):
    if message.from_user.id != ADMIN_ID:
        return

    args = message.text.split()
    if len(args) < 2:
        await message.answer("Укажите chat_id: /reset_tency [chat_id]")
        return

    try:
        chat_id = int(args[1])
        reset_count = db.reset_tency_chat_stats(chat_id)
        await message.answer(f"Статистика tency сброшена в чате {chat_id}. Удалено записей: {reset_count}")
    except ValueError:
        await message.answer("chat_id должен быть числом")


@router.message(Command("tency_stats"))
async def cmd_tency_stats(message: Message):
    if message.from_user.id != ADMIN_ID:
        return

    args = message.text.split()
    if len(args) < 2:
        await message.answer("Укажите chat_id: /tency_stats [chat_id]")
        return

    try:
        chat_id = int(args[1])
        top_data = db.get_tency_chat_top(chat_id, limit=20)
        chat_stats = db.get_tency_chat_stats(chat_id)

        if not top_data:
            await message.answer(f"В чате {chat_id} нет статистики tency")
            return

        text = f"Статистика tency для чата {chat_id}:\n\n"
        for i, (username, count) in enumerate(top_data, 1):
            text += f"{i}. {username} — {count} раз\n"
        text += f"\nВсего: {chat_stats['total']} раз\n"
        text += f"Уникальных: {chat_stats['users']}"

        await message.answer(text[:4000])
    except ValueError:
        await message.answer("chat_id должен быть числом")


# ===== АВТОРЕГИСТРАЦИЯ В ЧАТАХ =====

@router.message()
async def handle_group(message: Message):
    if not check_bot_active() and message.from_user.id != ADMIN_ID:
        return

    if message.chat.type in ["group", "supergroup"]:
        db.add_chat(message.chat.id, message.chat.type, message.chat.title)


# ===== РЕГИСТРАЦИЯ КОМАНД И ЗАПУСК =====

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def set_commands(bot: Bot):
    # Команды в личке
    private_commands = [
        BotCommand(command="start", description="Запустить бота"),
        BotCommand(command="top", description="Лист плохих людей сферы"),
    ]
    await bot.set_my_commands(private_commands, scope=BotCommandScopeAllPrivateChats())

    # Команды в группах
    group_commands = [
        BotCommand(command="top", description="Лист плохих людей сферы"),
        BotCommand(command="scan", description="Сканировать чат"),
        BotCommand(command="tency", description="Выебать мать тенси"),
        BotCommand(command="top_fuck", description="Топ ебателей в чате"),
    ]
    await bot.set_my_commands(group_commands, scope=BotCommandScopeAllGroupChats())


async def main():
    session = AiohttpSession(timeout=30)

    bot = Bot(
        token=BOT_TOKEN,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )

    dp = Dispatcher()
    dp.include_router(router)

    await set_commands(bot)

    try:
        await dp.start_polling(
            bot,
            allowed_updates=dp.resolve_used_update_types(),
            drop_pending_updates=True
        )
    except Exception as e:
        logger.error(f"Ошибка поллинга: {e}")
        raise


if __name__ == "__main__":
    while True:
        try:
            asyncio.run(main())
        except KeyboardInterrupt:
            logger.info("Бот остановлен")
            break
        except Exception as e:
            logger.error(f"Критическая ошибка: {e}")
            logger.info("Перезапуск через 10 секунд...")
            time.sleep(10)