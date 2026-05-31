#!/usr/bin/env python3
"""
HomeSound local room audio monitor.

The prototype stays dependency-light: Python handles configuration, HTTP, state,
and mixing while ffmpeg/ffprobe handle media probing, decoding, and encoding.
"""

from __future__ import annotations

import argparse
import audioop
import json
import signal
import subprocess
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit


DEFAULT_CONFIG = {
    "server": {"host": "0.0.0.0", "port": 8080},
    "audio": {
        "sample_rate": 48000,
        "channels": 1,
        "buffer_seconds": 8,
        "output_format": "mp3",
    },
    "cameras": [],
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def mask_url(url: str) -> str:
    """Hide credentials before printing or returning camera URLs."""

    parts = urlsplit(url)
    if not parts.username and not parts.password:
        return url

    host = parts.hostname or ""
    if parts.port:
        host = f"{host}:{parts.port}"

    username = parts.username or "user"
    netloc = f"{username}:***@{host}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def parse_scalar(value: str) -> Any:
    value = value.strip()
    if value in ("true", "false"):
        return value == "true"
    try:
        if "." in value:
            return float(value)
        return int(value)
    except ValueError:
        return value.strip("'\"")


def load_simple_yaml(path: Path) -> dict[str, Any]:
    """Load the small config shape used by config.example.yaml.

    This is not a general YAML parser. It exists so the prototype can run with
    the Python standard library only. Use PyYAML later if the config grows.
    """

    config: dict[str, Any] = {"server": {}, "audio": {}, "cameras": []}
    section: str | None = None
    current_camera: dict[str, Any] | None = None

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].rstrip()
        if not line:
            continue

        if not line.startswith(" "):
            key = line.rstrip(":")
            section = key
            current_camera = None
            if key not in config:
                config[key] = [] if key == "cameras" else {}
            continue

        stripped = line.strip()
        if section == "cameras" and stripped.startswith("- "):
            current_camera = {}
            config["cameras"].append(current_camera)
            stripped = stripped[2:].strip()
            if not stripped:
                continue

        if ":" not in stripped:
            continue

        key, value = stripped.split(":", 1)
        target: dict[str, Any]
        if section == "cameras":
            if current_camera is None:
                current_camera = {}
                config["cameras"].append(current_camera)
            target = current_camera
        else:
            target = config.setdefault(section or "", {})
        target[key.strip()] = parse_scalar(value)

    merged = DEFAULT_CONFIG.copy()
    merged["server"] = {**DEFAULT_CONFIG["server"], **config.get("server", {})}
    merged["audio"] = {**DEFAULT_CONFIG["audio"], **config.get("audio", {})}
    merged["cameras"] = config.get("cameras", [])
    return merged


def validate_config(config: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    cameras = config.get("cameras", [])
    if not isinstance(cameras, list) or not cameras:
        errors.append("cameras 中至少需要一个摄像头。")

    for index, item in enumerate(cameras):
        prefix = f"cameras[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{prefix} 必须是一个对象。")
            continue
        if not item.get("url"):
            errors.append(f"{prefix}.url 不能为空。")
        try:
            float(item.get("volume", 1.0))
        except (TypeError, ValueError):
            errors.append(f"{prefix}.volume 必须是数字。")

    try:
        port = int(config["server"]["port"])
        if not 1 <= port <= 65535:
            errors.append("server.port 必须在 1 到 65535 之间。")
    except (KeyError, TypeError, ValueError):
        errors.append("server.port 必须是端口数字。")

    try:
        sample_rate = int(config["audio"]["sample_rate"])
        if sample_rate <= 0:
            errors.append("audio.sample_rate 必须大于 0。")
    except (KeyError, TypeError, ValueError):
        errors.append("audio.sample_rate 必须是数字。")

    if int(config["audio"].get("channels", 1)) != 1:
        errors.append("当前原型只支持 audio.channels: 1。")

    return errors


class PcmRingBuffer:
    def __init__(self, max_chunks: int) -> None:
        self._chunks: deque[bytes] = deque(maxlen=max_chunks)
        self._condition = threading.Condition()

    def write(self, chunk: bytes) -> None:
        with self._condition:
            self._chunks.append(chunk)
            self._condition.notify_all()

    def latest(self, timeout: float = 1.0) -> bytes | None:
        with self._condition:
            if not self._chunks:
                self._condition.wait(timeout)
            if not self._chunks:
                return None
            return self._chunks[-1]


@dataclass
class CameraState:
    online: bool = False
    last_audio_at: str | None = None
    last_error: str | None = None
    restarts: int = 0
    bytes_read: int = 0
    started_at: str = field(default_factory=utc_now)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def mark_audio(self, size: int) -> None:
        with self._lock:
            self.online = True
            self.last_audio_at = utc_now()
            self.last_error = None
            self.bytes_read += size

    def mark_error(self, message: str) -> None:
        with self._lock:
            self.online = False
            self.last_error = message
            self.restarts += 1

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "online": self.online,
                "last_audio_at": self.last_audio_at,
                "last_error": self.last_error,
                "restarts": self.restarts,
                "bytes_read": self.bytes_read,
                "started_at": self.started_at,
            }


