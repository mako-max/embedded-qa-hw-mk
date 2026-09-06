import serial
from serial.tools import list_ports

from .base import Transport

# Стандартні параметри UART-протоколу пристрою: 115200 baud, 8N1.
DEFAULT_BAUDRATE = 115200
DEFAULT_TIMEOUT = 2
DEFAULT_DEVICE_VID = 0x1A86
SERIAL_BYTESIZE = serial.EIGHTBITS
SERIAL_PARITY = serial.PARITY_NONE
SERIAL_STOPBITS = serial.STOPBITS_ONE


# Створює pyserial-з'єднання з єдиною конфігурацією UART.
def create_serial_connection(
    port,
    *,
    baudrate=DEFAULT_BAUDRATE,
    timeout=DEFAULT_TIMEOUT,
):
    return serial.Serial(
        port=port,
        baudrate=baudrate,
        bytesize=SERIAL_BYTESIZE,
        parity=SERIAL_PARITY,
        stopbits=SERIAL_STOPBITS,
        timeout=timeout,
    )


# Реалізує Transport для фізичного підключення пристрою через UART.
class UARTTransport(Transport):
    def __init__(
        self,
        port,
        timeout=DEFAULT_TIMEOUT,
        *,
        baudrate=DEFAULT_BAUDRATE,
    ):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.serial_connection = None

    # Відкриває UART-порт один раз і очищає дані попередньої сесії.
    def open(self) -> None:
        if self.serial_connection is not None and self.serial_connection.is_open:
            return

        self.serial_connection = create_serial_connection(
            self.port,
            baudrate=self.baudrate,
            timeout=self.timeout,
        )
        self.serial_connection.reset_input_buffer()

    # Закриває UART-порт і дозволяє повторно використати transport.
    def close(self) -> None:
        if self.serial_connection is not None:
            self.serial_connection.close()
            self.serial_connection = None

    # Перетворює текстовий рядок на UART-команду з завершенням CRLF.
    def send_line(self, line: str) -> None:
        connection = self._get_open_connection()
        command = line.rstrip("\r\n") + "\r\n"
        connection.write(command.encode("utf-8"))
        connection.flush()

    # Читає один сирий рядок, не виходячи за timeout поточної операції.
    def read_line(self, timeout: float) -> bytes | None:
        connection = self._get_open_connection()
        original_timeout = connection.timeout

        try:
            connection.timeout = timeout
            raw_line = connection.readline()
        finally:
            connection.timeout = original_timeout

        return raw_line or None

    # Централізує перевірку стану порту для операцій читання та запису.
    def _get_open_connection(self):
        if self.serial_connection is None or not self.serial_connection.is_open:
            raise RuntimeError("UART transport is not open")

        return self.serial_connection


# Повертає доступні порти у стабільному порядку для відтворюваного вибору.
def get_available_ports():
    return sorted(list_ports.comports(), key=lambda port: port.device)


# Друкує діагностичну інформацію про знайдені UART-порти.
def print_available_ports(ports):
    print(f"Available serial ports: {len(ports)}")

    for port in ports:
        print(port.device)
        print(f"  description: {port.description or 'n/a'}")
        print(f"  hwid: {port.hwid or 'n/a'}")


# Обирає USB UART-порт навчального пристрою за VID, без hardcoded COM-порту.
def find_device_port(ports, device_vid=DEFAULT_DEVICE_VID):
    for port in ports:
        if port.vid == device_vid:
            return port.device

    raise RuntimeError(f"USB serial port with VID 0x{device_vid:04X} was not found")
