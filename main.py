import asyncio
import json
import os
import re
import uuid
from datetime import date, datetime
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

# --- Только отправка, без сложных разбивок ---
async def send_message(message: Message, text: str, keyboard: str = None):
    if not text: return
    try:
        await bot.api.messages.set_activity(type='typing', peer_id=message.peer_id)
        await asyncio.sleep(0.4)
        await message.answer(text, keyboard=keyboard)
    except Exception as e:
        logger.error(f"Ошибка отправки: {e}")

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

# --- Сборка карточки ---
def build_review_text(st: state.UserState) -> str:
    d = st.draft
    extras = ", ".join(state.EXTRA_NAMES[e] for e in d.get("extras", [])) or "нет"
    pkg_name = PROGRAMS.get(d.get("package", ""), {}).get("title", "")
    total = state.calc_total(d)
    lines = [
        f"🏙 Город: {d.get('city', '')}",
        f"🎯 Формат: {d.get('audience', '').replace('aud_', '')}",
        f"🎁 Программа: {pkg_name}",
        f"➕ Допы: {extras}",
        f"💰 Итого: {int(total)} ₽"
    ]
    return "\n".join(lines)

def share_url_for(vk_id: int) -> str:
    bot_link = f"https://vk.me/club{VK_GROUP_ID}"
    return f"https://vk.com/share.php?url={quote(bot_link)}&title={quote('Забронировали Деда Мороза!')}"

# ================= ШАГИ =================

async def step_city(message: Message, st: state.UserState):
    st.step = "city"
    st.draft = {}
    await send_message(message, texts.WELCOME.format(name=st.name), keyboard=kb.kb_cities())

async def step_audience(message: Message, st: state.UserState):
    st.step = "audience"
    await send_message(message, texts.ASK_AUDIENCE.format(city=st.draft.get("city", "")), keyboard=kb.kb_audience())

async def step_children_count(message: Message, st: state.UserState):
    st.step = "children_count"
    await send_message(message, texts.ASK_CHILDREN_COUNT, keyboard=kb.kb_children_count())

async def step_package(message: Message, st: state.UserState):
    st.step = "package"
    audience = st.draft.get("audience", "mixed")
    
    suitable = {k: v for k, v in PROGRAMS.items() if (v["for"] == "kids" and audience in ["kids", "mixed"]) or (v["for"] == "adults" and audience in ["adults", "mixed"])}
    
    program_list = ""
    for key, p in suitable.items():
        program_list += f"🎁 {p['title']} — {p['price']} ₽\n"
        program_list += f"⏱ {p['duration']} · {p['desc']}\n"
        program_list += f"👥 {p['details']}\n\n"
    
    text = texts.ASK_PACKAGE_DETAILS.format(program_list=program_list.strip())
    await send_message(message, text, keyboard=kb.kb_package(audience))

async def step_extras(message: Message, st: state.UserState):
    st.step = "extras"
    await send_message(message, texts.ASK_EXTRAS, keyboard=kb.kb_extras(st.draft))

async def step_review(message: Message, st: state.UserState):
    st.step = "review"
    header = texts.REVIEW_HEADER.format(name=st.name)
    full_text = header + "\n" + build_review_text(st) + "\n" + texts.REVIEW_GUARANTEE
    await send_message(message, full_text, keyboard=kb.kb_review())

async def step_payment(message: Message, st: state.UserState):
    st.step = "payment"
    booking = state.create_booking(message.from_id, st.draft)
    slot = await state.hold_slot(booking.slot_id, booking.id, HOLD_MIN)
    if not slot:
        await send_message(message, texts.SLOT_TAKEN, keyboard=kb.kb_main())
        st.step = "main"
        return
    st.draft["booking_id"] = str(booking.id)
    await send_message(message, texts.PAYMENT_SCREEN, keyboard=kb.kb_payment())

async def step_confirm_payment(message: Message, st: state.UserState):
    bid_str = st.draft.get("booking_id")
    if not bid_str: return
    bid = uuid.UUID(bid_str)
    if not await state.confirm_booking(bid): return

    d = st.draft
    children_names = ", ".join(d.get("children", [])) or "вашим гостям"
    
    asyncio.create_task(sheets.log_booking({
        "date": d.get("date_display", ""), "time": d.get("time_display", ""), 
        "vk_id": message.from_id, "user_name": st.name,
        "city": d.get("city", ""), "audience": d.get("audience", ""),
        "children": children_names, "package": PROGRAMS.get(d.get("package", ""), {}).get("title", ""),
        "extras": ", ".join(state.EXTRA_NAMES[e] for e in d.get("extras", [])),
        "address": d.get("address", ""), "phone": d.get("phone", ""),
        "total": str(state.calc_total(d))
    }))

    paid_header = texts.PAID_HEADER.format(name=st.name)
    paid_body = texts.PAID_BODY.format(
        date=d.get("date_display", ""), time=d.get("time_display", ""), 
        address=d.get("address", ""), package=PROGRAMS.get(d.get("package", ""), {}).get("title", ""),
        total=int(state.calc_total(d))
    )
    
    kb_with_pdf = Keyboard(one_time=False, inline=False)
    kb_with_pdf.add(OpenLink(PDF_GUIDE_URL, "📄 Скачать PDF-гайд"), color=KeyboardButtonColor.POSITIVE)
    kb_with_pdf.row()
    kb_with_pdf.add(Text("🏠 В меню", payload={"cmd": "back_main"}), color=KeyboardButtonColor.SECONDARY)
    
    await send_message(message, paid_header + "\n\n" + paid_body, keyboard=kb_with_pdf.get_json())
    st.step = "done"