@dataclass
class Camera:
    name: str
    url: str
    volume: float
    buffer: PcmRingBuffer
    state: CameraState = field(default_factory=CameraState)

    def public_snapshot(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "url": mask_url(self.url),
            "volume": self.volume,
            **self.state.snapshot(),
        }


class CameraWorker(threading.Thread):
    def __init__(self, camera: Camera, sample_rate: int, chunk_bytes: int) -> None:
        super().__init__(name=f"camera:{camera.name}", daemon=True)
        self.camera = camera
        self.sample_rate = sample_rate
        self.chunk_bytes = chunk_bytes
        self.stop_event = threading.Event()

    def run(self) -> None:
        while not self.stop_event.is_set():
            try:
                self._run_ffmpeg()
                self.camera.state.mark_error("ffmpeg exited without audio")
            except Exception as exc:
                self.camera.state.mark_error(str(exc))
                print(f"[{self.camera.name}] 音频读取失败，5 秒后重试: {exc}", file=sys.stderr)
            time.sleep(5)

    def _run_ffmpeg(self) -> None:
        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "warning",
            "-rtsp_transport",
            "tcp",
            "-i",
            self.camera.url,
            "-vn",
            "-ac",
            "1",
            "-ar",
            str(self.sample_rate),
            "-f",
            "s16le",
            "pipe:1",
        ]
        print(f"[{self.camera.name}] 正在连接: {mask_url(self.camera.url)}")
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        assert proc.stdout is not None
        while not self.stop_event.is_set():
            chunk = proc.stdout.read(self.chunk_bytes)
            if not chunk:
                break
            if self.camera.volume != 1.0:
                chunk = audioop.mul(chunk, 2, self.camera.volume)
            self.camera.buffer.write(chunk)
            self.camera.state.mark_audio(len(chunk))
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()


class Mixer:
    def __init__(self, cameras: list[Camera], chunk_bytes: int) -> None:
        self.cameras = cameras
        self.chunk_bytes = chunk_bytes

    def read_chunk(self) -> bytes:
        mixed: bytes | None = None
        for camera in self.cameras:
            chunk = camera.buffer.latest()
            if chunk is None:
                chunk = b"\x00" * self.chunk_bytes
            if len(chunk) < self.chunk_bytes:
                chunk = chunk.ljust(self.chunk_bytes, b"\x00")
            if mixed is None:
                mixed = chunk
            else:
                mixed = audioop.add(mixed, chunk, 2)
        return mixed or (b"\x00" * self.chunk_bytes)


def status_payload(cameras: list[Camera], started_at: str, sample_rate: int) -> dict[str, Any]:
    return {
        "service": "homesound",
        "started_at": started_at,
        "now": utc_now(),
        "sample_rate": sample_rate,
        "cameras": [camera.public_snapshot() for camera in cameras],
    }


def create_handler(
    index_html: bytes,
    mixer: Mixer,
    cameras: list[Camera],
    sample_rate: int,
    started_at: str,
):
    class HomeSoundHandler(BaseHTTPRequestHandler):
        server_version = "HomeSound/0.2"

        def do_GET(self) -> None:
            path = self.path.split("?", 1)[0]
            if path in ("/", "/index.html"):
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(index_html)))
                self.end_headers()
                self.wfile.write(index_html)
                return

            if path == "/stream.mp3":
                self.stream_mp3()
                return

            if path == "/health":
                body = b"ok\n"
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            if path == "/status":
                body = json.dumps(
                    status_payload(cameras, started_at, sample_rate),
                    ensure_ascii=False,
                    indent=2,
                ).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            self.send_error(404, "Not Found")

        def stream_mp3(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "audio/mpeg")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()

            cmd = [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "s16le",
                "-ac",
                "1",
                "-ar",
                str(sample_rate),
                "-i",
                "pipe:0",
                "-f",
                "mp3",
                "-codec:a",
                "libmp3lame",
                "-b:a",
                "64k",
                "pipe:1",
            ]
            proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE)
            assert proc.stdin is not None
            assert proc.stdout is not None

            def feed() -> None:
                try:
                    while True:
                        proc.stdin.write(mixer.read_chunk())
                        proc.stdin.flush()
                except (BrokenPipeError, OSError):
                    pass

            feeder = threading.Thread(target=feed, daemon=True)
            feeder.start()
            try:
                while True:
                    data = proc.stdout.read(4096)
                    if not data:
                        break
                    self.wfile.write(data)
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                proc.terminate()

        def log_message(self, fmt: str, *args: Any) -> None:
            print("[%s] %s" % (self.log_date_time_string(), fmt % args))

    return HomeSoundHandler


