import hashlib
import json
import os
from pathlib import Path

import requests
from dotenv import load_dotenv
from langchain_mistralai import ChatMistralAI
from langchain_core.messages import SystemMessage, HumanMessage

load_dotenv()

# Все REST-сервисы лежат в одном пакете Loginom, различаясь только именем.
LOGINOM_BASE = "https://edu.loginom.dev/lgi/rest/instacart_ws_Abakarov1/"

# Файл этого модуля перезагружается заново на каждый запрос (см. load_business_rules
# в app.py), поэтому кэш должен жить на диске, а не в переменной процесса.
CACHE_PATH = Path(__file__).parent / "llm_cache.json"

# Инстакарт кодирует день недели числом 0..6. Точное соответствие в датасете не
# задокументировано; принято частое допущение 0 = воскресенье.
DOW_RU = ["воскресенье", "понедельник", "вторник", "среда", "четверг", "пятница", "суббота"]

api_key = os.getenv("MISTRAL")
if not api_key:
    raise ValueError("Ключ MISTRAL не найден в .env")

llm = ChatMistralAI(
    api_key=api_key,
    model="mistral-large-latest",
    temperature=0.3,
    max_tokens=500,
)


# ---------------------------------------------------------------------------
# Loginom REST
# ---------------------------------------------------------------------------
def _call_loginom(service: str, user_id: int):
    payload = {"Variables": {"user_id": user_id}}
    response = requests.post(LOGINOM_BASE + service, json=payload, timeout=30)
    response.raise_for_status()
    return response.json()["DataSet"]["Rows"]


def get_user_history(user_id: int):
    return _call_loginom("GetUserHistory", user_id)


def get_forgotten_products(user_id: int):
    return _call_loginom("GetForgottenProducts", user_id)


def get_purchase_rhythm(user_id: int):
    return _call_loginom("GetPurchaseRhythm", user_id)


def get_client_summary(user_id: int):
    return _call_loginom("GetClientSummary", user_id)


# ---------------------------------------------------------------------------
# Подготовка текста для LLM и форматирование метрик для интерфейса
# ---------------------------------------------------------------------------
def build_products_text(rows):
    lines = []
    for i, row in enumerate(rows, start=1):
        lines.append(
            f"{i}. {row['product_name']} — "
            f"отдел: {row['department_rus']}, "
            f"категория: {row['aisle']}, "
            f"заказов: {row['order_count']}"
        )
    return "\n".join(lines)


def build_forgotten_text(rows):
    lines = []
    for i, row in enumerate(rows, start=1):
        lines.append(
            f"{i}. {row['product_name']} — "
            f"отдел: {row['department_rus']}, "
            f"покупал всего раз: {row['times_bought']}, "
            f"последний раз {row['orders_since_last']} заказ(ов) назад"
        )
    return "\n".join(lines)


def format_rhythm(row):
    dow_value = row.get("favorite_dow")
    dow = DOW_RU[int(dow_value)] if dow_value not in (None, "") else "—"
    return [
        {"label": "Всего заказов", "value": row["total_orders"]},
        {"label": "Средний интервал", "value": f"{round(float(row['avg_days_between']), 1)} дн."},
        {"label": "Любимый день", "value": dow},
        {"label": "Частый час", "value": f"{row['favorite_hour']}:00"},
    ]


def format_summary(row):
    rate = row.get("reorder_rate")
    rate_str = f"{round(float(rate) * 100)}%" if rate not in (None, "") else "—"
    return [
        {"label": "Заказов", "value": row["total_orders"]},
        {"label": "Уникальных товаров", "value": row["unique_products"]},
        {"label": "Позиций куплено", "value": row["total_items"]},
        {"label": "Повторные покупки", "value": rate_str},
        {"label": "Любимый отдел", "value": row["top_department_rus"]},
    ]


def build_rhythm_text(row):
    return "; ".join(f"{m['label']}: {m['value']}" for m in format_rhythm(row))


