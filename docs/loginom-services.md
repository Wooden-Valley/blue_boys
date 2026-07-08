# Что нужно сделать в Loginom

Приложение уже полностью готово под три новых аналитических сервиса. Со стороны
Python ничего менять не нужно — как только сервисы будут опубликованы в Loginom,
кнопки в интерфейсе сразу заработают.

Нужно опубликовать **3 новых REST-сервиса** в том же пакете, что и `GetUserHistory`
(`instacart_ws_Abakarov1`), тем же способом: **POST**, входная переменная `user_id`.

## ⚠️ Критично для совместимости

- **Имена сервисов — буква в букву** (регистр важен):
  `GetForgottenProducts`, `GetPurchaseRhythm`, `GetClientSummary`.
- **Имена выходных колонок — буква в букву** как в таблицах ниже
  (приложение читает их напрямую по имени).
- За основу берите свой запрос из `GetUserHistory` — там уже есть джойны с
  `products / aisles / departments` и колонка `department_rus`.
- Названия таблиц/полей ниже — стандартные для Instacart.
  **Подставьте свои, если у вас они называются иначе.**
- `:user_id` — привяжите входную переменную так же, как в `GetUserHistory`
  (синтаксис параметра подставьте свой, если отличается).

---

## 1. `GetForgottenProducts` — забытые товары

Товары, которые клиент часто покупал раньше, но которых не было в последних заказах.

| Колонка | Что это |
|---|---|
| `product_name` | название товара |
| `department_rus` | отдел (рус.) |
| `aisle` | категория |
| `times_bought` | сколько раз покупал всего |
| `orders_since_last` | сколько заказов назад покупал последний раз |

```sql
WITH user_orders AS (
    SELECT order_id, order_number FROM orders WHERE user_id = :user_id
),
user_max AS (SELECT MAX(order_number) AS max_no FROM user_orders),
prod AS (
    SELECT op.product_id,
           COUNT(*)             AS times_bought,
           MAX(uo.order_number) AS last_order_number
    FROM user_orders uo
    JOIN order_products op ON op.order_id = uo.order_id
    GROUP BY op.product_id
)
SELECT p.product_name,
       d.department_rus,
       a.aisle,
       prod.times_bought,
       (SELECT max_no FROM user_max) - prod.last_order_number AS orders_since_last
FROM prod
JOIN products    p ON p.product_id = prod.product_id
JOIN aisles      a ON a.aisle_id = p.aisle_id
JOIN departments d ON d.department_id = p.department_id
WHERE prod.times_bought >= 2
  AND prod.last_order_number < (SELECT max_no FROM user_max)
ORDER BY prod.times_bought DESC
LIMIT 10;
```

---

## 2. `GetPurchaseRhythm` — ритм покупок

Возвращает **одну строку** с агрегатами.

| Колонка | Что это |
|---|---|
| `total_orders` | всего заказов |
| `avg_days_between` | средний интервал между заказами (дни) |
| `favorite_dow` | любимый день недели, число 0–6 |
| `favorite_hour` | частый час, 0–23 |

```sql
SELECT
  (SELECT COUNT(*) FROM orders WHERE user_id = :user_id) AS total_orders,
  (SELECT AVG(days_since_prior_order) FROM orders
     WHERE user_id = :user_id AND days_since_prior_order IS NOT NULL) AS avg_days_between,
  (SELECT order_dow FROM orders WHERE user_id = :user_id
     GROUP BY order_dow ORDER BY COUNT(*) DESC LIMIT 1) AS favorite_dow,
  (SELECT order_hour_of_day FROM orders WHERE user_id = :user_id
     GROUP BY order_hour_of_day ORDER BY COUNT(*) DESC LIMIT 1) AS favorite_hour;
```

---

## 3. `GetClientSummary` — сводка по клиенту

Возвращает **одну строку** с метриками.

| Колонка | Что это |
|---|---|
| `total_orders` | всего заказов |
| `unique_products` | уникальных товаров |
| `total_items` | всего позиций куплено |
| `reorder_rate` | доля повторных покупок, **дробь 0..1** (приложение само переведёт в %) |
| `top_department_rus` | любимый отдел (рус.) |

```sql
SELECT
  (SELECT COUNT(*) FROM orders WHERE user_id = :user_id) AS total_orders,
  (SELECT COUNT(DISTINCT op.product_id)
     FROM orders o JOIN order_products op ON op.order_id = o.order_id
     WHERE o.user_id = :user_id) AS unique_products,
  (SELECT COUNT(*)
     FROM orders o JOIN order_products op ON op.order_id = o.order_id
     WHERE o.user_id = :user_id) AS total_items,
  (SELECT AVG(op.reordered)
     FROM orders o JOIN order_products op ON op.order_id = o.order_id
     WHERE o.user_id = :user_id) AS reorder_rate,
  (SELECT d.department_rus
     FROM orders o
     JOIN order_products op ON op.order_id = o.order_id
     JOIN products p    ON p.product_id = op.product_id
     JOIN departments d ON d.department_id = p.department_id
     WHERE o.user_id = :user_id
     GROUP BY d.department_rus ORDER BY COUNT(*) DESC LIMIT 1) AS top_department_rus;
```

---

## Нюансы

- **День недели.** В Instacart `order_dow` — число 0–6 без документированной
  привязки. В приложении заложено `0 = воскресенье`. Если у вас другое
  соответствие — поправьте один список `DOW_RU` в начале
  `webapp/business-rules.py`.
- **Пока сервис не создан**, его кнопка показывает `Ошибка: 404 ...` — это
  нормально, приложение не падает. Как опубликуете сервис — кнопка сразу
  заработает, ничего перезапускать или менять в коде не нужно.
- **Проверка:** после публикации откройте приложение, авторизуйтесь по `user_id`
  и нажмите кнопку сервиса — должны появиться данные и комментарий Mistral.

## Соответствие имён (сервис → колонки)

| Сервис | Выходные колонки |
|---|---|
| `GetForgottenProducts` | `product_name`, `department_rus`, `aisle`, `times_bought`, `orders_since_last` |
| `GetPurchaseRhythm` | `total_orders`, `avg_days_between`, `favorite_dow`, `favorite_hour` |
| `GetClientSummary` | `total_orders`, `unique_products`, `total_items`, `reorder_rate`, `top_department_rus` |
