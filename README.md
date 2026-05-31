# 家声 HomeSound

一个面向中文用户的本地婴儿监听 / 房间声音监听项目。

HomeSound 可以把家里的 RTSP 网络摄像头变成一个只听声音的网页监听器：摄像头负责收音，家里的小服务器负责拉流、转码和混音，手机浏览器负责播放。整个过程优先在局域网内完成，不依赖厂商云服务。

## 适合谁

- 家里有婴儿、儿童、老人或需要照看的房间，希望用手机持续听到房间声音。
- 已经有支持 RTSP 的网络摄像头，想把它当作“声音监听器”使用。
- 不想把儿童房、卧室等私密空间的音频交给厂商云服务。
- 希望一个手机网页就能监听多个房间，并看到每个摄像头是否在线。
- 愿意在 NAS、迷你主机、树莓派、旧电脑或家庭服务器上跑一个小服务。

## 当前能力

- 多个 RTSP 摄像头音频输入。
- 多路音频混合成一路浏览器音频流。
- 网页端播放 MP3 音频流。
- 首页显示摄像头在线/离线、最近音频时间、重连次数和错误信息。
- `probe` 命令检测摄像头是否有音频轨道。
- `/health` 和 `/status` 状态接口。
- 日志和状态接口中的 RTSP 地址脱敏。

## 工作原理

```text
儿童房摄像头 A ─┐
儿童房摄像头 B ─┼─> HomeSound 服务端 ──> 网页播放器 ──> 手机浏览器
儿童房摄像头 C ─┘
```

服务端会为每个摄像头启动一个读取任务：

1. 使用 `ffmpeg` 打开摄像头的 RTSP 地址。
2. 只取音频，不处理视频。
3. 把音频转成统一的单声道 PCM 数据。
4. 写入每个摄像头自己的短缓冲区。
5. 浏览器访问页面时，首页自动读取 `/status` 显示摄像头状态。
6. 浏览器播放 `/stream.mp3` 时，服务端把多路声音混合后编码成 MP3 输出。

## 可以接入什么摄像头

原则上需要满足三个条件：

- 摄像头支持 RTSP。
- RTSP 流里有音频轨道。
- 运行 HomeSound 的机器能在局域网里访问摄像头 IP 和端口。

常见可尝试的设备类型：支持 RTSP 的家用网络摄像头、支持 ONVIF/RTSP 的安防摄像头、支持 RTSP 输出的 NVR 通道。

详细接入方法见 [摄像头接入指南](docs/camera-setup.md)。

## 快速开始

### 1. 安装依赖

需要 Python 3.10+ 和 `ffmpeg` / `ffprobe`。

```bash
python --version
ffmpeg -version
ffprobe -version
```

### 2. 检测摄像头是否能接入

先用 `probe` 检查 RTSP 地址里是否有音频轨道：

```bash
python src/homesound.py probe "rtsp://user:password@192.168.1.31:554/stream1"
```

如果看到类似输出，说明可以继续配置：

```text
视频轨道: 1
音频轨道: 1
  - aac 8000Hz 1ch
结论: 发现音频轨道，可以尝试接入 HomeSound。
```

### 3. 准备配置文件

```bash
cp config.example.yaml config.yaml
```

Windows PowerShell：

```powershell
Copy-Item config.example.yaml config.yaml
```

编辑 `config.yaml`：

```yaml
server:
  host: 0.0.0.0
  port: 8080

audio:
  sample_rate: 48000
  channels: 1
  buffer_seconds: 8
  output_format: mp3

cameras:
  - name: 儿童房 A
    url: rtsp://user:password@192.168.1.31:554/stream1
    volume: 1.0
  - name: 儿童房 B
    url: rtsp://user:password@192.168.1.32:554/stream1
    volume: 0.8
```

配置详解见 [配置说明](docs/configuration.md)。

### 4. 启动服务

兼容旧写法：

```bash
python src/homesound.py --config config.yaml
```

也可以显式使用 `serve`：

```bash
python src/homesound.py serve --config config.yaml
```

看到类似输出说明服务已经启动：

```text
已启动摄像头音频读取: 儿童房 A (rtsp://user:***@192.168.1.31:554/stream1)
HomeSound 已启动: http://0.0.0.0:8080
状态接口: http://0.0.0.0:8080/status
```

### 5. 手机打开网页

手机和服务器连接同一个 Wi-Fi 后，打开服务器的局域网 IP：

```text
http://192.168.1.20:8080
```

页面会显示播放按钮和摄像头状态。`0.0.0.0` 只是服务监听地址，不是手机要访问的地址。

## 服务接口

- `/`：网页播放器和摄像头状态面板。
- `/stream.mp3`：浏览器实际播放的音频流。
- `/health`：健康检查，正常时返回 `ok`。
- `/status`：JSON 状态接口，包含摄像头在线状态、最近收到音频时间、重连次数和脱敏后的 RTSP 地址。

示例：

```bash
curl http://127.0.0.1:8080/status
```

## 安全提醒

当前原型没有账号、密码、HTTPS 和访问控制。请只在可信网络中使用，不要直接暴露到公网。

真实的 `config.yaml` 可能包含摄像头账号密码，已经被 `.gitignore` 排除。日志和 `/status` 会尽量脱敏 RTSP 地址，但仍然不要公开你的真实网络信息。

## 文档

- [使用场景](docs/scenarios.md)
- [摄像头接入指南](docs/camera-setup.md)
- [配置说明](docs/configuration.md)
- [代码使用说明](docs/code-usage.md)
- [故障排查](docs/troubleshooting.md)
- [架构说明](docs/architecture.md)
- [部署说明](docs/deployment.md)
- [安全说明](SECURITY.md)

## 路线图

- 支持每个房间单独静音和音量调节。
- 支持 WebM/Opus 低延迟播放。
- 增加简单访问令牌。
- 增加 Docker 部署方式。
- 增加 Prometheus 指标。
- 支持更多输入音频格式和自动重采样。

## 许可证

MIT License
