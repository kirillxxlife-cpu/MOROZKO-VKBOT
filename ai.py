import os
import aiohttp
from loguru import logger

YANDEX_FOLDER_ID = os.getenv("YANDEX_FOLDER_ID")
YANDEX_API_KEY = os.getenv("YANDEX_API_KEY")

BASE_SYSTEM_PROMPT = (
    "Ты — Морозко, вежливый и заботливый помощник сообщества «Сказка к вам домой». "
    "Твоя задача — помогать клиентам с выбором праздничной программы, отвечать на вопросы "
    "о Деде Морозе и Снегурочке, условиях бронирования, ценах и сроках. "
    "Общайся тепло, на «вы», без канцелярита. Если не знаешь точного ответа — "
    "не выдумывай, а предложи связаться с менеджером, добавив метку [ПЕРЕДАТЬ_ОПЕРАТОРУ]. "
    "Если клиент пишет длинно и эмоционально, сначала кратко перефразируй его мысль (рефлексивное слушание), "
    "а затем дай ответ. Всегда обращайся к клиенту по имени."
)

async def get_ai_response(user_message: str, chat_history: list, client_name: str) -> str:
    system_prompt = BASE_SYSTEM_PROMPT + f"\nИмя клиента: {client_name}. Всегда обращайся к нему/ней по имени."
    
    messages = [{"role": "system", "content": system_prompt}]
    for msg in chat_history:
        messages.append({"role": msg["role"], "content": msg.get("text") or msg.get("content")})
    messages.append({"role": "user", "content": user_message})

    url = "https://llm.api.cloud.yandex.net/v1/chat/completions"
    headers = {"Authorization": f"Api-Key {YANDEX_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": f"gpt://{YANDEX_FOLDER_ID}/alice-llm-flash",
        "messages": messages,
        "temperature": 0.3,
        "max_tokens": 1500
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload, timeout=40) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data["choices"][0]["message"]["content"].strip()
                else:
                    error_text = await resp.text()
                    logger.error(f"Yandex API Error {resp.status}: {error_text}")
                    return "Извините, произошла техническая ошибка. Попробуйте позже."
    except Exception as e:
        logger.error(f"Network error: {e}")
        return "Извините, произошла техническая ошибка. Попробуйте позже."
