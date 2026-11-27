import asyncio
import json
import os
import re
import uuid
from datetime import date, datetime, timedelta
from urllib.parse import quote

from loguru import logger
from vkbottle.bot import Bot, Message
from vkbottle import Keyboard, KeyboardButtonColor, Text, OpenLink

import state
import texts
import keyboards as kb
import sheets
import ai
from programs import PROGRAMS

VK_TOKEN = os.getenv("VK_GROUP_TOKEN")
VK_GROUP_ID = int(os.getenv("VK_GROUP_ID", "0"))
ADMIN_VK_ID = int(os.getenv("ADMIN_VK_ID", "0"))
HOLD_MIN = 15

if not VK_TOKEN:
    raise RuntimeError("VK_GROUP_TOKEN не задан!")

bot = Bot(token=VK_TOKEN)
bot.labeler.vbml_ignore_case = True

PDF_GUIDE_URL = "https://disk.yandex.ru/i/skazka_guide_pdf"

async def send_thinking(message: Message, text: str, keyboard: str = None):
    if not text: return
    parts = [p.strip() for p in text.split("\n\n") if p.strip()]
    if not parts: return
    try:
        for i, part in enumerate(parts):
            await bot.api.messages.set_activity(type='typing', peer_id=message.peer_id)
            delay = min(max(0.5, len(part) * 0.02), 2.0)
            await asyncio.sleep(delay)
            is_last = (i == len(parts) - 1)
            kb_val = keyboard if is_last else None
            await message.answer(part, keyboard=kb_val)
    except Exception as e:
        logger.error(f"Ошибка в send_thinking: {e}")

def parse_payload(message: Message) -> str:
    p = getattr(message, "payload", None)
    if isinstance(p, dict): return p.get("cmd") or ""
    if isinstance(p, str):
        try: return (json.loads(p) or {}).get("cmd") or ""
        except Exception: return ""
    return ""

async def safe_name(message: Message) -> str:
    try:
        u = (await bot.api.users.get(user_ids=message.from_id))[0]
        return u.first_name or "друг"
    except Exception:
        return "друг"

async def notify_admin(text: str) -> None:
    if not ADMIN_VK_ID: return
    try:
        await bot.api.messages.send(user_id=ADMIN_VK_ID, message=text, random_id=0)
    except Exception as e:
        logger.error("admin notify: {}", e)

def build_review_text(st: state.UserState) -> str:
    d = st.draft
    extras = ", ".join(state.EXTRA_NAMES[e] for e in d.get("extras", [])) or "нет"
    children_str = ", ".join(d.get("children", [])) or "нет"
    pkg_name = PROGRAMS.get(d.get("package", ""), {}).get("title", "")
    total = state.calc_total(d)
    lines = [
        f"🏙 Город: {d.get('city', '')}",
        f"🎯 Для кого: {d.get('audience', '').replace('aud_', '')}",
        f"👦 Дети: {children_str}",
        f"📅 {d.get('date_display', '')} в {d.get('time_display', '')}",
        f"🎁 Программа: {pkg_name}",
        f"➕ Допы: {extras}", f"📍 {d.get('address', '')}", f"📞 {d.get('phone', '')}",
        f"💰 Итого: {int(total)} ₽"
    ]
    return "\n".join(lines)

def share_url_for(vk_id: int) -> str:
    bot_link = f"https://vk.me/club{VK_GROUP_ID}"
    return f"https://vk.com/share.php?url={quote(bot_link)}&title={quote('Забронировали Деда Мороза!')}"

async def step_welcome(message: Message, st: state.UserState):
    st.step = "city"
    st.draft = {}
    await send_thinking(message, texts.WELCOME.format(name=st.name), keyboard=kb.kb_main())

async def step_audience(message: Message, st: state.UserState):
    st.step = "audience"
    await send_thinking(message, texts.ASK_AUDIENCE.format(city=st.draft.get("city", "")), keyboard=kb.kb_audience())

async def step_children_count(message: Message, st
