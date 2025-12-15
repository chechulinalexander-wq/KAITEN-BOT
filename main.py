import os
import sys
import json
import asyncio
import requests
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from openai import OpenAI

TZ_MOSCOW = timezone(timedelta(hours=3))

if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENAI_KEY = os.getenv("OPENAI_API_KEY")
KAITEN_API_KEY = os.getenv("KAITEN_API_KEY")
KAITEN_BASE_URL = "https://vash-1c.kaiten.ru/api/latest"

client = OpenAI(api_key=OPENAI_KEY)
TASKS_DIR = "tasks"

# Kaiten board/column mapping
KAITEN_MAPPING = {
    "Этот месяц": {"board_id": 300338, "column_id": 1017212, "lane_id": 415476},
    "Этот день": {"board_id": 300338, "column_id": 1017213, "lane_id": 415476},
    "Запланировано на конкретную дату": {"board_id": 301949, "column_id": 1022208, "lane_id": 417486},
    "Делегировано мне": {"board_id": 300339, "column_id": 1017215, "lane_id": 415477},
    "Делегировал исполнителю": {"board_id": 300339, "column_id": 1017216, "lane_id": 415477},
}

if not os.path.exists(TASKS_DIR):
    os.makedirs(TASKS_DIR)


def create_kaiten_card(task_data: dict) -> dict:
    """Create a card in Kaiten board"""
    kanban_column = task_data.get("kanban_column", "Этот месяц")
    mapping = KAITEN_MAPPING.get(kanban_column, KAITEN_MAPPING["Этот месяц"])

    card_data = {
        "title": task_data.get("content", "Новая задача"),
        "board_id": mapping["board_id"],
        "column_id": mapping["column_id"],
        "lane_id": mapping["lane_id"],
    }

    if task_data.get("due_date"):
        card_data["due_date"] = task_data["due_date"]

    headers = {
        "Authorization": f"Bearer {KAITEN_API_KEY}",
        "Content-Type": "application/json; charset=utf-8"
    }

    try:
        response = requests.post(
            f"{KAITEN_BASE_URL}/cards",
            headers=headers,
            data=json.dumps(card_data, ensure_ascii=False).encode('utf-8'),
            timeout=10
        )
        response.raise_for_status()
        result = response.json()
        print(f"✅ Kaiten card created: {result.get('id')}")
        return {"success": True, "card_id": result.get("id"), "card_uid": result.get("uid")}
    except Exception as e:
        print(f"❌ Kaiten API Error: {e}")
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e)}


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command"""
    await update.message.reply_text(
        "👋 Привет! Отправь мне описание задачи, и я её проанализирую.\n"
        "Я определю: содержание, дату выполнения и категорию Канбан."
    )


async def transcribe_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Transcribe voice message using Whisper"""
    await update.message.chat.send_action("typing")

    try:
        voice = update.message.voice
        file = await context.bot.get_file(voice.file_id)

        audio_path = f"temp_audio_{update.message.message_id}.ogg"
        await file.download_to_drive(audio_path)

        with open(audio_path, "rb") as audio_file:
            transcript = client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
                language="ru"
            )

        user_message = transcript.text
        os.remove(audio_path)

        print(f"🎤 Voice transcribed: {user_message}")

        await validate_task(update, context, user_message)

    except Exception as e:
        print(f"❌ Transcription Error: {e}")
        await update.message.reply_text(f"❌ Ошибка при обработке голоса: {str(e)}")


async def analyze_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Analyze incoming text message with OpenAI"""
    user_message = update.message.text
    await validate_task(update, context, user_message)


def is_obviously_not_task(text: str) -> bool:
    """Quick local check for obvious non-tasks"""
    if len(text.strip()) < 2:
        return True

    word_count = len(text.split())
    if word_count == 1:
        return True

    suspicious_patterns = [
        'лол', 'кек', 'хех', 'ха', 'ху', 'охе', 'охуе', 'чебурек',
        'привет', 'привтии', 'привет', 'hello', 'hi', 'yo',
        'дай', 'кур', 'бля', 'пошел', 'ладно', 'окей', 'ок'
    ]

    text_lower = text.lower().strip()
    if text_lower in suspicious_patterns:
        return True

    if text_lower.startswith('охуе'):
        return True

    return False


async def validate_task(update: Update, context: ContextTypes.DEFAULT_TYPE, user_message: str) -> None:
    """Validate if message is a real task"""
    await update.message.chat.send_action("typing")

    if is_obviously_not_task(user_message):
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Да, это задача", callback_data=f"confirm_{update.message.message_id}"),
                InlineKeyboardButton("❌ Отмена", callback_data=f"cancel_{update.message.message_id}")
            ]
        ])

        context.user_data[f"pending_task_{update.message.message_id}"] = user_message

        await update.message.reply_text(
            f"🤔 Это похоже на случайное сообщение, а не на задачу.\n\n"
            f"Ты всё равно хочешь сохранить это как задачу?",
            reply_markup=keyboard
        )
        print(f"⚠️ Obvious non-task detected: {user_message}")
        return

    today = datetime.now(TZ_MOSCOW).strftime("%Y-%m-%d")

    validation_prompt = f"""СТРОГО проверь, является ли это сообщение конкретной ЗАДАЧЕЙ/ДЕЛОМ.

Сообщение: "{user_message}"

Верни JSON:
{{
  "is_valid_task": true или false,
  "confidence": число от 0 до 100
}}

ЗАДАЧА - это конкретное действие с понятной целью:
✅ "Купить молоко", "Позвонить клиенту", "Подготовить отчёт", "Завтра встреча в 10", "Петя должен написать код"

