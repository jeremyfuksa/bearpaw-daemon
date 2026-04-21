from __future__ import annotations

import os

try:
    import tomllib
except ImportError:  # pragma: no cover
    import tomli as tomllib
from typing import List, Optional

import yaml
from pydantic import BaseModel, Field


class DeviceConfig(BaseModel):
    port: Optional[str] = None
    auto_detect: bool = True
    transport: str = "auto"
    usb_vid: int = 0x1965
    usb_pid: int = 0x0017
    usb_serial: Optional[str] = None


class ApiConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8000
    cors_origins: List[str] = Field(
        default_factory=lambda: [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ]
    )


class PollingConfig(BaseModel):
    sts_interval: float = 0.1
    reconnect_backoff: List[float] = Field(default_factory=lambda: [1, 2, 5, 10, 30])


class StateConfig(BaseModel):
    persistence: str = "sqlite"
    db_path: str = "./scanner.db"


class TextFileExporterConfig(BaseModel):
    enabled: bool = False
    path: str = "./now_scanning.txt"
    template: str = "{frequency} MHz {modulation} - {alpha_tag}"
    update_on: List[str] = Field(default_factory=lambda: ["frequency", "squelch_open"])
    blank_on_squelch_closed: bool = False


class JsonStreamExporterConfig(BaseModel):
    enabled: bool = False
    path: str = "./events.jsonl"
    max_bytes: int = 10 * 1024 * 1024
    rotate_daily: bool = True


class MqttExporterConfig(BaseModel):
    enabled: bool = False
    host: str = "127.0.0.1"
    port: int = 1883
    topic_prefix: str = "scanner"
    qos: int = 0
    retain: bool = False


class ExporterConfig(BaseModel):
    text_file: TextFileExporterConfig = Field(default_factory=TextFileExporterConfig)
    json_stream: JsonStreamExporterConfig = Field(
        default_factory=JsonStreamExporterConfig
    )
    mqtt: MqttExporterConfig = Field(default_factory=MqttExporterConfig)


class AnalyticsConfig(BaseModel):
    enabled: bool = True
    db_path: str = "./analytics.db"
    retention_days: int = 30
    cleanup_interval_hours: int = 24
    min_hit_duration: float = 1.0


class WebSocketConfig(BaseModel):
    ping_interval: float = 30.0
    ping_timeout: float = 10.0


class LoggingConfig(BaseModel):
    level: str = "INFO"
    format: str = "%(levelname)s %(message)s"


class RecordingConfig(BaseModel):
    enabled: bool = False
    output_path: str = "./recordings"
    format: str = "wav"
    sample_rate: int = 44100
    channels: int = 1
    buffer_seconds: int = 30
    auto_record_on_squelch: bool = False
    audio_device_index: Optional[int] = None


class AudioConfig(BaseModel):
    """Live HLS audio streaming from a scanner's headphone jack.

    Requires a scanner connected to the host's audio input (e.g. via a USB
    audio adapter on a Raspberry Pi) and a system `ffmpeg` binary. Disabled
    by default so existing deployments are unaffected.
    """

    enabled: bool = False
    # ffmpeg input format. "alsa" on Linux (including Raspberry Pi),
    # "avfoundation" on macOS for local dev, "dshow" on Windows.
    input_format: str = "alsa"
    # ALSA device (e.g. "hw:1,0"), AVFoundation index (":1"), or dshow name.
    device: str = "hw:1,0"
    # Mono AAC bitrate in kbps. Narrowband voice is fine at 32-64.
    bitrate: int = 64
    sample_rate: int = 22050
    # HLS tuning.
    segment_duration: int = 2  # seconds per segment
    buffer_segments: int = 15  # rolling window size
    # Directory ffmpeg writes playlist + segments to. Recommended to mount
    # as tmpfs on Pi to avoid SD card wear.
    output_dir: str = "/tmp/bearpaw-hls"
    # Path to the ffmpeg binary. Auto-discovered via PATH when None.
    ffmpeg_path: Optional[str] = None


class AppConfig(BaseModel):
    device: DeviceConfig = Field(default_factory=DeviceConfig)
    api: ApiConfig = Field(default_factory=ApiConfig)
    polling: PollingConfig = Field(default_factory=PollingConfig)
    state: StateConfig = Field(default_factory=StateConfig)
    exporters: ExporterConfig = Field(default_factory=ExporterConfig)
    analytics: AnalyticsConfig = Field(default_factory=AnalyticsConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    websocket: WebSocketConfig = Field(default_factory=WebSocketConfig)
    audio: AudioConfig = Field(default_factory=AudioConfig)


def load_config(path: Optional[str]) -> AppConfig:
    if not path:
        return AppConfig()
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    if path.endswith(".toml"):
        with open(path, "rb") as handle:
            data = tomllib.load(handle)
    else:
        with open(path, "r", encoding="ascii") as handle:
            data = yaml.safe_load(handle) or {}
    return AppConfig(**data)
