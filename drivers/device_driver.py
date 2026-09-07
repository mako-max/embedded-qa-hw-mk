#!/usr/bin/env python3

import argparse
import re
import sys
import time
from dataclasses import dataclass
from enum import StrEnum

# Відносні імпорти потрібні для `python -m drivers.device_driver`, а запасна
# гілка зберігає прямий запуск `python drivers/device_driver.py`.
if __package__:
    from .transports.base import Transport
    from .transports.uart import (
        DEFAULT_BAUDRATE,
        DEFAULT_DEVICE_VID,
        SERIAL_BYTESIZE,
        SERIAL_PARITY,
        SERIAL_STOPBITS,
        UARTTransport,
        find_device_port,
        get_available_ports,
        print_available_ports,
    )
else:
    from transports.base import Transport
    from transports.uart import (
        DEFAULT_BAUDRATE,
        DEFAULT_DEVICE_VID,
        SERIAL_BYTESIZE,
        SERIAL_PARITY,
        SERIAL_STOPBITS,
        UARTTransport,
        find_device_port,
        get_available_ports,
        print_available_ports,
    )

# Короткі polling-інтервали дають фоновим FreeRTOS-задачам змінити стан,
# але не перевантажують UART безперервними командами status/list.
DEFAULT_COMMAND_TIMEOUT = 2
DEFAULT_REBOOT_TIMEOUT = 5
DEFAULT_POLL_INTERVAL = 0.25
DEFAULT_JOB_TIMEOUT = 2
DEFAULT_DISTANCE_SERIES_TIMEOUT = 12

# Завдання вимагає `App started`, але поточна версія FW повідомляє `Device ready`.
# Альтернативний marker дозволяє тестувати обидві версії без hardcoded затримки.
CURRENT_FIRMWARE_READY_PATTERN = "Device ready"


class AlarmState(StrEnum):
    DISARMED = "DISARMED"
    ARMED = "ARMED"
    TRIGGERED = "TRIGGERED"
    CLEARED = "CLEARED"


# Enum зберігає відповідність між предметною операцією та UART-командою в драйвері,
# щоб параметризовані тести не містили логіки текстового протоколу.
class AlarmOperation(StrEnum):
    ARM = "alarm arm"
    DISARM = "alarm disarm"
    CLEAR = "alarm clear"
    STATUS = "alarm status"


