# Device Statistics Service

REST-сервис для сбора и анализа показаний устройств. Данные привязываются к устройству и временной метке, сохраняются в PostgreSQL и используются для расчета статистики.


## ТЗ
```
Вам требуется написать сервис на Python согласно техническому заданию ниже.

При разработке предлагается использовать Python версии не ниже 3.8, pip / poetry.

Примечания

● Пункты отмеченные “” необязательны к выполнению

● Необходимо подготовить описание реализованного сервиса

● Приложить результаты нагрузочного тестирования

● Формат предоставления: ссылка на репозиторий с кодом


Описание системы

К реализации предлагается система учета и анализа данных, поступающих с условного устройства. Полученные данные привязываются к временной метке и устройству, с которого пришли данные, и сохраняются в БД. Набор данных используется для дальнейшего анализа.

Требования к системе:

Функциональные

● В системе реализован сбор статистики с устройства по его идентификатору

○ формат получаемой статистики - {“x”: float, “y”: float, “z”:float}

● В системе реализован анализ собранной статистики с устройства за определенный период и за все время

● Результатами анализа являются числовые характеристики величины:

○ минимальное значение

○ максимальное значение

○ количество

○ сумма

○ медиана

● Система поддерживает добавление пользователей устройств*

● В системе реализован функционал получения анализа показаний устройств по идентификатору пользователя*:

○ агрегированные результаты для всех устройств

○ для каждого устройства отдельно

Нефункциональные

● архитектура REST

● фреймворк реализации сервиса FastApi

● собранные данные хранятся в БД на выбор разработчика

● аналитика показателей происходит в асинхронном режиме при помощи фреймворка Celery*

● Реализовано нагрузочное тестирование через инструмент locust*

● Сервис и его окружение разворачивается средствами docker + docker-compose
```

## Что реализовано

- прием показаний устройства в формате `{"x": float, "y": float, "z": float}`;
- автоматическое создание устройства при первом показании;
- безопасное создание устройства при параллельных запросах через обработку `IntegrityError`;
- пользователи и привязка устройств к пользователям;
- анализ устройства за период или за все время;
- анализ пользователя: агрегат по всем устройствам и детализация по каждому устройству;
- расчет `min`, `max`, `count`, `sum`, `median` отдельно для `x`, `y`, `z`;
- PostgreSQL-only аналитика: медиана считается в БД через `percentile_cont(0.5)`;
- асинхронная аналитика через Celery;
- персистентные статусы Celery-задач в таблице `analysis_tasks`;
- валидация `device_identifier`, запрет `NaN/inf`, запрет timestamp дальше чем на 5 минут в будущем;
- единый формат ошибок;
- Docker Compose окружение: FastAPI, PostgreSQL, Redis, Celery worker, Locust;
- нагрузочное тестирование через Locust.

## ER-диаграмма БД

![ER-диаграмма БД](img/db.png)


## Быстрый запуск

```bash
cp .env.example .env
docker compose up --build
```

После запуска:

- API: `http://localhost:8000`
- Swagger UI: `http://localhost:8000/docs`
- healthcheck: `http://localhost:8000/health`

## Основные эндпоинты

Создание пользователя:

```bash
curl -X POST http://localhost:8000/users \
  -H "Content-Type: application/json" \
  -d '{"name":"Max","email":"maxutko555@example.com"}'
```

Привязка устройства:

```bash
curl -X POST http://localhost:8000/users/1/devices \
  -H "Content-Type: application/json" \
  -d '{"identifier":"device-001"}'
```

Отправка показания:

```bash
curl -X POST http://localhost:8000/devices/device-001/readings \
  -H "Content-Type: application/json" \
  -d '{"x":1.5,"y":2.5,"z":3.5}'
```

Аналитика устройства:

```bash
curl http://localhost:8000/devices/device-001/analysis
```

Аналитика устройства за период:

```bash
curl "http://localhost:8000/devices/device-001/analysis?date_from=2026-05-01T00:00:00Z&date_to=2026-05-19T23:59:59Z"
```

Аналитика пользователя:

```bash
curl http://localhost:8000/users/1/analysis
```

Асинхронная аналитика устройства:

```bash
curl -X POST http://localhost:8000/analytics/devices/device-001 \
  -H "Content-Type: application/json" \
  -d '{"date_from":null,"date_to":null}'
```

Статус Celery-задачи:

```bash
curl http://localhost:8000/analytics/tasks/<task_id>
```

## Формат ошибок

```json
{
  "error": {
    "code": "validation_error",
    "message": "Request validation failed",
    "details": []
  }
}
```

## Нагрузочное тестирование

Сценарий находится в `locustfile.py`. Он создает пользователя и устройство для каждого виртуального пользователя, затем выполняет смешанную нагрузку:

- `POST /devices/{device_identifier}/readings`, вес 10;
- `GET /devices/{device_identifier}/analysis`, вес 2;
- `GET /users/{user_id}/analysis`, вес 1.

Интерактивный запуск:

```bash
docker compose --profile loadtest up --build locust
```

UI будет доступен на `http://localhost:8089`.

Headless запуск с сохранением CSV и HTML-отчета:

```bash
mkdir -p docs
docker compose up -d --build api worker
docker compose --profile loadtest run --rm locust \
  locust -f locustfile.py \
  --host http://api:8000 \
  --headless -u 50 -r 10 -t 2m \
  --csv docs/locust_postgres \
  --html docs/locust_postgres_report.html
```

Актуальный отчет: `docs/load_test_results.md`.

## Тесты

Быстрые unit-тесты без БД:

```bash
pytest tests/test_validation.py
```

Полный API/integration-прогон требует отдельную PostgreSQL-БД. Имя базы должно содержать `test`, потому что тесты пересоздают таблицы:

```bash
TEST_DATABASE_URL=postgresql+psycopg://user:password@localhost:5432/device_stats_test pytest
```
