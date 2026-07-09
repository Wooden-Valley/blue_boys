import os
import time
import importlib.util
from pathlib import Path

from flask import Flask, request, session, jsonify, render_template, abort

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "instacart-demo-secret-key")
BASE_DIR = Path(__file__).parent


# Описание всех аналитических сервисов. Каждый ссылается на функции из
# business-rules.py по имени (модуль грузится динамически на каждый запрос).
SERVICES = {
    "history": {
        "title": "Топ-10 товаров клиента",
        "subtitle": "Товары, которые клиент заказывает чаще всего.",
        "get": "get_user_history",
        "build_text": "build_products_text",
        "ask": "ask_mistral",
        "view": "table",
        "page": "history",
        "columns": [
            {"label": "Товар", "key": "product_name"},
            {"label": "Категория", "key": "aisle"},
            {"label": "Отдел", "key": "department_rus"},
            {"label": "Покупок", "key": "order_count"},
        ],
        "bar": {"label": "product_name", "value": "order_count"},
        "chart": {"labels": "product_name", "values": "order_count", "kind": "bar", "title": "Частота покупок"},
        "empty_msg": "Loginom вернул пустой список товаров",
    },
    "forgotten": {
        "title": "Забытые товары",
        "subtitle": "Привычные товары, которых не было в последних заказах.",
        "get": "get_forgotten_products",
        "build_text": "build_forgotten_text",
        "ask": "ask_forgotten",
        "view": "table",
        "page": "insights",
        "columns": [
            {"label": "Товар", "key": "product_name"},
            {"label": "Отдел", "key": "department_rus"},
            {"label": "Категория", "key": "aisle"},
            {"label": "Покупок всего", "key": "times_bought"},
            {"label": "Заказов назад", "key": "orders_since_last"},
        ],
        "bar": {"label": "product_name", "value": "times_bought"},
        "empty_msg": "Похоже, клиент недавно покупал все привычные товары — забытых нет.",
    },
    "rhythm": {
        "title": "Ритм покупок",
        "subtitle": "Как часто и когда клиент оформляет заказы.",
        "get": "get_purchase_rhythm",
        "build_text": "build_rhythm_text",
        "ask": "ask_rhythm",
        "view": "metrics",
        "page": "insights",
        "format": "format_rhythm",
        "empty_msg": "Недостаточно данных о заказах клиента.",
    },
    "summary": {
        "title": "Сводка по клиенту",
        "subtitle": "Ключевые метрики покупательского поведения.",
        "get": "get_client_summary",
        "build_text": "build_summary_text",
        "ask": "ask_summary",
        "view": "metrics",
        "page": "insights",
        "format": "format_summary",
        "empty_msg": "Недостаточно данных для сводки.",
    },
    "departments": {
        "title": "Отделы и категории",
        "subtitle": "Из каких отделов состоят покупки клиента.",
        "get": "get_department_stats",
        "build_text": "build_departments_text",
        "ask": "ask_departments",
        "view": "table",
        "page": "insights",
        "columns": [
            {"label": "Отдел", "key": "department_rus"},
            {"label": "Покупок", "key": "order_count"},
            {"label": "Доля, %", "key": "share"},
        ],
        "bar": {"label": "department_rus", "value": "order_count"},
        "chart": {"labels": "department_rus", "values": "order_count", "kind": "doughnut", "title": "Доля отделов"},
        "empty_msg": "Недостаточно данных по отделам.",
    },
}

# Разделы (страницы) приложения и относящиеся к ним сервисы.
PAGES = {
    "home": {"title": "Личный кабинет", "services": []},
    "history": {"title": "Мои покупки", "services": ["history"]},
    "insights": {"title": "Аналитика", "services": ["forgotten", "rhythm", "summary", "departments"]},
}
NAV = [
    {"page": "home", "url": "/", "title": "Кабинет"},
    {"page": "history", "url": "/history", "title": "Мои покупки"},
    {"page": "insights", "url": "/insights", "title": "Аналитика"},
]


