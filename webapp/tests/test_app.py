from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import app as app_module

CACHE_PATH = Path(__file__).resolve().parent.parent / "llm_cache.json"

SAMPLE_ROWS = [
    {
        "product_name": "Bananas",
        "aisle": "fresh fruits",
        "department": "produce",
        "department_rus": "Овощи и фрукты",
        "order_count": 12,
    },
    {
        "product_name": "Milk",
        "aisle": "milk",
        "department": "dairy",
        "department_rus": "Молочные продукты",
        "order_count": 7,
    },
]


@pytest.fixture(autouse=True)
def clean_cache_file():
    if CACHE_PATH.exists():
        CACHE_PATH.unlink()
    yield
    if CACHE_PATH.exists():
        CACHE_PATH.unlink()


@pytest.fixture
def client():
    app_module.app.config.update(TESTING=True)
    with app_module.app.test_client() as test_client:
        yield test_client


def fake_loginom_response(rows):
    response = MagicMock()
    response.raise_for_status.return_value = None
    response.json.return_value = {"DataSet": {"Rows": rows}}
    return response


def test_index_page_loads(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Instacart".encode("utf-8") in resp.data


def test_login_rejects_non_numeric_user_id(client):
    resp = client.post("/login", data={"user_id": "abc"})
    assert "целым числом".encode("utf-8") in resp.data


@patch("requests.post")
def test_login_rejects_unknown_user(mock_post, client):
    mock_post.return_value = fake_loginom_response([])

    resp = client.post("/login", data={"user_id": "999999"})

    assert "не найден".encode("utf-8") in resp.data


@patch("requests.post")
def test_login_accepts_known_user(mock_post, client):
    mock_post.return_value = fake_loginom_response(SAMPLE_ROWS)

    resp = client.post("/login", data={"user_id": "1"})

    assert "Текущий клиент".encode("utf-8") in resp.data


def test_history_requires_login(client):
    resp = client.post("/history")
    assert "Сначала авторизуйтесь".encode("utf-8") in resp.data


@patch("langchain_mistralai.ChatMistralAI")
@patch("requests.post")
def test_history_second_identical_request_uses_cache(mock_post, mock_llm_cls, client):
    mock_post.return_value = fake_loginom_response(SAMPLE_ROWS)
    mock_llm_instance = mock_llm_cls.return_value
    mock_llm_instance.invoke.return_value = MagicMock(content="Тестовая рекомендация")

    with client.session_transaction() as sess:
        sess["user_id"] = 1

    first = client.post("/history")
    assert "Тестовая рекомендация".encode("utf-8") in first.data
    assert "новый запрос".encode("utf-8") in first.data
    assert mock_llm_instance.invoke.call_count == 1

    second = client.post("/history")
    assert "Тестовая рекомендация".encode("utf-8") in second.data
    assert "из кэша".encode("utf-8") in second.data
    # Повторный запрос с теми же параметрами не должен идти в LLM заново.
    assert mock_llm_instance.invoke.call_count == 1


@patch("langchain_mistralai.ChatMistralAI")
@patch("requests.post")
def test_history_different_users_not_mixed_up_by_cache(mock_post, mock_llm_cls, client):
    mock_llm_instance = mock_llm_cls.return_value
    mock_llm_instance.invoke.return_value = MagicMock(content="Рекомендация")

    mock_post.return_value = fake_loginom_response(SAMPLE_ROWS)
    with client.session_transaction() as sess:
        sess["user_id"] = 1
    client.post("/history")

    mock_post.return_value = fake_loginom_response(SAMPLE_ROWS[:1])
    with client.session_transaction() as sess:
        sess["user_id"] = 2
    client.post("/history")

    assert mock_llm_instance.invoke.call_count == 2


@patch("requests.post")
def test_history_handles_loginom_failure(mock_post, client):
    mock_post.side_effect = Exception("Loginom недоступен")

    with client.session_transaction() as sess:
        sess["user_id"] = 1

    resp = client.post("/history")

    assert "Ошибка".encode("utf-8") in resp.data


FORGOTTEN_ROWS = [
    {
        "product_name": "Bananas",
        "department_rus": "Овощи и фрукты",
        "aisle": "fresh fruits",
        "times_bought": 9,
        "orders_since_last": 4,
    },
]

RHYTHM_ROW = {
    "total_orders": 15,
    "avg_days_between": 12.4,
    "favorite_dow": 1,
    "favorite_hour": 14,
}

SUMMARY_ROW = {
    "total_orders": 15,
    "unique_products": 80,
    "total_items": 210,
    "reorder_rate": 0.62,
    "top_department_rus": "Молочные продукты",
}


def _login_service_test(client, mock_llm_cls, content="Готовый текст"):
    mock_llm_cls.return_value.invoke.return_value = MagicMock(content=content)
    with client.session_transaction() as sess:
        sess["user_id"] = 1


@patch("langchain_mistralai.ChatMistralAI")
@patch("requests.post")
def test_forgotten_service_renders_table_and_llm(mock_post, mock_llm_cls, client):
    mock_post.return_value = fake_loginom_response(FORGOTTEN_ROWS)
    _login_service_test(client, mock_llm_cls, content="Не забудьте бананы")

    resp = client.post("/service/forgotten")

    assert resp.status_code == 200
    assert "Забытые товары".encode("utf-8") in resp.data
    assert "Bananas".encode("utf-8") in resp.data
    assert "Не забудьте бананы".encode("utf-8") in resp.data


@patch("langchain_mistralai.ChatMistralAI")
@patch("requests.post")
def test_rhythm_service_renders_metrics(mock_post, mock_llm_cls, client):
    mock_post.return_value = fake_loginom_response([RHYTHM_ROW])
    _login_service_test(client, mock_llm_cls, content="Вы заказываете раз в две недели")

    resp = client.post("/service/rhythm")

    assert resp.status_code == 200
    assert "Ритм покупок".encode("utf-8") in resp.data
    assert "понедельник".encode("utf-8") in resp.data  # favorite_dow=1
    assert "Вы заказываете раз в две недели".encode("utf-8") in resp.data


@patch("langchain_mistralai.ChatMistralAI")
@patch("requests.post")
def test_summary_service_renders_metrics(mock_post, mock_llm_cls, client):
    mock_post.return_value = fake_loginom_response([SUMMARY_ROW])
    _login_service_test(client, mock_llm_cls, content="Стабильный покупатель")

    resp = client.post("/service/summary")

    assert resp.status_code == 200
    assert "Сводка по клиенту".encode("utf-8") in resp.data
    assert "62%".encode("utf-8") in resp.data  # reorder_rate 0.62
    assert "Стабильный покупатель".encode("utf-8") in resp.data


@patch("langchain_mistralai.ChatMistralAI")
@patch("requests.post")
def test_forgotten_empty_shows_note_without_calling_llm(mock_post, mock_llm_cls, client):
    mock_post.return_value = fake_loginom_response([])
    _login_service_test(client, mock_llm_cls)

    resp = client.post("/service/forgotten")

    assert resp.status_code == 200
    assert "забытых нет".encode("utf-8") in resp.data
    assert mock_llm_cls.return_value.invoke.call_count == 0


def test_service_requires_login(client):
    resp = client.post("/service/rhythm")
    assert "Сначала авторизуйтесь".encode("utf-8") in resp.data


def test_unknown_service_returns_404(client):
    with client.session_transaction() as sess:
        sess["user_id"] = 1
    resp = client.post("/service/does-not-exist")
    assert resp.status_code == 404


@patch("langchain_mistralai.ChatMistralAI")
@patch("requests.post")
def test_departments_service_aggregates_and_charts(mock_post, mock_llm_cls, client):
    mock_post.return_value = fake_loginom_response(SAMPLE_ROWS)
    _login_service_test(client, mock_llm_cls, content="Вы любите молочное")

    resp = client.post("/service/departments")

    assert resp.status_code == 200
    assert "Отделы и категории".encode("utf-8") in resp.data
    # доля отделов складывается в 100% (12 и 7 из SAMPLE_ROWS)
    assert "Овощи и фрукты".encode("utf-8") in resp.data
    assert "svcChart".encode("utf-8") in resp.data  # блок Chart.js отрисован
    assert "Вы любите молочное".encode("utf-8") in resp.data


def test_insights_page_lists_services(client):
    with client.session_transaction() as sess:
        sess["user_id"] = 1
    resp = client.get("/insights")
    assert resp.status_code == 200
    assert "Забытые товары".encode("utf-8") in resp.data
    assert "Отделы и категории".encode("utf-8") in resp.data


def test_home_page_shows_banner_area(client):
    resp = client.get("/")
    assert resp.status_code == 200
    # либо вставленный баннер, либо слот-заглушка — в обоих случаях класс "banner"
    assert b"banner" in resp.data


@patch("langchain_mistralai.ChatMistralAI")
@patch("requests.post")
def test_service_second_identical_request_uses_cache(mock_post, mock_llm_cls, client):
    mock_post.return_value = fake_loginom_response([RHYTHM_ROW])
    _login_service_test(client, mock_llm_cls, content="Текст про ритм")

    first = client.post("/service/rhythm")
    assert "новый запрос".encode("utf-8") in first.data

    second = client.post("/service/rhythm")
    assert "из кэша".encode("utf-8") in second.data
    assert mock_llm_cls.return_value.invoke.call_count == 1
