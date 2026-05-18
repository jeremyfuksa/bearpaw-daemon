import os
import sys
import time
import unittest
from concurrent.futures import Future

from fastapi.testclient import TestClient

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
)

from bearpaw.api import RuntimeState, _select_poll_interval, create_app
from bearpaw.config import AppConfig, PollingConfig, WebSocketConfig
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


class AdaptivePollIntervalTests(unittest.TestCase):
    def _runtime(self, ws_manager: WebSocketManager) -> RuntimeState:
        config = AppConfig(
            polling=PollingConfig(sts_interval=0.1, idle_sts_interval=1.0)
        )
        device_info = DeviceInfo(
            model="BC125AT",
            port="/dev/ttyACM0",
            vid=0x1965,
            pid=0x0017,
            serial_number=None,
            description="Uniden Scanner",
        )
        device_info.connection_status = "connected"
        return RuntimeState(
            config=config,
            transport=StubTransport(),
            scheduler=StubScheduler(),
            driver=StubDriver(),
            state_store=StateStore(persistence=None),
            ws_manager=ws_manager,
            device_info=device_info,
            session_id="test-session",
        )

    def test_uses_idle_interval_when_no_subscribers(self) -> None:
        runtime = self._runtime(WebSocketManager(WebSocketConfig()))
        self.assertEqual(_select_poll_interval(runtime), 1.0)

    def test_uses_fast_interval_when_state_subscriber_present(self) -> None:
        ws_manager = WebSocketManager(WebSocketConfig())
        # Simulate a client subscribed only to the "state" topic.
        ws_manager._connections.add("client-a")  # type: ignore[arg-type]
        ws_manager._topics["client-a"] = {"state"}  # type: ignore[index]
        runtime = self._runtime(ws_manager)
        self.assertAlmostEqual(_select_poll_interval(runtime), 0.1)

    def test_unfiltered_subscriber_counts_as_state_subscriber(self) -> None:
        # Default-connected clients (topics=None) get all messages,
        # including state, so they should keep the daemon at fast rate.
        ws_manager = WebSocketManager(WebSocketConfig())
        ws_manager._connections.add("client-b")  # type: ignore[arg-type]
        ws_manager._topics["client-b"] = None  # type: ignore[index]
        runtime = self._runtime(ws_manager)
        self.assertAlmostEqual(_select_poll_interval(runtime), 0.1)

    def test_non_state_subscriber_does_not_keep_fast_rate(self) -> None:
        ws_manager = WebSocketManager(WebSocketConfig())
        ws_manager._connections.add("client-c")  # type: ignore[arg-type]
        ws_manager._topics["client-c"] = {"events"}  # type: ignore[index]
        runtime = self._runtime(ws_manager)
        self.assertEqual(_select_poll_interval(runtime), 1.0)

    def test_disconnected_uses_backoff_multiplier(self) -> None:
        runtime = self._runtime(WebSocketManager(WebSocketConfig()))
        runtime.device_info.connection_status = "disconnected"
        # Disconnected backoff is sts_interval * 5 regardless of idle setting.
        self.assertAlmostEqual(_select_poll_interval(runtime), 0.5)

    def test_passive_state_subscriber_does_not_force_fast_rate(self) -> None:
        # Regression for the v1.3.0 kiosk case: a WS client subscribed to
        # "state" with live=false should NOT pin the daemon at fast rate.
        ws_manager = WebSocketManager(WebSocketConfig())
        ws_manager._connections.add("kiosk")  # type: ignore[arg-type]
        ws_manager._topics["kiosk"] = {"state"}  # type: ignore[index]
        ws_manager._live["kiosk"] = False  # type: ignore[index]
        runtime = self._runtime(ws_manager)
        self.assertEqual(_select_poll_interval(runtime), 1.0)

    def test_mixed_live_and_passive_uses_fast_rate(self) -> None:
        # If any state subscriber is live, the daemon stays fast.
        ws_manager = WebSocketManager(WebSocketConfig())
        ws_manager._connections.update(["kiosk", "browser"])  # type: ignore[arg-type]
        ws_manager._topics["kiosk"] = {"state"}  # type: ignore[index]
        ws_manager._live["kiosk"] = False  # type: ignore[index]
        ws_manager._topics["browser"] = {"state"}  # type: ignore[index]
        ws_manager._live["browser"] = True  # type: ignore[index]
        runtime = self._runtime(ws_manager)
        self.assertAlmostEqual(_select_poll_interval(runtime), 0.1)


class WebSocketSubscribeLiveFlagTests(unittest.TestCase):
    def test_subscribe_sets_live_flag(self) -> None:
        ws_manager = WebSocketManager(WebSocketConfig())
        sentinel = object()
        ws_manager._connections.add(sentinel)  # type: ignore[arg-type]
        ws_manager._topics[sentinel] = None  # type: ignore[index]
        ws_manager._live[sentinel] = True  # type: ignore[index]

        # Simulate the subscribe-message branch of handle_messages.
        data = {"type": "subscribe", "topics": ["state"], "live": False}
        topics = data.get("topics", [])
        if isinstance(topics, list):
            ws_manager._topics[sentinel] = set(topics)  # type: ignore[index]
        if "live" in data:
            ws_manager._live[sentinel] = bool(data.get("live"))  # type: ignore[index]

        self.assertFalse(ws_manager.has_live_subscribers_for("state"))
        self.assertTrue(ws_manager.has_subscribers_for("state"))

    def test_subscribe_without_live_field_keeps_default(self) -> None:
        # Backward compat: clients that don't send `live` keep the
        # pre-1.4 behavior (forcing fast rate).
        ws_manager = WebSocketManager(WebSocketConfig())
        sentinel = object()
        ws_manager._connections.add(sentinel)  # type: ignore[arg-type]
        ws_manager._topics[sentinel] = None  # type: ignore[index]
        ws_manager._live[sentinel] = True  # type: ignore[index]

        data = {"type": "subscribe", "topics": ["state"]}
        topics = data.get("topics", [])
        if isinstance(topics, list):
            ws_manager._topics[sentinel] = set(topics)  # type: ignore[index]
        if "live" in data:
            ws_manager._live[sentinel] = bool(data.get("live"))  # type: ignore[index]

        self.assertTrue(ws_manager.has_live_subscribers_for("state"))


if __name__ == "__main__":
    unittest.main()
