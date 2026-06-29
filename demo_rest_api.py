import os
import requests
import pandas as pd
from dotenv import load_dotenv
from langchain_mistralai import ChatMistralAI
from langchain_core.messages import SystemMessage, HumanMessage


# Загружаем переменные окружения из .env
load_dotenv()

LOGINOM_URL = "https://edu.loginom.dev/lgi/rest/instacart_ws_Abakarov1/GetUserHistory"
USER_ID = 1

payload = {
    "Variables": {
        "user_id": USER_ID
    }
}

response = requests.post(LOGINOM_URL, json=payload, timeout=30)
response.raise_for_status()
rows = response.json()["DataSet"]["Rows"]

# преобразуем ответ сервиса в датафрейм
df = pd.DataFrame(rows)
print(df.head(10))


lines = []
for i, row in enumerate(rows, start=1):
    lines.append(
        f"{i}. {row['product_name']} — "
        f"отдел: {row['department_rus']}, "
        f"категория: {row['aisle']}, "
        f"заказов: {row['order_count']}"
    )

products_text = "\n".join(lines)
print(products_text)


api_key = os.getenv("MISTRAL")
if not api_key:
    raise ValueError("Ключ MISTRAL_API_KEY не найден в .env")

llm = ChatMistralAI(
    api_key=api_key,
    model="mistral-large-latest",
    temperature=0.3,
    max_tokens=500
)


system_prompt = """Ты — персональный помощник покупателя в продуктовом онлайн-магазине.
Твоя задача — анализировать историю покупок клиента и давать ему понятные,
дружелюбные рекомендации прямо в его личном кабинете.
Обращайся к клиенту на "вы", тепло и по-человечески.
Пиши кратко — не более 5–6 предложений."""

user_prompt = f"""Вот список товаров, которые клиент покупает чаще всего:

{products_text}

Напишите клиенту короткий персональный анализ его покупок.
Начните с того, что вы заметили в его предпочтениях.
Дайте 1–2 дружеских совета — например, что стоит попробовать добавить
или на что обратить внимание. Пишите так, как будто клиент читает это
в своём личном кабинете."""


messages = [
    SystemMessage(content=system_prompt),
    HumanMessage(content=user_prompt)
]


result = llm.invoke(messages)
print(result.content)
