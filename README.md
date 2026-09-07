# SENTRY-C1 Hardware Tests

Pytest-тести прошивки SENTRY-C1 на ESP32-S3 через USB-UART. Python 3.11+, Linux/Unix.

## Встановлення

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install pytest pyserial
```

## Запуск

Підключіть плату з прошивкою SENTRY-C1, закрийте serial monitor.
Тести змінюють стан пристрою та виконують reboot.

```bash
# Увесь набір
python -m pytest -v

# Smoke
python -m pytest -v tests/smoke/test_smoke.py

# Alarm
python -m pytest -v tests/functional/test_alarm.py

# Persistence
python -m pytest -v tests/functional/test_config.py

# Distance stability
python -m pytest -v tests/functional/test_distance_stability.py

# Regression
python -m pytest -v tests/functional/test_bugs.py
```

Відомі дефекти позначені `xfail` із причинами. Увімкнено `xfail_strict`:
після виправлення FW відповідну мітку потрібно прибрати.

## Стенд для distance stability

US-100 у Trig/Echo-режимі (перемичка знята), нерухома плоска мішень на 15 см.
Тест виконує 3 серії по 10 вимірів без reboot між серіями.

Критерії: усі показання в межах 1–400 см, розкид кожної серії ≤ 2 см,
розкид середніх трьох серій ≤ 2 см. Це перевірка повторюваності, не абсолютної точності.
Допуски — тестові припущення в `tests/constants.py`, не специфікація US-100.

## UART / CLI драйвера

Pytest автоматично вибирає порт за VID `0x1A86`.
Окремий CLI надсилає `help` і показує raw-відповідь:

```bash
# Список портів і USB ID
python -m serial.tools.list_ports -v

# Стандартний VID
python -m drivers.device_driver

# Інший VID або явний порт — приклади
python -m drivers.device_driver --vid 0x303A
python -m drivers.device_driver --port /dev/ttyACM0
```

VID: hex із префіксом `0x` або decimal. `--port` має пріоритет над `--vid`.
Обидві опції належать лише CLI драйвера; pytest-фікстури вони не змінюють.
