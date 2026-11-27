from datetime import date
from vkbottle import Keyboard, KeyboardButtonColor, Text, OpenLink
from programs import PROGRAMS

WD_RU = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]

def add_main_menu(kb: Keyboard) -> Keyboard:
    kb.row()
    kb.add(Text("📅 Свободные даты", payload={"cmd": "free_dates"}), color=KeyboardButtonColor.SECONDARY)
    kb.row()
    kb.add(Text("👤 Живой человек", payload={"cmd": "operator"}), color=KeyboardButtonColor.NEGATIVE)
    return kb

def kb_main() -> str:
    return add_main_menu(Keyboard(one_time=False, inline=False)).get_json()

def kb_welcome() -> str: return kb_main()

def kb_cities() -> str:
    kb = Keyboard(one_time=False, inline=False)
    kb.add(Text("Екатеринбург", payload={"cmd": "city_ekb"}), color=KeyboardButtonColor.PRIMARY)
    kb.row()
    kb.add(Text("Тюмень", payload={"cmd": "city_tmn"}), color=KeyboardButtonColor.PRIMARY)
    kb.row()
    kb.add(Text("Курган", payload={"cmd": "city_krg"}), color=KeyboardButtonColor.PRIMARY)
    return add_main_menu(kb).get_json()

def kb_audience() -> str:
    kb = Keyboard(one_time=False, inline=False)
    kb.add(Text("👶 Только детям", payload={"cmd": "aud_kids"}), color=KeyboardButtonColor.PRIMARY)
    kb.row()
    kb.add(Text("🥂 Только взрослым (18+)", payload={"cmd": "aud_adults"}), color=KeyboardButtonColor.PRIMARY)
    kb.row()
    kb.add(Text("🎉 Смешанная (дети+взрослые)", payload={"cmd": "aud_mixed"}), color=KeyboardButtonColor.SECONDARY)
    return add_main_menu(kb).get_json()

def kb_children_count() -> str:
    kb = Keyboard(one_time=False, inline=False)
    kb.add(Text("1 ребёнок", payload={"cmd": "children_1"}), color=KeyboardButtonColor.PRIMARY)
    kb.row()
    kb.add(Text("2 ребёнка", payload={"cmd": "children_2"}), color=KeyboardButtonColor.PRIMARY)
    kb.row()
    kb.add(Text("3 ребёнка", payload={"cmd": "children_3"}), color=KeyboardButtonColor.PRIMARY)
    kb.row()
    kb.add(Text("4 и больше", payload={"cmd": "children_4"}), color=KeyboardButtonColor.SECONDARY)
    return add_main_menu(kb).get_json()

def kb_package(audience: str) -> str:
    kb = Keyboard(one_time=False, inline=False)
    suitable = {k: v for k, v in PROGRAMS.items() if (v["for"] == "kids" and audience in ["kids", "mixed"]) or (v["for"] == "adults" and audience in ["adults", "mixed"])}
    for key, p in suitable.items():
        label = f"{p['title']} — {p['price']} ₽"
        kb.add(Text(label, payload={"cmd": f"pkg_{key}"}), color=KeyboardButtonColor.SECONDARY)
        kb.row()
    return add_main_menu(kb).get_json()

def kb_extras(draft: dict) -> str:
    kb = Keyboard(one_time=False, inline=False)
    chosen = set(draft.get("extras", []))
    mk = lambda k, l: f"{'✅ ' if k in chosen else ''}{l}"
    kb.add(Text(mk("photo", "📸 Фотограф 3 500"), payload={"cmd": "extra_photo"}), color=KeyboardButtonColor.SECONDARY)
    kb.row()
    kb.add(Text(mk("bubbles", "🫧 Пузыри 2 000"), payload={"cmd": "extra_bubbles"}), color=KeyboardButtonColor.SECONDARY)
    kb.row()
    kb.add(Text(mk("snow", "❄️ Снежное шоу 2 500"), payload={"cmd": "extra_snow"}), color=KeyboardButtonColor.SECONDARY)
    kb.row()
    kb.add(Text(mk("gifts", "🎁 Подарки 500/шт"), payload={"cmd": "extra_gifts"}), color=KeyboardButtonColor.SECONDARY)
    kb.row()
    kb.add(Text("✅ Готово, выбрать дату", payload={"cmd": "extras_done"}), color=KeyboardButtonColor.POSITIVE)
    return add_main_menu(kb).get_json()