def probe_camera(url: str, timeout: int) -> int:
    masked = mask_url(url)
    print(f"正在检测摄像头: {masked}")
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-rtsp_transport",
        "tcp",
        "-show_streams",
        "-of",
        "json",
        url,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        print("找不到 ffprobe。请确认 ffmpeg/ffprobe 已安装并在 PATH 中。", file=sys.stderr)
        return 2
    except subprocess.TimeoutExpired:
        print(f"连接超时: {masked}", file=sys.stderr)
        return 1

    if result.returncode != 0:
        print("检测失败。ffprobe 输出：", file=sys.stderr)
        print(result.stderr.strip() or result.stdout.strip(), file=sys.stderr)
        return 1

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        print("检测失败：ffprobe 返回了无法解析的结果。", file=sys.stderr)
        return 1

    streams = payload.get("streams", [])
    audio_streams = [stream for stream in streams if stream.get("codec_type") == "audio"]
    video_streams = [stream for stream in streams if stream.get("codec_type") == "video"]

    print(f"视频轨道: {len(video_streams)}")
    for stream in video_streams:
        codec = stream.get("codec_name", "unknown")
        width = stream.get("width", "?")
        height = stream.get("height", "?")
        print(f"  - {codec} {width}x{height}")

    print(f"音频轨道: {len(audio_streams)}")
    for stream in audio_streams:
        codec = stream.get("codec_name", "unknown")
        sample_rate = stream.get("sample_rate", "?")
        channels = stream.get("channels", "?")
        print(f"  - {codec} {sample_rate}Hz {channels}ch")

    if not audio_streams:
        print("结论: 未发现音频轨道。请检查摄像头是否开启麦克风，或换一个 RTSP 码流地址。")
        return 1

    print("结论: 发现音频轨道，可以尝试接入 HomeSound。")
    return 0


def serve(config_path: Path) -> int:
    if not config_path.exists():
        print(f"找不到配置文件: {config_path}", file=sys.stderr)
        print("请先复制 config.example.yaml 为 config.yaml 并填写摄像头地址。", file=sys.stderr)
        return 2

    config = load_simple_yaml(config_path)
    errors = validate_config(config)
    if errors:
        print("配置文件有问题：", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 2

    sample_rate = int(config["audio"]["sample_rate"])
    buffer_seconds = int(config["audio"]["buffer_seconds"])
    chunk_ms = 100
    chunk_bytes = sample_rate * 2 * chunk_ms // 1000
    max_chunks = max(1, buffer_seconds * 1000 // chunk_ms)

    cameras = [
        Camera(
            name=str(item.get("name", f"房间 {idx + 1}")),
            url=str(item["url"]),
            volume=float(item.get("volume", 1.0)),
            buffer=PcmRingBuffer(max_chunks),
        )
        for idx, item in enumerate(config["cameras"])
    ]

    for camera in cameras:
        CameraWorker(camera, sample_rate, chunk_bytes).start()
        print(f"已启动摄像头音频读取: {camera.name} ({mask_url(camera.url)})")

    index_path = Path(__file__).parent / "web" / "index.html"
    index_html = index_path.read_bytes()
    mixer = Mixer(cameras, chunk_bytes)

    host = str(config["server"]["host"])
    port = int(config["server"]["port"])
    started_at = utc_now()
    handler = create_handler(index_html, mixer, cameras, sample_rate, started_at)
    httpd = ThreadingHTTPServer((host, port), handler)

    def shutdown(signum: int, frame: Any) -> None:
        print("正在停止 HomeSound...")
        httpd.shutdown()

    signal.signal(signal.SIGINT, shutdown)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, shutdown)

    print(f"HomeSound 已启动: http://{host}:{port}")
    print(f"状态接口: http://{host}:{port}/status")
    httpd.serve_forever()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="HomeSound 本地房间声音监听器")
    subparsers = parser.add_subparsers(dest="command")

    serve_parser = subparsers.add_parser("serve", help="启动 HomeSound 服务")
    serve_parser.add_argument("--config", default="config.yaml", help="配置文件路径")

    probe_parser = subparsers.add_parser("probe", help="检测 RTSP 摄像头是否有音频轨道")
    probe_parser.add_argument("url", help="摄像头 RTSP 地址")
    probe_parser.add_argument("--timeout", type=int, default=15, help="检测超时时间，单位秒")

    parser.add_argument("--config", default="config.yaml", help="配置文件路径，兼容旧启动方式")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "probe":
        return probe_camera(args.url, args.timeout)

    config_path = Path(args.config)
    return serve(config_path)


if __name__ == "__main__":
    raise SystemExit(main())
