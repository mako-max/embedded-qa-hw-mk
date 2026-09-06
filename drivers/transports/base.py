from typing import Protocol


# Визначає мінімальний контракт для будь-якого способу зв'язку з пристроєм.
# DeviceDriver залежить тільки від цих чотирьох операцій, тому майбутній TCP/Wi-Fi
# transport можна додати без дублювання командної логіки та змін у тестах.
class Transport(Protocol):
    def open(self) -> None: ...

    def close(self) -> None: ...

    def send_line(self, line: str) -> None: ...

    def read_line(self, timeout: float) -> bytes | None: ...
