import os
import sys
import time
import unittest
from concurrent.futures import Future

from fastapi.testclient import TestClient

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
)

from bearpaw.api import RuntimeState, create_app
from bearpaw.config import AppConfig, WebSocketConfig
from bearpaw.models import ChannelData, DeviceInfo, LiveState
from bearpaw.state import StateStore
from bearpaw.websocket import WebSocketManager


class StubDriver:
    def __init__(self):
        self.last_key: str | None = None
        self.last_frequency: tuple[float, str | None] | None = None

    async def get_status(self):
        return LiveState(
            timestamp=time.time(),
            frequency=151.25,
            modulation="FM",
            squelch_open=True,
            rssi=75,
            mode="SCAN",
            channel=1,
            alpha_tag="TEST",
            volume=10,
            battery=100,
            stale=False,
        )

    async def send_hold(self):
        return True

    async def send_scan(self):
        return True

    async def send_key(self, key_code: str):
        self.last_key = key_code
        return True

    async def set_frequency(self, frequency_mhz: float, modulation=None):
        self.last_frequency = (frequency_mhz, modulation)
        return True

    async def read_channel(self, index: int):
        raise NotImplementedError

    async def detect_model(self):
        return "BC125AT"


class StubScheduler:
    def has_high_priority(self):
        return False


class StubTransport:
    def send_command(self, cmd: str):
        future = Future()
        future.set_result("OK")
        return future


class ApiTests(unittest.TestCase):
    def setUp(self) -> None:
        app = create_app(AppConfig(), startup_enabled=False)
        state_store = StateStore(persistence=None)
        state_store.update_live_state(
            LiveState(
                timestamp=time.time(),
                frequency=151.25,
                modulation="FM",
                squelch_open=True,
                rssi=75,
                mode="SCAN",
                channel=1,
                alpha_tag="TEST",
                volume=10,
                battery=100,
                stale=False,
            )
        )
        state_store.set_shadow_state(
            {
                1: ChannelData(
                    index=1,
                    frequency=151.25,
                    modulation="FM",
                    alpha_tag="Police",
                    delay=2,
                    lockout=False,
                    priority=True,
                    tone_squelch=None,
                    bank=1,
                )
            }
        )
        ws_config = WebSocketConfig()
        app.state.runtime = RuntimeState(
            config=AppConfig(),
            transport=StubTransport(),
            scheduler=StubScheduler(),
            driver=StubDriver(),
            state_store=state_store,
            ws_manager=WebSocketManager(ws_config),
            device_info=DeviceInfo(
                model="BC125AT",
                port="/dev/ttyACM0",
                vid=0x1965,
                pid=0x0017,
                serial_number=None,
                description="Uniden Scanner",
            ),
            session_id="test-session",
        )
        self.client = TestClient(app)

    def test_status(self) -> None:
        response = self.client.get("/api/v1/status")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["frequency"], 151.25)

    def test_health(self) -> None:
        response = self.client.get("/api/v1/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")

    def test_device_info(self) -> None:
        response = self.client.get("/api/v1/device/info")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["model"], "BC125AT")

    def test_commands(self) -> None:
        response = self.client.post("/api/v1/commands/hold")
        self.assertEqual(response.status_code, 200)
        response = self.client.post("/api/v1/commands/scan")
        self.assertEqual(response.status_code, 200)
        response = self.client.post("/api/v1/commands/key", json={"key": "UP"})
        self.assertEqual(response.status_code, 200)

    def test_key_aliases_translate_to_scanner_codes(self) -> None:
        driver = self.client.app.state.runtime.driver
        for friendly, expected in [
            ("UP", ">"),
            ("DOWN", "<"),
            ("MENU", "M"),
            ("FUNC", "F"),
            ("HOLD", "H"),
            ("ENTER", "E"),
        ]:
            response = self.client.post("/api/v1/commands/key", json={"key": friendly})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(driver.last_key, expected)

    def test_key_passthrough_for_native_codes(self) -> None:
        driver = self.client.app.state.runtime.driver
        response = self.client.post("/api/v1/commands/key", json={"key": "."})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(driver.last_key, ".")

    def test_set_frequency(self) -> None:
        driver = self.client.app.state.runtime.driver
        response = self.client.post(
            "/api/v1/frequency",
            json={"frequency": 151.25, "modulation": "FM"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(driver.last_frequency, (151.25, "FM"))

    def test_set_frequency_modulation_optional(self) -> None:
        driver = self.client.app.state.runtime.driver
        response = self.client.post("/api/v1/frequency", json={"frequency": 462.5625})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(driver.last_frequency, (462.5625, None))

    def test_memory_queries(self) -> None:
        response = self.client.get("/api/v1/memory/channels")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 1)
        response = self.client.get("/api/v1/memory/channels/1")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["alpha_tag"], "Police")


if __name__ == "__main__":
    unittest.main()
