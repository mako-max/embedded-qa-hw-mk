import pytest

from drivers.device_driver import DeviceDriver
from drivers.transports.uart import UARTTransport, find_device_port, get_available_ports
from tests.constants import (
    ACCOUNT_LOCK_RECOVERY_TIMEOUT,
    DEFAULT_ALARM_THRESHOLD,
    TEST_LOGIN,
    TEST_PASSWORD,
)


# Приводить пристрій до стану з новим профілем і без активної сесії.
def prepare_test_profile(driver):
    # Успішний reboot очищає RAM-профіль, тому його створюємо заново.
    if driver.reboot():
        assert driver.register(TEST_LOGIN, TEST_PASSWORD), "Registration failed"
        return

    # Якщо reboot заборонено й профілю немає, register одразу завершує підготовку.
    if driver.register(TEST_LOGIN, TEST_PASSWORD):
        return

    # Існуючий тестовий профіль потрібно авторизувати й створити заново після reboot.
    assert driver.login(
        TEST_LOGIN,
        TEST_PASSWORD,
    ), "Cannot access the existing test profile"

    assert driver.reboot(), "Failed to reset the existing test profile"
    assert driver.register(TEST_LOGIN, TEST_PASSWORD), "Registration failed"


# Відкриває окреме з'єднання для кожного тесту та завжди закриває його після тесту.
# Порт знаходиться за VID USB-UART, тому назва на кшталт /dev/ttyACM0 не залежить
# від середовища. Фізичний пристрій один: паралельний pytest запуск не підтримується.
@pytest.fixture
def connected_device():
    ports = get_available_ports()
    port = find_device_port(ports)
    transport = UARTTransport(port)
    driver = DeviceDriver(transport)

    try:
        driver.open()
        # Function scope ізолює Python-з'єднання, але не RAM-стан ESP32: сесію,
        # sensor та alarm мають явно очищати залежні фікстури.
        yield driver
    finally:
        driver.close()


# Готує авторизований пристрій для функціональних тестів.
@pytest.fixture
def device(connected_device):
    prepare_test_profile(connected_device)

    assert connected_device.login(
        TEST_LOGIN,
        TEST_PASSWORD,
    ), "Login failed after device setup"

    return connected_device


# Гарантує AUTH_NONE без неправильних паролів, щоб не зачепити rate limit.
# Після кейсу правильний login відновлює AUTH_USER: наступна фікстура зможе
# одразу виконати авторизований reboot і не залежатиме від порядку тестів.
@pytest.fixture
def unauthenticated_device(device):
    assert device.logout(), "Cannot close session for authorization test"

    try:
        yield device
    finally:
        assert device.login(
            TEST_LOGIN,
            TEST_PASSWORD,
        ), "Cannot restore session after authorization test"


# Створює ізольований TEMP-alarm стан і прибирає його навіть після падіння тесту.
@pytest.fixture
def alarm_device(device):
    try:
        assert device.set_sensor_mode_temperature(), "Cannot select TEMP sensor mode"
        assert device.disarm_alarm(), "Cannot reset alarm to DISARMED"
        assert device.set_alarm_threshold(
            DEFAULT_ALARM_THRESHOLD
        ), "Cannot configure alarm threshold"
        assert device.start_sensor(), "Cannot start sensor for alarm test"
        yield device
    finally:
        # Cleanup є best effort і не перекриває початковий assert новою помилкою;
        # наступний device setup додатково виконує reboot для повної ізоляції RAM.
        device.disarm_alarm()
        device.stop_sensor()


# Готує профіль без login, щоб тест міг накопичити невдалі спроби авторизації.
@pytest.fixture
def rate_limit_device(connected_device):
    prepare_test_profile(connected_device)

    try:
        yield connected_device
    finally:
        # Тест навмисно залишає профіль locked на 30 с. Чекаємо реальний таймер FW
        # плюс запас, відновлюємо сесію правильним паролем і лише тоді reboot-имо;
        # тому цей teardown є найдовшою частиною загального hardware-suite.
        assert connected_device.wait_for_login(
            TEST_LOGIN,
            TEST_PASSWORD,
            ACCOUNT_LOCK_RECOVERY_TIMEOUT,
        ), "Account lockout did not expire during fixture cleanup"
        assert connected_device.reboot(), (
            "Device did not reboot after rate-limit fixture cleanup"
        )
