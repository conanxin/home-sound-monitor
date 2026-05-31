#!/usr/bin/env python3
"""
HomeSound local room audio monitor.

This prototype keeps the implementation dependency-light. It relies on an
installed ffmpeg binary to pull RTSP audio, convert it to mono PCM, mix
camera streams, and encode the browser stream.
"""

from __future__ import annotations

import argparse
import audioop
import signal
import subprocess
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


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
class Camera:
    name: str
    url: str
    volume: float
    buffer: PcmRingBuffer


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
            except Exception as exc:
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
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        assert proc.stdout is not None
        while not self.stop_event.is_set():
            chunk = proc.stdout.read(self.chunk_bytes)
            if not chunk:
                break
            if self.camera.volume != 1.0:
                chunk = audioop.mul(chunk, 2, self.camera.volume)
            self.camera.buffer.write(chunk)
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


def create_handler(index_html: bytes, mixer: Mixer, sample_rate: int):
    class HomeSoundHandler(BaseHTTPRequestHandler):
        server_version = "HomeSound/0.1"

        def do_GET(self) -> None:
            if self.path in ("/", "/index.html"):
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(index_html)))
                self.end_headers()
                self.wfile.write(index_html)
                return

            if self.path == "/stream.mp3":
                self.stream_mp3()
                return

            if self.path == "/health":
                body = b"ok\n"
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
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


def main() -> int:
    parser = argparse.ArgumentParser(description="HomeSound 本地房间声音监听器")
    parser.add_argument("--config", default="config.yaml", help="配置文件路径")
    args = parser.parse_args()

    config_path = Path(args.config)
    if not config_path.exists():
        print(f"找不到配置文件: {config_path}", file=sys.stderr)
        print("请先复制 config.example.yaml 为 config.yaml 并填写摄像头地址。", file=sys.stderr)
        return 2

    config = load_simple_yaml(config_path)
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

    if not cameras:
        print("配置文件里没有摄像头。请在 cameras 中添加至少一个 RTSP 地址。", file=sys.stderr)
        return 2

    for camera in cameras:
        CameraWorker(camera, sample_rate, chunk_bytes).start()
        print(f"已启动摄像头音频读取: {camera.name}")

    index_path = Path(__file__).parent / "web" / "index.html"
    index_html = index_path.read_bytes()
    mixer = Mixer(cameras, chunk_bytes)

    host = str(config["server"]["host"])
    port = int(config["server"]["port"])
    handler = create_handler(index_html, mixer, sample_rate)
    httpd = ThreadingHTTPServer((host, port), handler)

    def shutdown(signum: int, frame: Any) -> None:
        print("正在停止 HomeSound...")
        httpd.shutdown()

    signal.signal(signal.SIGINT, shutdown)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, shutdown)

    print(f"HomeSound 已启动: http://{host}:{port}")
    httpd.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
