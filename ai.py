import os
import aiohttp
from loguru import logger
from programs import PROGRAMS

YANDEX_FOLDER_ID = os.getenv("YANDEX_FOLDER_ID")
YANDEX_API_KEY = os.getenv("YANDEX_API_KEY")

def build_knowledge_base():
    text = "### БАЗА ЗНАНИЙ (ТОЛЬКО ЭТИ ПРОГРАММЫ):\n"
    for key, p in PROGRAMS.items():
        text += f"- {p['title']} ({p['duration']}): {p['price']} ₽. {p['desc']}\n"
    return text

BASE_SYSTEM_PROMPT = (
    "Ты — виртуальный помощник 'Морозко', эксперт по организации новогодних праздников (2027 год). "
    "Твоя задача — консультировать и вести пользователя к заполнению анкеты через кнопки.\n\n"
    "### ТОН ОБЩЕНИЯ:\n- Обращайся по имени.\n- Отвечай кратко (1-3 предложения).\n"
    "- Используй эмпатию (сначала пойми, потом отвечай).\n\n"
    f"{build_knowledge_base()}\n"
    "### ТВОЯ РОЛЬ:\nТы видишь, на каком шаге находится клиент. Если он задает вопрос, ответь на него и напомни, "
    "что для продолжения нужно нажать на кнопку на клавиатуре ниже.\n\n"
    "### КОГДА ПЕРЕДАВАТЬ ОПЕРАТОРУ:\n"
    "Если клиент сильно недоволен, просит скидку >25% или сложный корпоратив. "
    "Напиши 'Передаю старшему администратору!' и добавь метку [ПЕРЕДАТЬ_ОПЕРАТОРУ]\n\n"
    "### ПРАВИЛО ДЕРЗКИХ СООБЩЕНИЙ:\n"
    "Если пишут 'И что', 'Цены давай', отвечай так же коротко и сразу к сути."
)

async def get_ai_response(user_message: str, chat_history: list, client_name: str, current_step: str) -> str:
    step_hints = {
        "city": "Клиент на шаге ввода ГОРОДА.",
        "audience": "Клиент выбирает, ДЛЯ КОГО праздник (дети/взрослые).",
        "children_count": "Клиент на шаге выбора КОЛИЧЕСТВА ДЕТЕЙ.",
        "child_name": "Клиент на шаге ввода ИМЕНИ И ВОЗРАСТА ребенка.",
        "package": "Клиент на шаге выбора ПРОГРАММЫ.",
        "extras": "Клиент на шаге выбора ДОПОВ.",
        "date": "Клиент на шаге выбора ДАТЫ.",
        "address": "Клиент на шаге ввода АДРЕСА.",
        "phone": "Клиент на шаге ввода ТЕЛЕФОНА.",
        "payment": "Клиент на шаге ОПЛАТЫ."
    }
    
    step_context = f"\n\n[СИСТЕМНАЯ ИНФОРМАЦИЯ]: {step_hints.get(current_step, 'Клиент в главном меню.')}"
    system_prompt = BASE_SYSTEM_PROMPT + f"\n\nИмя клиента: {client_name}.{step_context}"
    
    messages = [{"role": "system", "content": system_prompt}]
    for msg in chat_history:
        messages.append({"role": msg["role"], "content": msg.get("text") or msg.get("content")})
    messages.append({"role": "user", "content": user_message})

    url = "https://llm.api.cloud.yandex.net/v1/chat/completions"
    headers = {"Authorization": f"Api-Key {YANDEX_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": f"gpt://{YANDEX_FOLDER_ID}/aliceai-llm-flash/latest",
        "messages": messages,
        "temperature": 0.3,
        "max_tokens": 1000
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload, timeout=40) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data["choices"][0]["message"]["content"].strip()
                return "Извините, произошла техническая ошибка. Попробуйте позже."
    except Exception as e:
        logger.error(f"Network error: {e}")
        return "Извините, произошла техническая ошибка. Попробуйте позже."