def load_business_rules():
    py_path = BASE_DIR / "business-rules.py"
    if not py_path.exists():
        raise FileNotFoundError("Не найден business-rules.py.")

    spec = importlib.util.spec_from_file_location("business-rules", py_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _page_services(page):
    return [{"key": k, "title": SERVICES[k]["title"], "subtitle": SERVICES[k]["subtitle"]}
            for k in PAGES.get(page, {}).get("services", [])]


def _find_banner():
    for ext in ("png", "jpg", "jpeg", "webp"):
        if (BASE_DIR / "static" / f"banner.{ext}").exists():
            return f"banner.{ext}"
    return None


def render_index(page="home", **overrides):
    banner_file = _find_banner()
    context = {
        "user_id": session.get("user_id"),
        "nav": NAV,
        "page": page,
        "page_title": PAGES.get(page, {}).get("title", ""),
        "services": _page_services(page),
        "banner_file": banner_file,
        "has_banner": banner_file is not None,
        "active_service": None,
        "service_title": None,
        "result_view": None,
        "columns": None,
        "rows": None,
        "bars": None,
        "metrics": None,
        "chart": None,
        "result_note": None,
        "prompt_text": None,
        "recommendation": None,
        "from_cache": False,
        "response_time_ms": None,
        "error": None,
    }
    context.update(overrides)
    return render_template("index.html", **context)


def _build_bars(rows, bar_cfg):
    values = [row[bar_cfg["value"]] for row in rows]
    max_value = max(values, default=0)
    if not max_value:
        return None
    return [
        {
            "label": row[bar_cfg["label"]],
            "value": row[bar_cfg["value"]],
            "pct": round(row[bar_cfg["value"]] / max_value * 100, 1),
        }
        for row in rows
    ]


def _build_chart(rows, chart_cfg):
    return {
        "kind": chart_cfg["kind"],
        "title": chart_cfg["title"],
        "labels": [str(row[chart_cfg["labels"]]) for row in rows],
        "values": [row[chart_cfg["values"]] for row in rows],
    }


def run_service(service_key, as_json=False):
    cfg = SERVICES[service_key]
    page = cfg["page"]

    user_id = session.get("user_id")
    if not user_id:
        if as_json:
            return jsonify({"error": "Сначала авторизуйтесь"}), 403
        return render_index(page=page, user_id=None, error="Сначала авторизуйтесь по user_id")

    try:
        rules = load_business_rules()
        rows = getattr(rules, cfg["get"])(user_id)
    except Exception as e:
        if as_json:
            return jsonify({"error": str(e)}), 500
        return render_index(page=page, user_id=user_id, error=f"Ошибка: {e}")

    if not rows:
        if as_json:
            return jsonify({"user_id": user_id, "service": service_key, "rows": [], "message": cfg["empty_msg"]})
        return render_index(
            page=page,
            user_id=user_id,
            active_service=service_key,
            service_title=cfg["title"],
            result_note=cfg["empty_msg"],
        )

    try:
        # Для сервисов-метрик Loginom возвращает единственную строку-агрегат.
        data = rows[0] if cfg["view"] == "metrics" else rows
        text = getattr(rules, cfg["build_text"])(data)

        started_at = time.perf_counter()
        prompt_text, recommendation, from_cache = getattr(rules, cfg["ask"])(user_id, text)
        response_time_ms = round((time.perf_counter() - started_at) * 1000)
    except Exception as e:
        if as_json:
            return jsonify({"error": str(e)}), 500
        return render_index(page=page, user_id=user_id, error=f"Ошибка: {e}")

    if as_json:
        return jsonify({
            "user_id": user_id,
            "service": service_key,
            "rows": rows,
            "prompt_text": prompt_text,
            "recommendation": recommendation,
            "from_cache": from_cache,
            "response_time_ms": response_time_ms,
        })

    view_data = {}
    if cfg["view"] == "table":
        view_data["columns"] = cfg["columns"]
        view_data["rows"] = rows
        if cfg.get("bar"):
            view_data["bars"] = _build_bars(rows, cfg["bar"])
        if cfg.get("chart"):
            view_data["chart"] = _build_chart(rows, cfg["chart"])
    else:
        view_data["metrics"] = getattr(rules, cfg["format"])(rows[0])

    return render_index(
        page=page,
        user_id=user_id,
        active_service=service_key,
        service_title=cfg["title"],
        result_view=cfg["view"],
        prompt_text=prompt_text,
        recommendation=recommendation,
        from_cache=from_cache,
        response_time_ms=response_time_ms,
        **view_data,
    )


@app.route("/", methods=["GET"])
def index():
    startup_error = None
    if not (BASE_DIR / "business-rules.py").exists():
        startup_error = "Файл business-rules.py не найден. "
    return render_index(page="home", error=startup_error)


@app.route("/history", methods=["GET"])
def history_page():
    return render_index(page="history")


@app.route("/insights", methods=["GET"])
def insights_page():
    return render_index(page="insights")


@app.route("/login", methods=["POST"])
def login():
    user_id = request.form.get("user_id", "").strip()
    if not user_id.isdigit():
        return render_index(user_id=None, error="user_id должен быть целым числом")

    user_id = int(user_id)

    try:
        rules = load_business_rules()
        rows = rules.get_user_history(user_id)
    except Exception as e:
        return render_index(user_id=None, error=f"Не удалось проверить user_id в Loginom: {e}")

    if not rows:
        return render_index(user_id=None, error="Клиент с таким user_id не найден в Loginom")

    session["user_id"] = user_id
    return render_index(page="history", user_id=user_id)


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return render_index()


@app.route("/service/<service_key>", methods=["POST"])
def service(service_key):
    if service_key not in SERVICES:
        abort(404)
    return run_service(service_key)


@app.route("/api/service/<service_key>", methods=["POST"])
def api_service(service_key):
    if service_key not in SERVICES:
        abort(404)
    return run_service(service_key, as_json=True)


# Совместимость: базовый сервис доступен и по прежним адресам.
@app.route("/history", methods=["POST"])
def history():
    return run_service("history")


@app.route("/api/history", methods=["POST"])
def api_history():
    return run_service("history", as_json=True)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port)
