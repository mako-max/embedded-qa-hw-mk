# Embedded QA Hardware Tests

## Install

python -m venv .venv
source .venv/bin/activate
python -m pip install pytest pyserial

## Run all tests

python -m pytest -v

Повний прогін на фізичному ESP32-S3 займає близько п'яти хвилин. Це очікувано:

- кожний параметризований кейс отримує окреме UART-з'єднання та чистий RAM-стан;
- sensor history збирає реальні показання приблизно 32 секунди;
- rate-limit cleanup чекає 30-секундний таймер блокування прошивки;
- негативні alarm-перевірки спостерігають стан довше одного циклу фонової задачі.

Не запускайте hardware-тести паралельно: усі worker-процеси використовуватимуть один
USB-UART і спільний стан одного пристрою. Поточні дефекти FW позначено strict `xfail`;
їхній `XPASS` є помилкою та означає, що після виправлення FW мітку треба прибрати.

## Run smoke tests

```bash
python -m pytest -v tests/smoke/test_smoke.py
```

## Run alarm tests

python -m pytest -v tests/functional/test_alarm.py

## Run known-bug regression tests

python -m pytest -v tests/functional/test_bugs.py

## Run sensor history test

python -m pytest -v tests/functional/test_bugs.py::test_sensor_history_keeps_last_ten_readings

## Run rate-limit test

python -m pytest -v tests/functional/test_bugs.py::test_login_rate_limit
