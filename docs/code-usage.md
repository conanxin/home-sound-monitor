# 代码使用说明

HomeSound 当前是一个 Python 原型，代码入口是：

```text
src/homesound.py
```

它尽量只依赖 Python 标准库，把音频解码和编码交给系统里的 `ffmpeg` 命令。

## 运行入口

```bash
python src/homesound.py --config config.yaml
```

参数：

- `--config`：配置文件路径，默认是 `config.yaml`。

如果配置文件不存在，程序会提示先复制 `config.example.yaml`。

## 运行后会发生什么

1. 读取配置文件。
2. 为每个摄像头创建一个 `Camera` 对象。
3. 为每个摄像头启动一个 `CameraWorker` 后台线程。
4. 每个 `CameraWorker` 调用 ffmpeg 拉取 RTSP 音频。
5. ffmpeg 把输入音频转换成 `s16le` 单声道 PCM。
6. PCM 数据写入该摄像头的 `PcmRingBuffer`。
7. HTTP 服务启动，提供网页和音频流。
8. 浏览器访问 `/stream.mp3` 时，`Mixer` 读取各摄像头最新声音并混音。
9. 服务端再调用 ffmpeg 把混音后的 PCM 编码成 MP3 输出给浏览器。

## 核心类和函数

### load_simple_yaml()

读取 `config.yaml`。这是一个小型解析器，只支持项目当前示例配置那样的简单 YAML。

未来如果配置需要更复杂，可以替换成 PyYAML：

```python
import yaml
config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
```

### PcmRingBuffer

保存某个摄像头最近几秒的 PCM 音频块。

它不是录音文件，也不会保存到磁盘。它的作用是：

- 摄像头持续写入最新声音。
- 播放端随时读取最近声音。
- 数据太旧时自动被新数据覆盖。

### CameraWorker

每个摄像头一个后台线程。它会执行类似命令：

```bash
ffmpeg \
  -hide_banner \
  -loglevel warning \
  -rtsp_transport tcp \
  -i "rtsp://user:password@192.168.1.31:554/stream1" \
  -vn \
  -ac 1 \
  -ar 48000 \
  -f s16le \
  pipe:1
```

含义：

- `-rtsp_transport tcp`：用 TCP 拉 RTSP，家庭网络里通常更稳定。
- `-i`：摄像头地址。
- `-vn`：不要视频。
- `-ac 1`：转成单声道。
- `-ar 48000`：转成 48kHz。
- `-f s16le`：输出 16-bit little-endian PCM。
- `pipe:1`：输出到 stdout，让 Python 读取。

如果摄像头断开，线程会等待 5 秒后重试。

### Mixer

混音器。它从每个摄像头的缓冲区读取最新声音块，然后用 `audioop.add()` 把它们相加。

注意：当前混音比较直接，没有 limiter。如果多个房间同时很响，可能出现削波或失真。可以先通过 `volume` 降低每路音量。

### create_handler()

创建 HTTP 请求处理器，提供三个入口：

- `/` 和 `/index.html`：返回网页播放器。
- `/stream.mp3`：返回连续 MP3 音频流。
- `/health`：返回 `ok`，用于检查服务是否活着。

## 调试方法

### 先单独测试摄像头

```bash
ffmpeg -rtsp_transport tcp -i "你的 RTSP 地址"
```

确认输出里有 `Audio:`。

### 测试服务是否启动

```bash
curl http://127.0.0.1:8080/health
```

正常会返回：

```text
ok
```

### 测试音频流

可以在浏览器里直接打开：

```text
http://127.0.0.1:8080/stream.mp3
```

也可以用播放器打开这个地址。

### 查看日志

服务启动后会输出每个摄像头读取状态。如果某个摄像头失败，会看到类似：

```text
[儿童房 A] 音频读取失败，5 秒后重试: ...
```

这通常意味着 RTSP 地址、账号密码、网络或摄像头状态有问题。

## 二次开发建议

如果你想继续改代码，推荐按这个顺序：

1. 先增加更完整的配置解析，例如 PyYAML。
2. 增加每路摄像头状态页。
3. 增加 limiter，避免混音爆音。
4. 增加 WebM/Opus 输出，降低浏览器播放延迟。
5. 增加访问令牌，避免局域网里任何人都能打开。
6. 增加 Dockerfile 和 systemd 服务文件。

## 当前原型的边界

- 没有账号认证。
- 没有 HTTPS。
- 没有录像保存。
- 没有视频播放。
- 没有摄像头自动发现。
- 没有完整 YAML 解析。
- 没有音频 limiter。

这些不是不能做，而是当前版本先把最核心的链路跑通：摄像头音频进来，混合后从网页听到。