def build_summary_text(row):
    return "; ".join(f"{m['label']}: {m['value']}" for m in format_summary(row))


# ---------------------------------------------------------------------------
# Кэш ответов LLM
# ---------------------------------------------------------------------------
def _load_cache() -> dict:
    if not CACHE_PATH.exists():
        return {}
    try:
        with open(CACHE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_cache(cache: dict) -> None:
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def _cache_key(user_id: int, products_text: str) -> str:
    raw = f"{user_id}:{products_text}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _service_key(service: str, user_id: int, text: str) -> str:
    raw = f"{service}:{user_id}:{text}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _cached_llm(cache_key: str, system_prompt: str, user_prompt: str):
    cache = _load_cache()

    cached = cache.get(cache_key)
    if cached is not None:
        return cached["prompt_text"], cached["recommendation"], True

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_prompt),
    ]
    result = llm.invoke(messages)

    cache[cache_key] = {"prompt_text": user_prompt, "recommendation": result.content}
    _save_cache(cache)

    return user_prompt, result.content, False


# ---------------------------------------------------------------------------
# Обращения к LLM по каждому сервису
# ---------------------------------------------------------------------------
def ask_mistral(user_id: int, products_text: str):
    system_prompt = """Ты — персональный помощник покупателя в продуктовом онлайн-магазине.
Твоя задача — анализировать историю покупок клиента и давать ему понятные,
дружелюбные рекомендации прямо в его личном кабинете.
Обращайся к клиенту на "вы", тепло и по-человечески.
Пиши кратко — не более 5–6 предложений."""

    user_prompt = f"""Вот список товаров, которые клиент (id={user_id}) покупает чаще всего:

{products_text}

Напишите клиенту короткий персональный анализ его покупок.
Начните с того, что вы заметили в его предпочтениях.
Дайте 1–2 дружеских совета — например, что стоит попробовать добавить
или на что обратить внимание. Пишите так, как будто клиент читает это
в своём личном кабинете."""

    return _cached_llm(_cache_key(user_id, products_text), system_prompt, user_prompt)


def ask_forgotten(user_id: int, forgotten_text: str):
    system_prompt = """Ты — заботливый помощник покупателя в продуктовом онлайн-магазине.
Клиент давно не заказывал некоторые товары, которые раньше брал регулярно.
Мягко и по-дружески напомни о них, без навязчивости.
Обращайся к клиенту на "вы". Пиши 3–4 предложения."""

    user_prompt = f"""Клиент (id={user_id}) давно не покупал эти привычные для него товары:

{forgotten_text}

Напишите короткое дружелюбное напоминание: возможно, клиент забыл добавить
что-то из этого в корзину. Не перечисляйте всё дословно списком, а мягко подскажите."""

    return _cached_llm(_service_key("forgotten", user_id, forgotten_text), system_prompt, user_prompt)


def ask_rhythm(user_id: int, rhythm_text: str):
    system_prompt = """Ты — дружелюбный аналитик покупательского поведения.
Объясняешь клиенту его ритм покупок простым человеческим языком.
Обращайся к клиенту на "вы". Пиши 3–4 предложения."""

    user_prompt = f"""Данные о ритме заказов клиента (id={user_id}):

{rhythm_text}

Объясните клиенту простыми словами, как он обычно делает покупки,
и подскажите, когда ему, вероятно, снова понадобится оформить заказ."""

    return _cached_llm(_service_key("rhythm", user_id, rhythm_text), system_prompt, user_prompt)


def ask_summary(user_id: int, summary_text: str):
    system_prompt = """Ты — помощник, который кратко и понятно комментирует
сводную статистику покупок клиента.
Обращайся к клиенту на "вы", дружелюбно. Пиши 3–4 предложения."""

    user_prompt = f"""Сводные показатели клиента (id={user_id}):

{summary_text}

Дайте короткий понятный комментарий: что эти цифры говорят о покупателе
и на что ему стоит обратить внимание."""

    return _cached_llm(_service_key("summary", user_id, summary_text), system_prompt, user_prompt)
