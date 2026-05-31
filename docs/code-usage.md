# 代码使用说明

HomeSound 当前是一个 Python 原型，代码入口是：

```text
src/homesound.py
```

它尽量只依赖 Python 标准库，把音频解码、探测和编码交给系统里的 `ffmpeg` / `ffprobe` 命令。

## 命令入口

### 启动服务

兼容旧写法：

```bash
python src/homesound.py --config config.yaml
```

显式写法：

```bash
python src/homesound.py serve --config config.yaml
```

### 检测摄像头

```bash
python src/homesound.py probe "rtsp://user:password@192.168.1.31:554/stream1"
```

可设置超时时间：

```bash
python src/homesound.py probe "rtsp://user:password@192.168.1.31:554/stream1" --timeout 20
```

`probe` 会调用 `ffprobe`，列出视频轨道和音频轨道。如果没有音频轨道，HomeSound 即使能连接摄像头，也无法作为声音监听器使用。

## 运行后会发生什么

1. 读取并校验配置文件。
2. 为每个摄像头创建一个 `Camera` 对象和 `CameraState` 状态对象。
3. 为每个摄像头启动一个 `CameraWorker` 后台线程。
4. 每个 `CameraWorker` 调用 ffmpeg 拉取 RTSP 音频。
5. ffmpeg 把输入音频转换成 `s16le` 单声道 PCM。
6. PCM 数据写入该摄像头的 `PcmRingBuffer`。
7. 摄像头状态会记录在线状态、最近收到音频时间、重连次数和读取字节数。
8. HTTP 服务启动，提供网页、音频流、健康检查和状态接口。
9. 浏览器访问 `/stream.mp3` 时，`Mixer` 读取各摄像头最新声音并混音。
10. 服务端再调用 ffmpeg 把混音后的 PCM 编码成 MP3 输出给浏览器。

## HTTP 接口

### `/`

网页播放器。

### `/stream.mp3`

连续 MP3 音频流。浏览器里的 `<audio>` 元素会播放这个地址。

### `/health`

健康检查。正常返回：

```text
ok
```

### `/status`

状态接口。返回 JSON，包含服务启动时间、采样率和每个摄像头状态。

示例字段：

```json
{
  "service": "homesound",
  "sample_rate": 48000,
  "cameras": [
    {
      "name": "儿童房 A",
      "url": "rtsp://user:***@192.168.1.31:554/stream1",
      "volume": 1.0,
      "online": true,
      "last_audio_at": "2026-05-31T12:00:00+00:00",
      "last_error": null,
      "restarts": 0,
      "bytes_read": 192000
    }
  ]
}
```

注意：`url` 会脱敏，不会返回明文密码。

## 核心类和函数

### `mask_url()`

把 RTSP 地址中的密码隐藏掉，用于日志和 `/status`。

```text
rtsp://user:password@192.168.1.31:554/stream1
```

会变成：

```text
rtsp://user:***@192.168.1.31:554/stream1
```

### `validate_config()`

做基础配置校验。它会检查：

- 是否至少配置一个摄像头。
- 每个摄像头是否有 URL。
- `volume` 是否是数字。
- 端口是否在合法范围内。
- 当前是否保持 `audio.channels: 1`。

### `CameraState`

记录摄像头运行状态：

- `online`
- `last_audio_at`
- `last_error`
- `restarts`
- `bytes_read`
- `started_at`

这些状态会被 `/status` 使用。

### `CameraWorker`

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

如果摄像头断开，线程会等待 5 秒后重试，并更新 `CameraState`。

### `Mixer`

从每个摄像头的缓冲区读取最新声音块，然后用 `audioop.add()` 把它们相加。

当前混音没有 limiter。如果多个房间同时很响，可能出现削波或失真。可以先通过 `volume` 降低每路音量。

### `probe_camera()`

调用 `ffprobe` 检测 RTSP 地址是否能访问，以及里面是否有音频轨道。这是用户排障的第一入口。

## 调试方法

### 检测摄像头

```bash
python src/homesound.py probe "你的 RTSP 地址"
```

### 测试服务是否启动

```bash
curl http://127.0.0.1:8080/health
```

### 查看摄像头状态

```bash
curl http://127.0.0.1:8080/status
```

### 测试音频流

可以在浏览器或播放器里直接打开：

```text
http://127.0.0.1:8080/stream.mp3
```

## 二次开发建议

下一步适合继续做：

1. 首页展示 `/status` 中的摄像头状态。
2. 增加 Dockerfile 和 docker-compose 示例。
3. 增加 limiter，避免混音爆音。
4. 增加 WebM/Opus 输出，降低浏览器播放延迟。
5. 增加访问令牌，避免局域网里任何人都能打开。
6. 拆分模块并加入测试。
