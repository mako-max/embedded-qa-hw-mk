# Спільний RAM-профіль тестів; неправильний пароль використовується лише
# контрольованим rate-limit кейсом і не повинен потрапляти у cleanup.
TEST_LOGIN = "user"
TEST_PASSWORD = "111222"
WRONG_PASSWORD = "wrongpass"
FAILED_LOGIN_ATTEMPTS = 3

# History наповнюється реальною фоновою задачею: 32 с дають час отримати
# 10 показань з інтервалом 3 с разом із невеликим запасом на запуск.
DEFAULT_SENSOR_INTERVAL = 3000
SENSOR_COLLECTION_TIME = 32
EXPECTED_HISTORY_COUNT = 10

# Значення з reproduction steps SENTRY-ISSUE-0004. Обидва валідні за PRD та
# відрізняються від defaults, тому повернення дефолтів після reboot не дасть false pass.
PERSISTED_SENSOR_INTERVAL = 2500
PERSISTED_ALARM_THRESHOLD = 50

# `distance 10s` повертає 10 показань. PRD не задає окремий stability tolerance,
# тому для нерухомої мішені приймаємо консервативний максимальний розкид 2 см.
DISTANCE_READING_COUNT = 10
MIN_DISTANCE_CM = 1.0
MAX_DISTANCE_CM = 400.0
MAX_DISTANCE_SPREAD_CM = 2.0

# Alarm task перевіряє умови раз на секунду. Observation windows довші за один
# цикл потрібні для негативних перевірок, але коротші за calibration job (~4 с).
DEFAULT_ALARM_THRESHOLD = 80
ALARM_STATE_TIMEOUT = 4
ALARM_INHIBIT_OBSERVATION_TIME = 2.5
CALIBRATION_INHIBIT_OBSERVATION_TIME = 1.5
CANCELLED_JOB_OBSERVATION_TIME = 5

# FW блокує login на 30 с; додаткові 5 с покривають UART-відповіді та scheduling.
ACCOUNT_LOCK_RECOVERY_TIMEOUT = 35
