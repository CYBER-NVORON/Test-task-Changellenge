## Smoke: 50 users, 10 users/s, 1m

| Метрика | Значение |
|---|---:|
| Requests | 6 544 |
| Failures | 0 |
| RPS | 110.34 |
| Avg response | 313 ms |
| p50 | 290 ms |
| p95 | 530 ms |
| p99 | 710 ms |
| Max | 1 217 ms |

Результат: успешно, ошибок нет.

## Main: 500 users, 50 users/s, 2m

| Метрика | Значение |
|---|---:|
| Requests | 277 |
| Failures | 105 |
| RPS | 3.02 |
| Failure rate | 37.9% |
| Avg response | 27 773 ms |
| p50 | 840 ms |
| p95 | 90 000 ms |
| Max | 89 628 ms |

Результат: прогон не выдержан.

## Причина падения

В `docs/api_after_load.log` повторяется ошибка:

```text
sqlalchemy.exc.TimeoutError: QueuePool limit of size 5 overflow 10 reached, connection timed out
```

То есть API уперся в пул соединений SQLAlchemy/PostgreSQL. В `docs/locust_500u_failures.csv` зафиксированы HTTP 500 на всех основных эндпоинтах.

## Вывод

Текущая конфигурация подходит для профиля около 50 пользователей, но не выдерживает 500 пользователей. Для роста нагрузки нужно настраивать пул соединений, количество API workers, лимиты PostgreSQL.
