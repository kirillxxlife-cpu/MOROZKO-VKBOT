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

async def step_children_count(message: Message, st: state.UserState):
    st.step = "children_count"
    st.draft["children"] = []
    st.draft["current_child_idx"] = 0
    await send_thinking(message, texts.ASK_CHILDREN_COUNT, keyboard=kb.kb_children_count())

async def ask_child_info(message: Message, st: state.UserState):
    idx = st.draft.get("current_child_idx", 0)
    child_num = ["первого", "второго", "третьего", "четвёртого"][idx] if idx < 4 else f"{idx+1}-го"
    st.step = "child_name"
    await send_thinking(message, texts.ASK_CHILD_INFO.format(child_num=child_num), keyboard=kb.kb_main())

# ИСПРАВЛЕННАЯ ЛОГИКА: формируем подробный текст и прикрепляем кнопки
async def step_package(message: Message, st: state.UserState):
    st.step = "package"
    audience = st.draft.get("audience", "mixed")
    
    # Собираем программы под аудиторию
    suitable = {k: v for k, v in PROGRAMS.items() if (v["for"] == "kids" and audience in ["kids", "mixed"]) or (v["for"] == "adults" and audience in ["adults", "mixed"])}
    
    # Формируем подробный список
    program_list = ""
    for key, p in suitable.items():
        program_list += f"🎁 {p['title']} — {p['price']} ₽\n"
        program_list += f"⏱ {p['duration']} · {p['desc']}\n"
        program_list += f"👥 {p['details']}\n\n"
    
    text = texts.ASK_PACKAGE_DETAILS.format(program_list=program_list.strip())
    await send_thinking(message, text, keyboard=kb.kb_package(audience))

async def step_extras(message: Message, st: state.UserState):
    st.step = "extras"
    await send_thinking(message, texts.ASK_EXTRAS, keyboard=kb.kb_extras(st.draft))

async def step_dates(message: Message, st: state.UserState):
    st.step = "date"
    summary = state.get_dates_summary()
    await send_thinking(message, texts.ASK_DATE, keyboard=kb.kb_dates(summary))

async def step_times(message: Message, st: state.UserState, d: date):
    st.draft["date"] = d.isoformat()
    st.draft["date_display"] = d.strftime("%d.%m.%Y")
    st.step = "time"
    slots = state.get_free_slots_by_date(d)
    if not any(s.status.value == "free" for s in slots):
        await send_thinking(message, texts.NO_SLOTS_LEFT, keyboard=kb.kb_dates(state.get_dates_summary()))
        return
    await send_thinking(message, texts.ASK_TIME.format(date=d.strftime("%d.%m.%Y")), keyboard=kb.kb_times(slots))

async def step_address(message: Message, st: state.UserState):
    st.step = "address"
    await send_thinking(message, texts.ASK_ADDRESS, keyboard=kb.kb_main())

async def step_phone(message: Message, st: state.UserState):
    st.step = "phone"
    await send_thinking(message, texts.ASK_PHONE, keyboard=kb.kb_main())

async def step_review(message: Message, st: state.UserState):
    st.step = "review"
    header = texts.REVIEW_HEADER.format(name=st.name)
    full_text = header + "\n" + build_review_text(st) + "\n" + texts.REVIEW_GUARANTEE
    await send_thinking(message, full_text, keyboard=kb.kb_review())

async def step_payment(message: Message, st: state.UserState):
    booking = state.create_booking(message.from_id, st.draft)
    slot = await state.hold_slot(booking.slot_id, booking.id, HOLD_MIN)
    if not slot:
        await send_thinking(message, texts.SLOT_TAKEN, keyboard=kb.kb_main())
        st.step = "main"
        return
    st.draft["booking_id"] = str(booking.id)
    st.step = "payment"
    await send_thinking(message, texts.PAYMENT_SCREEN, keyboard=kb.kb_payment())

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
    
    await send_thinking(message, paid_header + "\n\n" + paid_body, keyboard=kb_with_pdf.get_json())
    st.step = "done"

async def enter_operator(message: Message, st: state.UserState):
    st.operator_mode = True
    await send_thinking(message, texts.OPERATOR_REQUESTED, keyboard=kb.kb_main())
    await notify_admin(texts.ADMIN_NEW_CLIENT.format(name=st.name or f"user_{st.vk_id}", vk_id=st.vk_id, snippet="Нажал «Живой человек»", funnel_stage=st.step))

