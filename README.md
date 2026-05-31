# 家声 HomeSound

一个面向中文用户的本地婴儿监听 / 房间声音监听项目。

HomeSound 可以把家里的 RTSP 网络摄像头变成一个只听声音的网页监听器：摄像头负责收音，家里的小服务器负责拉流、转码和混音，手机浏览器负责播放。整个过程优先在局域网内完成，不依赖厂商云服务。

## 这个项目适合谁

- 家里有婴儿、儿童、老人或需要照看的房间，希望用手机持续听到房间声音。
- 已经有支持 RTSP 的网络摄像头，想把它当作“声音监听器”使用。
- 不想把儿童房、卧室等私密空间的音频交给厂商云服务。
- 希望一个手机网页就能监听多个房间，而不是反复打开多个摄像头 App。
- 愿意在家里的 NAS、迷你主机、树莓派、旧电脑或家庭服务器上跑一个小服务。

如果你只想要一个商业 App、云端回放、账号体系、视频录像和远程推送提醒，这个项目现在还不是那个方向。HomeSound 的目标更简单：本地、可理解、可改造、声音优先。

## 一个典型场景

晚上两个孩子分别睡在两个房间，每个房间都有一个网络摄像头。你在客厅或卧室打开手机浏览器，访问家里服务器上的 HomeSound 页面，点“开始监听”。

此后，HomeSound 会把两个房间的麦克风声音混成一路音频。如果某个房间有哭声、咳嗽声、喊人声或明显动静，你可以马上听到。

## 工作原理

```text
儿童房摄像头 A ─┐
儿童房摄像头 B ─┼─> HomeSound 服务端 ──> /stream.mp3 ──> 手机浏览器
儿童房摄像头 C ─┘
```

服务端会为每个摄像头启动一个读取任务：

1. 使用 `ffmpeg` 打开摄像头的 RTSP 地址。
2. 只取音频，不处理视频。
3. 把音频转成统一的单声道 PCM 数据。
4. 写入每个摄像头自己的短缓冲区。
5. 当浏览器访问 `/stream.mp3` 时，把多路声音混合后编码成 MP3 输出。

当前原型优先兼容性，所以网页端直接播放 MP3。后续可以增加 WebM/Opus + MediaSource 的低延迟播放路径。

## 可以接入什么摄像头

原则上需要满足三个条件：

- 摄像头支持 RTSP。
- RTSP 流里有音频轨道。
- 运行 HomeSound 的机器能在局域网里访问摄像头 IP 和端口。

常见可尝试的设备类型：

- 支持 RTSP 的家用网络摄像头。
- 支持 ONVIF / RTSP 的安防摄像头。
- 支持 RTSP 输出的 NVR 或录像机通道。
- 能通过固件或设置打开 RTSP 的智能摄像头。

不适合直接接入的设备：

- 只能通过厂商 App 观看、没有 RTSP/ONVIF 开关的云摄像头。
- 只有视频没有麦克风或音频轨道的摄像头。
- 与服务器不在同一网络、且没有 VPN/内网穿透的摄像头。

详细接入方法见 [摄像头接入指南](docs/camera-setup.md)。

## 快速开始

### 1. 安装依赖

需要 Python 3.10+ 和 `ffmpeg`。

确认 Python：

```bash
python --version
```

确认 ffmpeg：

```bash
ffmpeg -version
```

如果 `ffmpeg -version` 找不到命令，请先安装 ffmpeg，并确保它在系统 PATH 中。

### 2. 找到摄像头 RTSP 地址

地址通常长这样：

```text
rtsp://用户名:密码@摄像头IP:554/stream1
```

不同品牌路径不一样。可以先用下面命令验证：

```bash
ffmpeg -rtsp_transport tcp -i "rtsp://user:password@192.168.1.31:554/stream1"
```

如果命令能看到 `Audio:` 相关输出，说明 HomeSound 有机会读取到声音。

### 3. 准备配置文件

复制示例配置：

```bash
cp config.example.yaml config.yaml
```

Windows PowerShell 可以用：

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

```bash
python src/homesound.py --config config.yaml
```

看到类似输出：

```text
已启动摄像头音频读取: 儿童房 A
已启动摄像头音频读取: 儿童房 B
HomeSound 已启动: http://0.0.0.0:8080
```

说明服务已经开始工作。

### 5. 手机打开网页

在运行 HomeSound 的机器上查看局域网 IP，例如 `192.168.1.20`。

手机和服务器连接同一个 Wi-Fi 后，打开：

```text
http://192.168.1.20:8080
```

点击“开始监听”。

注意：`0.0.0.0` 表示服务监听所有网卡，不是手机要访问的地址。手机要访问服务器真实的局域网 IP。

## 项目里的几个入口

- `/`：网页播放器。
- `/stream.mp3`：浏览器实际播放的音频流。
- `/health`：健康检查，正常时返回 `ok`。

代码入口是 [src/homesound.py](src/homesound.py)。它包含四个核心部分：

- `load_simple_yaml()`：读取 `config.yaml`。
- `CameraWorker`：每个摄像头一个后台线程，用 ffmpeg 拉取音频。
- `PcmRingBuffer`：保存每个摄像头最近几秒的声音。
- `Mixer` 和 `stream_mp3()`：混合多路声音并输出给浏览器。

更详细的代码说明见 [代码使用说明](docs/code-usage.md)。

## 常见问题

### 打开网页但没有声音

先确认摄像头 RTSP 地址本身能用：

```bash
ffmpeg -rtsp_transport tcp -i "rtsp://user:password@192.168.1.31:554/stream1"
```

重点看输出里有没有 `Audio:`。如果只有 `Video:`，说明这个地址可能没有音频轨道。

### 手机打不开页面

确认三件事：

- 手机和服务器在同一个局域网。
- 手机访问的是服务器 IP，例如 `http://192.168.1.20:8080`。
- 服务器防火墙允许 8080 端口被局域网访问。

### 摄像头账号密码里有特殊字符怎么办

RTSP URL 里的特殊字符可能需要 URL 编码。例如密码里有 `@`，通常要写成 `%40`。建议先用 ffmpeg 命令验证地址。

### 延迟比较高

当前原型使用 MP3 输出，兼容性好，但不是最低延迟方案。后续路线图会加入 WebM/Opus 低延迟播放。

### 可以远程在外面听吗

不建议直接把 8080 端口映射到公网。更推荐用 Tailscale、WireGuard、ZeroTier 或家庭 VPN，让手机像在家里局域网一样访问。

## 安全提醒

当前原型没有账号、密码、HTTPS 和访问控制。请只在可信网络中使用，不要直接暴露到公网。

真实的 `config.yaml` 可能包含摄像头账号密码，已经被 `.gitignore` 排除。不要把真实配置提交到 GitHub。

## 文档

- [使用场景](docs/scenarios.md)
- [摄像头接入指南](docs/camera-setup.md)
- [配置说明](docs/configuration.md)
- [代码使用说明](docs/code-usage.md)
- [架构说明](docs/architecture.md)
- [部署说明](docs/deployment.md)
- [安全说明](SECURITY.md)

## 路线图

- 支持每个房间单独静音和音量调节。
- 支持 WebM/Opus 低延迟播放。
- 增加简单访问令牌。
- 增加 Docker 部署方式。
- 增加摄像头在线状态页。
- 增加 Prometheus 指标。
- 支持更多输入音频格式和自动重采样。

## 许可证

MIT License