class JobState(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    DONE = "DONE"
    CANCELLED = "CANCELLED"


# Розрізняємо нову й уже активну сесію: обидва стани достатні для cleanup,
# якщо через фонові UART-логи було пропущено початковий `Session Started`.
@dataclass(frozen=True)
class LoginAttemptResult:
    session_started: bool
    session_already_active: bool
    account_locked: bool

    @property
    def has_active_session(self):
        return self.session_started or self.session_already_active


@dataclass(frozen=True)
class AlarmStatus:
    state: AlarmState
    threshold: int
    last_value: float
    sensor_running: bool
    led_on: bool


# Виконує команди пристрою незалежно від способу доставки даних.
class DeviceDriver:
    # Отримує готовий transport замість параметрів конкретного з'єднання.
    def __init__(self, transport: Transport, timeout=DEFAULT_COMMAND_TIMEOUT):
        self.transport = transport
        self.timeout = timeout

    # Делегує відкриття з'єднання вибраному transport.
    def open(self):
        self.transport.open()

    # Делегує коректне закриття з'єднання вибраному transport.
    def close(self):
        self.transport.close()

    # Надсилає команду та збирає також асинхронні логи протягом усього timeout.
    # Коротка пауза стосується звичайних команд; reboot обходить цей метод і
    # очікує startup marker через wait_for_pattern(), як вимагає завдання.
    def send_command(self, command):
        self.transport.send_line(command)
        time.sleep(0.1)

        return self.read_lines(self.timeout)

    # Збирає непорожні рядки до deadline, навіть якщо між ними є паузи.
    # Такий fixed-time режим потрібен для історії та вільного потоку фонових логів,
    # але саме через реальний timeout окремі hardware-тести виконуються довго.
    def read_lines(self, timeout):
        lines = []
        end_time = time.time() + timeout

        while time.time() < end_time:
            remaining_time = end_time - time.time()
            # Transport сам застосовує timeout до конкретної операції читання.
            raw_line = self.transport.read_line(min(0.1, max(remaining_time, 0)))

            if not raw_line:
                continue

            line = raw_line.decode("utf-8", errors="replace")
            # Видаляємо ANSI-коди кольору, щоб тести працювали з чистим текстом.
            line = re.sub(r"\x1b\[[0-9;]*[mK]", "", line)
            line = line.strip("\r\n")

            if line.strip():
                lines.append(line)

        return lines

    # Збирає рядки до response marker, не чекаючи весь fixed timeout.
    # alternatives покриває еквівалентні відповіді різних версій прошивки;
    # сторонні FreeRTOS-логи не завершують читання, доки marker не знайдено.
    def read_lines_until(self, pattern, timeout, alternatives=()):
        expected_patterns = (pattern, *alternatives)
        lines = []
        end_time = time.time() + timeout

        while time.time() < end_time:
            remaining_time = end_time - time.time()
            raw_line = self.transport.read_line(min(0.1, max(remaining_time, 0)))

            if not raw_line:
                continue

            line = raw_line.decode("utf-8", errors="replace")
            line = re.sub(r"\x1b\[[0-9;]*[mK]", "", line)
            line = line.strip("\r\n")

            if not line.strip():
                continue

            lines.append(line)

            if any(expected in line for expected in expected_patterns):
                return lines, True

        return lines, False

    # Надсилає команду й завершує читання одразу після її response marker.
    def send_command_until(self, command, pattern, timeout=None, alternatives=()):
        response_timeout = self.timeout if timeout is None else timeout
        self.transport.send_line(command)
        return self.read_lines_until(
            pattern,
            response_timeout,
            alternatives=alternatives,
        )

    # Читає нові рядки до появи очікуваного або сумісного pattern.
    def wait_for_pattern(self, pattern, timeout=DEFAULT_REBOOT_TIMEOUT, alternatives=()):
        _, matched = self.read_lines_until(
            pattern,
            timeout,
            alternatives=alternatives,
        )
        return matched

    # Зберігає сумісність із попереднім публічним API драйвера.
    def wait_for(self, pattern, timeout):
        return self.wait_for_pattern(pattern, timeout)

    # Перезавантажує авторизований пристрій без sleep і очікує старт застосунку.
    def reboot(self, timeout=DEFAULT_REBOOT_TIMEOUT):
        # UART залишається доступним під час software reboot, тому читаємо boot log
        # з поточного transport замість фіксованої паузи або повторного відкриття порту.
        self.transport.send_line("reboot")
        return self.wait_for_pattern(
            "App started",
            timeout,
            alternatives=(CURRENT_FIRMWARE_READY_PATTERN,),
        )

    # Перевіряє доступність CLI та ключових базових команд через help.
    def is_cli_responsive(self):
        response = self.send_command("help")
        output = "\n".join(response)
        required_markers = ("=== Commands ====", "status", "reboot")

        return "Access denied" not in output and all(
            marker in output for marker in required_markers
        )

    # Перевіряє завершеність status та наявність доступної heap-пам'яті.
    def is_system_status_healthy(self):
        response = self.send_command("status")
        output = "\n".join(response)
        heap_match = re.search(r"\[Status\] Free heap:\s+(\d+) bytes", output)

        return (
            "Access denied" not in output
            and "[Status] Checking components" in output
            and "[Status] Done." in output
            and heap_match is not None
            and int(heap_match.group(1)) > 0
        )

    # Перемикає джерело alarm на температурну телеметрію.
    def set_sensor_mode_temperature(self):
        _, matched = self.send_command_until(
            "sensor mode temp",
            "[Sensor] Mode: TEMP",
        )
        return matched

    # Збирає штатну серію з 10 distance-вимірів та повертає calibrated cm.
    # Команда сама витримує інтервал 1 с; тест не керує часом через sleep.
    def collect_distance_readings(self, timeout=DEFAULT_DISTANCE_SERIES_TIMEOUT):
        response, completed = self.send_command_until(
            "distance 10s",
            "[Distance] Done.",
            timeout=timeout,
        )
        output = "\n".join(response)

        if not completed:
            raise RuntimeError(f"Distance series did not complete:\n{output}")

        calibrated_values = re.findall(
            r"\[Distance\]\s+#\d+\s+"
            r"-?\d+(?:\.\d+)?\s+cm\s+"
            r"\(calibrated:\s*(-?\d+(?:\.\d+)?)\s+cm\)",
            output,
        )

        return [float(value) for value in calibrated_values]

    # Запускає фонове отримання показань сенсора.
    def start_sensor(self):
        _, matched = self.send_command_until(
            "sensor start",
            "Starting data acquisition",
        )
        return matched

    # Встановлює робочий інтервал сенсора без збереження у fake NVS.
    def set_sensor_interval(self, interval):
        _, matched = self.send_command_until(
            f"config set sensor_interval {interval}",
            f"[Config] sensor_interval = {interval}",
        )
        return matched

    # Читає числове значення config key, не передаючи розбір UART-виводу в тест.
    # Одиниці `ms`/`cm` необов'язкові: різні параметри та версії FW форматують їх
    # по-різному, але числовий контракт команди залишається однаковим.
    def get_config_value(self, key):
        response, matched = self.send_command_until(
            f"config get {key}",
            f"[Config] {key} =",
        )
        output = "\n".join(response)
        value_match = re.search(
            rf"\[Config\]\s+{re.escape(key)}\s*=\s*(-?\d+)\b",
            output,
        )

        if not matched or value_match is None:
            raise RuntimeError(f"Cannot parse config value for {key!r}:\n{output}")

        return int(value_match.group(1))

    # Повертає snapshot вибраних параметрів після окремого config get для кожного.
    def get_config_values(self, keys):
        return {key: self.get_config_value(key) for key in keys}

    # Копіює робочу конфігурацію в NVS і чекає marker завершеного commit.
    def save_config(self):
        _, matched = self.send_command_until(
            "config save",
            "[Config] Saved successfully.",
        )
        return matched

    # Завантажує NVS-копію у робочу конфігурацію; warning про defaults не вважаємо
    # protocol failure, якщо FW завершила операцію marker-ом успішного застосування.
    def load_config(self):
        _, matched = self.send_command_until(
            "config load",
            "[Config] Config applied successfully.",
        )
        return matched

    # Зупиняє сенсор; повторна зупинка також вважається досягненням цільового стану.
    def stop_sensor(self):
        _, matched = self.send_command_until(
            "sensor stop",
            "Sensor stopped",
            alternatives=("Already stopped", "already stopped"),
        )
        return matched

    # Встановлює manual override, щоб alarm-тести не залежали від фізичного сенсора.
    def set_sensor_value(self, value):
        _, matched = self.send_command_until(
            f"sensor set {value}",
            "Manual override: value locked",
        )
        return matched

    # Збирає автоматичні показання у реальному часі FW і гарантовано зупиняє сенсор.
    # read_lines() тут навмисно блокується: history наповнює фонова задача ESP32,
    # тому 10 показань з інтервалом 3 с неможливо отримати миттєво.
    def collect_sensor_readings(self, duration):
        if not self.start_sensor():
            return False

        stopped = False

        try:
            self.read_lines(duration)
        finally:
            stopped = self.stop_sensor()

        return stopped

    # Повертає кількість temperature readings у history без розбору в тесті.
    def get_sensor_history_count(self):
        response = self.send_command("sensor history")
        return sum(
            "[Sensor]" in line and "] temp:" in line for line in response
        )

    # Змінює робочий поріг alarm без збереження у fake NVS.
    def set_alarm_threshold(self, threshold):
        _, matched = self.send_command_until(
            f"config set alarm_threshold {threshold}",
            f"[Config] alarm_threshold = {threshold}",
        )
        return matched

    # Активує моніторинг порогової сигналізації.
    def arm_alarm(self):
        _, matched = self.send_command_until(
            "alarm arm",
            "State: ARMED. Monitoring active.",
        )
        return matched

    # Переводить alarm у DISARMED; already DISARMED є валідним цільовим станом.
    def disarm_alarm(self):
        _, matched = self.send_command_until(
            "alarm disarm",
            "State: DISARMED.",
            alternatives=("Already DISARMED.",),
        )
        return matched

    # Повертає True лише для дозволеного переходу TRIGGERED -> CLEARED.
    # `Nothing to clear` також є marker завершеної відповіді, але не успішного переходу.
    def clear_alarm(self):
        response, _ = self.send_command_until(
            "alarm clear",
            "State: CLEARED",
            alternatives=("Nothing to clear",),
        )
        return any("State: CLEARED" in line for line in response)

    # Перетворює текст alarm status на предметну модель для тестів.
    # LED є останнім полем status, тому його marker означає, що всі поля вже отримано.
    def get_alarm_status(self):
        response, matched = self.send_command_until(
            "alarm status",
            "[Alarm] LED state:",
        )

        if not matched:
            raise RuntimeError("Alarm status response was not completed")

        output = "\n".join(response)
        state_match = re.search(
            r"\[Alarm\] State:\s+(DISARMED|ARMED|TRIGGERED|CLEARED)\b",
            output,
        )
        threshold_match = re.search(r"\[Alarm\] Threshold:\s+(\d+)", output)
        value_match = re.search(
            r"\[Alarm\] Last value:\s+(-?\d+(?:\.\d+)?)",
            output,
        )
        sensor_match = re.search(r"\[Alarm\] Sensor:\s+(running|stopped)", output)
        led_match = re.search(r"\[Alarm\] LED state:\s+(ON|OFF)", output)

        if (
            state_match is None
            or threshold_match is None
            or value_match is None
            or sensor_match is None
            or led_match is None
        ):
            raise RuntimeError(f"Cannot parse alarm status response:\n{output}")

        return AlarmStatus(
            state=AlarmState(state_match.group(1)),
            threshold=int(threshold_match.group(1)),
            last_value=float(value_match.group(1)),
            sensor_running=sensor_match.group(1) == "running",
            led_on=led_match.group(1) == "ON",
        )

    # Опитує alarm status до очікуваного стану з обмеженою частотою запитів.
    def wait_for_alarm_state(self, expected_state, timeout):
        end_time = time.time() + timeout

        while time.time() < end_time:
            status = self.get_alarm_status()

            if status.state is expected_state:
                return status

            time.sleep(DEFAULT_POLL_INTERVAL)

        return None

    # Перевіряє, що alarm не залишає стан протягом заданого вікна спостереження.
    def alarm_state_remains(self, expected_state, duration):
        end_time = time.time() + duration
        observed_status = False

        while time.time() < end_time:
            status = self.get_alarm_status()
            observed_status = True

            if status.state is not expected_state:
                return False

            remaining_time = end_time - time.time()
            if remaining_time > 0:
                time.sleep(min(DEFAULT_POLL_INTERVAL, remaining_time))

        return observed_status

    # Запускає calibration job і повертає ID після активації alarm inhibit.
    # Очікування двофазне: PENDING містить ID, а окремий асинхронний marker ACTIVE
    # гарантує, що небезпечне sensor value можна подавати без гонки з alarm task.
    def add_calibration_job(self, timeout=DEFAULT_JOB_TIMEOUT):
        response, queued = self.send_command_until(
            "job add calibrate",
            "[Job] State:  PENDING",
            timeout=timeout,
        )
        id_match = re.search(r"\[Job\] ID:\s+(\d+)", "\n".join(response))

        if not queued or id_match is None:
            return None

        if not self.wait_for_pattern("Alarm inhibit: ACTIVE", timeout):
            return None

        return int(id_match.group(1))

    # Скасовує calibration job і перевіряє, що alarm inhibit було знято.
    def cancel_calibration_job(self, job_id, timeout=DEFAULT_JOB_TIMEOUT):
        response, _ = self.send_command_until(
            f"job cancel {job_id}",
            "Alarm monitoring restored.",
            timeout=timeout,
        )
        return any(
            f"#{job_id}" in line and "CANCELLED" in line for line in response
        )

    # Читає поточний стан конкретної calibration job із job list.
    # Короткий timeout важливий: сама job триває близько 4 с, і довге читання
    # приховало б проміжний CANCELLED перед помилковим переходом FW у DONE.
    def get_calibration_job_state(self, job_id, timeout=0.75):
        self.transport.send_line("job list")
        response = self.read_lines(timeout)
        state_match = re.search(
            rf"\[Job\] #{job_id}\s+calibrate\s+"
            r"(PENDING|RUNNING|DONE|CANCELLED)\b",
            "\n".join(response),
        )

        if state_match is None:
            return None

        return JobState(state_match.group(1))

    # Очікує цільовий стан calibration job через контрольоване polling-вікно.
    def wait_for_calibration_job_state(self, job_id, expected_state, timeout):
        end_time = time.time() + timeout

        while time.time() < end_time:
            state = self.get_calibration_job_state(job_id)

            if state is expected_state:
                return state

            time.sleep(DEFAULT_POLL_INTERVAL)

        return None

    # Перевіряє стабільність terminal state протягом усього observation window.
    # Одноразового CANCELLED недостатньо: дефектна фонова job пізніше записує DONE.
    def calibration_job_state_remains(self, job_id, expected_state, duration):
        end_time = time.time() + duration
        observed_state = False

        while time.time() < end_time:
            state = self.get_calibration_job_state(job_id)
            observed_state = True

            if state is not expected_state:
                return False

            remaining_time = end_time - time.time()
            if remaining_time > 0:
                time.sleep(min(DEFAULT_POLL_INTERVAL, remaining_time))

        return observed_state

    # Завершує сесію та очікує повної зупинки залежних сервісів.
    def logout(self):
        _, matched = self.send_command_until(
            "logout",
            "All services stopped. Session closed.",
        )
        return matched

    # Перевіряє саме access-control відмову, а не загальний command failure.
    def is_alarm_operation_access_denied(self, operation: AlarmOperation):
        _, denied = self.send_command_until(
            operation.value,
            "Access denied",
        )
        return denied

    # Створює профіль і визначає успіх за маркером у відповіді прошивки.
    def register(self, login, password):
        response = self.send_command(f"register {login} {password}")
        return any("Profile Created" in line for line in response)

    # Виконує одну login-спробу та класифікує результат протоколу.
    def login_attempt(self, login, password):
        response = self.send_command(f"login {login} {password}")
        output = "\n".join(response)
        return LoginAttemptResult(
            session_started="Session Started" in output,
            session_already_active="Already logged in" in output,
            account_locked="locked" in output.lower(),
        )

    # Очікує реальний 30-секундний lockout FW, використовуючи лише правильні дані.
    # Некласифікована відповідь не завершує polling: UART може змішати її з
    # фоновими логами, а наступна спроба розпізнає Session Started/Already logged in.
    def wait_for_login(self, login, password, timeout, poll_interval=1):
        end_time = time.time() + timeout

        while time.time() < end_time:
            result = self.login_attempt(login, password)

            if result.has_active_session:
                return True

            remaining_time = end_time - time.time()
            if remaining_time > 0:
                time.sleep(min(poll_interval, remaining_time))

        return False

    # Спочатку реєструє профіль, а потім авторизується згідно з контрактом завдання.
    def login(self, login, password):
        self.register(login, password)
        return self.login_attempt(login, password).has_active_session


# Збирає необроблені байти transport для діагностики без декодування тексту.
def read_raw_response(transport: Transport, timeout):
    response = bytearray()
    end_time = time.time() + timeout

    while time.time() < end_time:
        remaining_time = end_time - time.time()
        raw_line = transport.read_line(min(0.1, max(remaining_time, 0)))

        if raw_line:
            response.extend(raw_line)

    return bytes(response)


def parse_device_vid(value):
    text = value.strip()
    try:
        vid = int(text, 16 if text.lower().startswith("0x") else 10)
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "VID must be decimal or hexadecimal with a 0x prefix"
        ) from error
    if not 0 <= vid <= 0xFFFF:
        raise argparse.ArgumentTypeError("VID must be between 0x0000 and 0xFFFF")
    return vid