def kb_dates(dates_summary: list[dict]) -> str:
    kb = Keyboard(one_time=False, inline=False)
    col, count = 0, 0
    for item in dates_summary:
        if count >= 9: break
        d: date = item["date"]
        free = item["free"]
        if free == 0:
            kb.add(Text(f"{d.day} {WD_RU[d.weekday()]} · занято", payload={"cmd": "noop"}), color=KeyboardButtonColor.NEGATIVE)
        else:
            kb.add(Text(f"{d.day} {WD_RU[d.weekday()]} · {free} окон", payload={"cmd": f"date_{d.isoformat()}"}), color=KeyboardButtonColor.SECONDARY)
        col += 1; count += 1
        if col == 3:
            kb.row(); col = 0
    if col: kb.row()
    return add_main_menu(kb).get_json()

def kb_times(slots: list) -> str:
    kb = Keyboard(one_time=False, inline=False)
    col = 0
    for slot in slots:
        t = slot.time.strftime("%H:%M")
        if slot.status.value == "free":
            kb.add(Text(t, payload={"cmd": f"slot_{slot.id}"}), color=KeyboardButtonColor.PRIMARY)
        else:
            kb.add(Text(f"{t} — занято", payload={"cmd": "noop"}), color=KeyboardButtonColor.NEGATIVE)
        col += 1
        if col == 3:
            kb.row(); col = 0
    if col: kb.row()
    return add_main_menu(kb).get_json()

def kb_review() -> str:
    kb = Keyboard(one_time=False, inline=False)
    kb.add(Text("✅ Всё верно", payload={"cmd": "review_ok"}), color=KeyboardButtonColor.POSITIVE)
    kb.row()
    kb.add(Text("✏️ Изменить", payload={"cmd": "review_edit"}), color=KeyboardButtonColor.SECONDARY)
    kb.row()
    kb.add(Text("✖ Отменить", payload={"cmd": "cancel"}), color=KeyboardButtonColor.NEGATIVE)
    return add_main_menu(kb).get_json()

def kb_consent() -> str:
    kb = Keyboard(one_time=False, inline=False)
    kb.add(Text("✅ Согласен и оплатить", payload={"cmd": "consent_yes"}), color=KeyboardButtonColor.POSITIVE)
    return add_main_menu(kb).get_json()

def kb_payment() -> str:
    kb = Keyboard(one_time=False, inline=False)
    kb.add(Text("💳 Оплатить 500 ₽", payload={"cmd": "pay_now"}), color=KeyboardButtonColor.POSITIVE)
    kb.row()
    kb.add(Text("✖ Отменить", payload={"cmd": "cancel"}), color=KeyboardButtonColor.NEGATIVE)
    return add_main_menu(kb).get_json()

def kb_after_paid(share_url: str) -> str:
    kb = Keyboard(one_time=False, inline=False)
    kb.add(OpenLink(share_url, "📤 Поделиться с родными"), color=KeyboardButtonColor.POSITIVE)
    return add_main_menu(kb).get_json()

def kb_free_dates(dates_summary: list[dict]) -> str:
    kb = Keyboard(one_time=False, inline=False)
    col, count = 0, 0
    for item in dates_summary:
        if item["free"] > 0:
            if count >= 9: break
            d: date = item["date"]
            kb.add(Text(f"{d.day} {WD_RU[d.weekday()]} · {item['free']} окон", payload={"cmd": f"date_{d.isoformat()}"}), color=KeyboardButtonColor.SECONDARY)
            col += 1; count += 1
            if col == 3:
                kb.row(); col = 0
    if col: kb.row()
    return add_main_menu(kb).get_json()
