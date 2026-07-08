import importlib.util
from pathlib import Path
from unittest.mock import patch

WEBAPP_DIR = Path(__file__).resolve().parent.parent


def load_rules_module():
    # business-rules.py содержит дефис в имени, поэтому его нельзя
    # импортировать обычным `import`, — грузим так же, как это делает app.py.
    with patch("langchain_mistralai.ChatMistralAI"):
        spec = importlib.util.spec_from_file_location(
            "business_rules_under_test", WEBAPP_DIR / "business-rules.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


def test_build_products_text_formats_rows():
    rules = load_rules_module()
    rows = [
        {
            "product_name": "Bananas",
            "department_rus": "Овощи и фрукты",
            "aisle": "fresh fruits",
            "order_count": 5,
        },
    ]

    text = rules.build_products_text(rows)

    assert "1. Bananas" in text
    assert "Овощи и фрукты" in text
    assert "5" in text


def test_cache_key_differs_for_different_users():
    rules = load_rules_module()

    key_user_1 = rules._cache_key(1, "одинаковый текст товаров")
    key_user_2 = rules._cache_key(2, "одинаковый текст товаров")

    assert key_user_1 != key_user_2


def test_cache_key_is_stable_for_same_input():
    rules = load_rules_module()

    assert rules._cache_key(1, "текст") == rules._cache_key(1, "текст")


def test_service_key_differs_by_service():
    rules = load_rules_module()

    assert rules._service_key("rhythm", 1, "t") != rules._service_key("summary", 1, "t")


def test_build_forgotten_text_formats_rows():
    rules = load_rules_module()
    rows = [
        {
            "product_name": "Milk",
            "department_rus": "Молочные продукты",
            "aisle": "milk",
            "times_bought": 8,
            "orders_since_last": 3,
        },
    ]

    text = rules.build_forgotten_text(rows)

    assert "1. Milk" in text
    assert "8" in text
    assert "3 заказ" in text


def test_format_rhythm_maps_day_of_week():
    rules = load_rules_module()
    metrics = rules.format_rhythm(
        {"total_orders": 10, "avg_days_between": 12.37, "favorite_dow": 2, "favorite_hour": 9}
    )
    flat = {m["label"]: m["value"] for m in metrics}

    assert flat["Любимый день"] == "вторник"
    assert flat["Средний интервал"] == "12.4 дн."
    assert flat["Частый час"] == "9:00"


def test_format_summary_renders_reorder_percent():
    rules = load_rules_module()
    metrics = rules.format_summary(
        {
            "total_orders": 10,
            "unique_products": 50,
            "total_items": 120,
            "reorder_rate": 0.5,
            "top_department_rus": "Напитки",
        }
    )
    flat = {m["label"]: m["value"] for m in metrics}

    assert flat["Повторные покупки"] == "50%"
    assert flat["Любимый отдел"] == "Напитки"