@bot.on.message()
async def router(message: Message):
    try:
        vk_id = message.from_id
        st = state.get_user(vk_id)
        if not st.name:
            st.name = await safe_name(message)
        st.last_activity = datetime.now()

        text_raw = (message.text or "").strip()
        cmd = parse_payload(message)

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

        if not cmd and text_raw:
            if st.step == "city":
                st.draft["city"] = text_raw
                await step_audience(message, st); return
            if st.step == "child_name":
                st.draft["children"].append(text_raw)
                st.draft["current_child_idx"] += 1
                if st.draft["current_child_idx"] < st.draft.get("target_children_count", 1):
                    await ask_child_info(message, st)
                else:
                    await step_package(message, st)
                return
            if st.step == "address":
                st.draft["address"] = text_raw
                await step_phone(message, st); return
            if st.step == "phone":
                digits = re.sub(r"\D", "", text_raw)
                if len(digits) < 10:
                    await send_thinking(message, texts.BAD_PHONE, keyboard=kb.kb_main()); return
                st.draft["phone"] = text_raw
                await step_review(message, st); return

        if text_raw.lower().startswith("/start"):
            await step_welcome(message, st); return
        if cmd == "book": 
            await step_welcome(message, st); return 
        if cmd == "free_dates":
            st.step = "free_dates"
            summary = state.get_dates_summary()
            await send_thinking(message, texts.FREE_DATES_HEADER, keyboard=kb.kb_free_dates(summary)); return
        if cmd == "operator":
            await enter_operator(message, st); return
        if cmd == "back_main":
            await step_welcome(message, st); return

        if cmd in ("aud_kids", "aud_adults", "aud_mixed"):
            st.draft["audience"] = cmd
            if cmd == "aud_adults":
                st.draft["target_children_count"] = 0
                await step_package(message, st)
            else:
                await step_children_count(message, st)
            return

        if cmd.startswith("children_"):
            count = 4 if cmd.split("_")[1] == "4" else int(cmd.split("_")[1])
            st.draft["target_children_count"] = count
            st.draft["current_child_idx"] = 0
            await ask_child_info(message, st); return
        if cmd.startswith("pkg_"):
            st.draft["package"] = cmd.replace("pkg_", "")
            st.draft["extras"] = []
            await step_extras(message, st); return
        if cmd in ("extra_photo", "extra_bubbles", "extra_snow", "extra_gifts"):
            key = cmd.split("_", 1)[1]; chosen = set(st.draft.get("extras", []))
            chosen.symmetric_difference_update({key}); st.draft["extras"] = list(chosen)
            await send_thinking(message, "Отмечено.", keyboard=kb.kb_extras(st.draft)); return
        if cmd == "extras_done": await step_dates(message, st); return
        if cmd.startswith("date_"):
            await step_times(message, st, date.fromisoformat(cmd[5:])); return
        if cmd.startswith("slot_"):
            slot_id = int(cmd[5:]); slots = state.get_free_slots_by_date(date.fromisoformat(st.draft["date"]))
            slot = next((s for s in slots if s.id == slot_id), None)
            if not slot or slot.status.value != "free":
                await send_thinking(message, texts.SLOT_TAKEN, keyboard=kb.kb_times(slots)); return
            st.draft["slot_id"] = slot_id; st.draft["time_display"] = slot.time.strftime("%H:%M")
            await step_address(message, st); return

        if cmd == "review_ok":
            st.step = "consent"; await send_thinking(message, texts.CONSENT, keyboard=kb.kb_consent()); return
        if cmd == "review_edit": await step_welcome(message, st); return
        if cmd == "review_back": await step_review(message, st); return
        if cmd == "consent_yes": await step_payment(message, st); return
        if cmd == "pay_now":
            await send_thinking(message, "✅ Оплата получена")
            await asyncio.sleep(0.4)
            await step_confirm_payment(message, st); return
        if cmd == "cancel":
            if st.draft.get("booking_id"): await state.release_slot(uuid.UUID(st.draft["booking_id"]))
            await send_thinking(message, texts.CANCEL.format(name=st.name), keyboard=kb.kb_welcome()); st.draft = {}; st.step = "main"; return
        if cmd == "noop": await send_thinking(message, texts.NOOP, keyboard=kb.kb_main()); return

        if not cmd and text_raw:
            ai_response = await ai.get_ai_response(text_raw, st.ai_history, st.name, st.step)

            if "[ПЕРЕДАТЬ_ОПЕРАТОРУ]" in ai_response:
                clean_response = ai_response.replace("[ПЕРЕДАТЬ_ОПЕРАТОРУ]", "").strip()
                await send_thinking(message, clean_response, keyboard=kb.kb_main())
                await notify_admin(f"🚨 Требуется оператор!\n👤 {st.name} (vk.com/id{st.vk_id})\n💬 {text_raw[:200]}...")
                st.operator_mode = True; return

            st.ai_history.extend([{"role": "user", "text": text_raw}, {"role": "assistant", "text": ai_response}])
            st.ai_history = st.ai_history[-10:]
            await send_thinking(message, ai_response, keyboard=kb.kb_main()); return

        await send_thinking(message, "Пожалуйста, выберите вариант на клавиатуре ниже 👇", keyboard=kb.kb_main())

    except Exception as e:
        logger.error(f"КРИТИЧЕСКАЯ ОШИБКА: {e}")
        await message.answer("Упс, что-то пошло не так. Нажмите /start для перезапуска.")

async def main():
    state.init_slots()
    if sheets.is_enabled():
        rows = await sheets.load_paid()
        restored = state.mark_booked_from_sheets(rows)
        logger.info(f"Восстановлено {restored} слотов")

    asyncio.create_task(state.cleanup_loop(60))
    logger.info("Бот запускается...")
    await bot.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