НЕ ЗАДАЧА - случайный текст, междометия, ненормальные слова, приветствия:
❌ "Охуенчик", "Привет", "Лол", "Кек", "Хелло", "123", просто одно-два слова без смысла

ПРАВИЛО: Если сообщение длинное (более 3 слов) и имеет смысл - вероятнее задача.
Если это просто странное слово или междометие - это точно НЕ задача.

Будь строг! Лучше переспросить чем сохранить мусор.
"""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": validation_prompt}],
            temperature=0.3,
        )

        validation_text = response.choices[0].message.content.strip()
        validation_data = json.loads(validation_text)

        if not validation_data.get("is_valid_task", False):
            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("✅ Да, это задача", callback_data=f"confirm_{update.message.message_id}"),
                    InlineKeyboardButton("❌ Отмена", callback_data=f"cancel_{update.message.message_id}")
                ]
            ])

            context.user_data[f"pending_task_{update.message.message_id}"] = user_message

            await update.message.reply_text(
                f"🤔 Это похоже на случайное сообщение, а не на задачу.\n\n"
                f"Ты всё равно хочешь сохранить это как задачу?",
                reply_markup=keyboard
            )
            print(f"⚠️ Validation failed: {validation_data.get('reason')}")
            return

        await analyze_task(update, context, user_message)

    except Exception as e:
        print(f"❌ Validation Error: {e}")
        await analyze_task(update, context, user_message)


async def handle_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle task confirmation buttons"""
    query = update.callback_query
    await query.answer()

    message_id = query.data.split("_")[1]
    pending_key = f"pending_task_{message_id}"

    if "confirm" in query.data:
        if pending_key in context.user_data:
            user_message = context.user_data[pending_key]
            del context.user_data[pending_key]

            await query.edit_message_text("✅ Обработка...")
            await analyze_task(update, context, user_message)
        else:
            await query.edit_message_text("⚠️ Сессия истекла. Отправь сообщение заново.")

    elif "cancel" in query.data:
        if pending_key in context.user_data:
            del context.user_data[pending_key]
        await query.edit_message_text("❌ Задача отменена.")


async def analyze_task(update: Update, context: ContextTypes.DEFAULT_TYPE, user_message: str) -> None:
    """Core task analysis logic"""
    await update.message.chat.send_action("typing")

    today = datetime.now(TZ_MOSCOW).strftime("%Y-%m-%d")

    prompt = f"""Проанализируй это сообщение про задачу и верни ТОЛЬКО JSON:

Сообщение: "{user_message}"

Сегодня: {today}

Верни ТОЛЬКО валидный JSON без дополнительного текста:
{{
  "content": "суть задачи (обязательно)",
  "due_date": "YYYY-MM-DD или null",
  "kanban_column": "одна из: Этот месяц, Этот день, Запланировано на конкретную дату, Делегировано мне, Делегировал исполнителю"
}}

Правила:
- "Этот день" если срочно/сегодня/ASAP
- "Запланировано на конкретную дату" если есть конкретная дата ≠ сегодня
- "Делегировано мне" если кто-то задачу поручил
- "Делегировал исполнителю" если я кому-то поручил
- "Этот месяц" если срок неясен (fallback)
- due_date = null если дата не определена
"""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
        )

        response_text = response.choices[0].message.content.strip()

        task_data = json.loads(response_text)

        timestamp = datetime.now(TZ_MOSCOW).strftime("%Y%m%d_%H%M%S")
        filename = f"{TASKS_DIR}/task_{timestamp}.json"

        task_data["original_message"] = user_message
        task_data["created_at"] = datetime.now(TZ_MOSCOW).isoformat()

        with open(filename, "w", encoding="utf-8") as f:
            json.dump(task_data, f, ensure_ascii=False, indent=2)

        # Create card in Kaiten
        kaiten_result = create_kaiten_card(task_data)

        due_date_display = task_data.get("due_date")
        if due_date_display:
            due_date_display = datetime.strptime(due_date_display, "%Y-%m-%d").strftime("%d.%m.%Y")

        response_text = (
            f"✅ Задача сохранена\n\n"
            f"📝 Содержание: {task_data.get('content', 'N/A')}\n"
        )

        if task_data.get("due_date"):
            response_text += f"📅 Срок: {due_date_display}\n"

        response_text += f"📊 Колонка: {task_data.get('kanban_column', 'N/A')}\n"

        if kaiten_result.get("success"):
            response_text += f"🔗 Kaiten: карточка #{kaiten_result.get('card_id')} создана"
        else:
            response_text += f"⚠️ Kaiten: ошибка ({kaiten_result.get('error', 'unknown')})"

        await update.message.reply_text(response_text)

        print(f"✅ Task saved: {filename}")
        print(f"Content: {task_data}")
        print(f"Kaiten: {kaiten_result}")

    except json.JSONDecodeError as e:
        print(f"❌ JSON Error: {e}")
        print(f"Response: {response_text}")
        await update.message.reply_text(
            "❌ Ошибка при анализе. Попробуй ещё раз с более чётким описанием."
        )
    except Exception as e:
        print(f"❌ Error: {e}")
        await update.message.reply_text(f"❌ Ошибка: {str(e)}")


if __name__ == "__main__":
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_confirmation))
    app.add_handler(MessageHandler(filters.VOICE, transcribe_voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, analyze_message))

    print("🤖 Bot started. Press Ctrl+C to stop.")
    print("📝 Supports: text messages and voice messages")
    print("✓ Task validation enabled")
    app.run_polling()