# Описує параметри CLI з можливістю змінити port, VID, baudrate і timeout.
def build_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", help="explicit serial port; overrides VID autodetection")
    parser.add_argument(
        "--vid",
        type=parse_device_vid,
        default=DEFAULT_DEVICE_VID,
        help="USB VID: decimal or 0x-prefixed hex (default: 0x1A86)",
    )
    parser.add_argument(
        "--baudrate",
        type=int,
        default=DEFAULT_BAUDRATE,
        help=f"serial baud rate (default: {DEFAULT_BAUDRATE})",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_COMMAND_TIMEOUT,
        help=f"response timeout in seconds (default: {DEFAULT_COMMAND_TIMEOUT})",
    )
    return parser


# Виконує діагностичну команду help і показує її необроблену відповідь.
def run(args):
    ports = get_available_ports()
    print_available_ports(ports)

    port = args.port
    if port is None:
        port = find_device_port(ports, device_vid=args.vid)

    print(f"Selected port: {port}")
    print(
        f"Connection parameters: {args.baudrate} baud, "
        f"{SERIAL_BYTESIZE} data bits, parity {SERIAL_PARITY}, "
        f"{SERIAL_STOPBITS} stop bit"
    )
    print(f"Timeout: {args.timeout:g} seconds")

    transport = UARTTransport(
        port,
        baudrate=args.baudrate,
        timeout=args.timeout,
    )

    try:
        transport.open()
        command = "help"
        print(f"Sent bytes: {(command + chr(13) + chr(10)).encode()!r}")

        transport.send_line(command)
        raw_response = read_raw_response(transport, args.timeout)
        print(f"Raw response ({len(raw_response)} bytes):")
        print(repr(raw_response))
    finally:
        transport.close()

    return 0


# Перетворює помилки serial і конфігурації на зрозумілий код завершення CLI.
def main():
    parser = build_parser()
    args = parser.parse_args()

    try:
        return run(args)
    except (OSError, RuntimeError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