async def enter_operator(message: Message, st: state.UserState):
    st.operator_mode = True
    await send_message(message, texts.OPERATOR_REQUESTED, keyboard=kb.kb_main())
    await notify_admin(texts.ADMIN_NEW_CLIENT.format(name=st.name or f"user_{st.vk_id}", vk_id=st.vk_id, snippet="Нажал «Живой человек»", funnel_stage=st.step))

# ================= РОУТЕР =================
@bot.on.message()
async def router(message: Message):
    try:
        vk_id = message.from_id
        st = state.get_user(vk_id)
        if not st.name:
            st.name = await safe_name(message)

        text_raw = (message.text or "").strip()
        cmd = parse_payload(message)

        # Админ-команды
        if vk_id == ADMIN_VK_ID and text_raw.startswith("/"):
            if text_raw.startswith("/take "):
                uid = int(text_raw.split()[1]); s = state.get_user(uid); s.operator_mode = True
                await message.answer(texts.ADMIN_TAKEN.format(vk_id=uid)); return
            if text_raw.startswith("/release "):
                uid = int(text_raw.split()[1]); s = state.get_user(uid); s.operator_mode = False
                await message.answer(texts.ADMIN_RELEASED.format(vk_id=uid))
                try: await bot.api.messages.send(user_id=uid, message=texts.OPERATOR_RETURNED, random_id=0, keyboard=kb.kb_main())
                except: pass
                return

        if st.operator_mode:
            await notify_admin(f"💬 {st.name} ({vk_id}):\n{text_raw[:500]}"); return

        # Ввод текста (если не кнопка)
        if not cmd and text_raw:
            if st.step == "city":
                st.draft["city"] = text_raw
                await step_audience(message, st); return

        # Кнопки
        if text_raw.lower().startswith("/start"):
            await step_city(message, st); return
        if cmd == "book": 
            await step_city(message, st); return 
        if cmd == "operator":
            await enter_operator(message, st); return
        if cmd == "back_main":
            await step_city(message, st); return

        # 1. Города
        if cmd.startswith("city_"):
            city_map = {"city_ekb": "Екатеринбург", "city_tmn": "Тюмень", "city_krg": "Курган"}
            st.draft["city"] = city_map.get(cmd, "Город")
            await step_audience(message, st); return

        # 2. Аудитория
        if cmd in ("aud_kids", "aud_adults", "aud_mixed"):
            st.draft["audience"] = cmd
            if cmd == "aud_adults":
                st.draft["target_children_count"] = 0
                await step_package(message, st)
            else:
                await step_children_count(message, st)
            return

        # 3. Кол-во детей
        if cmd.startswith("children_"):
            count = 4 if cmd.split("_")[1] == "4" else int(cmd.split("_")[1])
            st.draft["target_children_count"] = count
            st.draft["current_child_idx"] = 0
            await step_package(message, st); return

        # 4. Программа
        if cmd.startswith("pkg_"):
            st.draft["package"] = cmd.replace("pkg_", "")
            st.draft["extras"] = []
            await step_extras(message, st); return

        # 5. Допы
        if cmd in ("extra_photo", "extra_bubbles", "extra_snow", "extra_gifts"):
            key = cmd.split("_", 1)[1]; chosen = set(st.draft.get("extras", []))
            chosen.symmetric_difference_update({key}); st.draft["extras"] = list(chosen)
            await send_message(message, "Отмечено.", keyboard=kb.kb_extras(st.draft)); return
        if cmd == "extras_done": await step_review(message, st); return

        # 6. Подтверждение
        if cmd == "review_ok":
            st.step = "consent"; await send_message(message, texts.CONSENT, keyboard=kb.kb_consent()); return
        if cmd == "review_edit": await step_city(message, st); return
        if cmd == "cancel":
            if st.draft.get("booking_id"): await state.release_slot(uuid.UUID(st.draft["booking_id"]))
            await send_message(message, texts.CANCEL.format(name=st.name), keyboard=kb.kb_welcome()); st.draft = {}; st.step = "main"; return

        # 7. Оплата
        if cmd == "consent_yes": await step_payment(message, st); return
        if cmd == "pay_now":
            await send_message(message, "✅ Оплата получена")
            await asyncio.sleep(0.4)
            await step_confirm_payment(message, st); return

        await send_message(message, "Пожалуйста, выберите вариант на клавиатуре ниже 👇", keyboard=kb.kb_main())

    except Exception as e:
        logger.error(f"КРИТИЧЕСКАЯ ОШИБКА: {e}")
        await message.answer("Упс, что-то пошло не так. Нажмите /start для перезапуска.")

async def main():
    state.init_slots()
    asyncio.create_task(state.cleanup_loop(60))
    logger.info("Бот запускается...")
    await bot.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
