# 家声 HomeSound

一个面向中文用户的本地婴儿监听 / 房间声音监听项目。

它可以把家里的 RTSP 网络摄像头变成一个只听声音的网页监听器：摄像头负责收音，家里的小服务器负责转码和混音，手机浏览器负责播放。整个过程优先在局域网内完成，不依赖厂商云服务。

## 适合的场景

- 两个孩子分别睡在不同房间，你想在手机上同时听到两个房间的声音。
- 家里已经有支持 RTSP 的摄像头，不想再买传统婴儿监视器。
- 不希望监控音频经过第三方云服务。
- 想用浏览器打开一个本地网页，点一下就开始听。

## 它怎么工作

```text
RTSP 摄像头 1 ─┐
RTSP 摄像头 2 ─┼─> HomeSound 服务端 ──> 网页音频流 ──> 手机浏览器
RTSP 摄像头 3 ─┘
```

服务端会持续从摄像头拉取音频，保存最近一小段声音。当手机打开网页并点击播放时，服务端把多个房间的声音混合成一路，再输出给浏览器播放。

## 当前状态

这是一个中文开源项目设计稿和可运行原型，目标是让更多中文用户能理解、部署和继续改造这种“本地声音监听器”。

当前包含：中文 README、场景说明、架构说明、示例配置、Python 服务端原型、浏览器播放页面和开源协作文件。

## 快速开始

### 1. 安装依赖

需要先安装 `ffmpeg`，并确保命令行可以直接运行：

```bash
ffmpeg -version
```

### 2. 准备配置

```bash
cp config.example.yaml config.yaml
```

然后把里面的 RTSP 地址改成你的摄像头地址。

### 3. 启动服务

```bash
python src/homesound.py --config config.yaml
```

默认监听：`http://0.0.0.0:8080`

在手机浏览器中打开家里服务器的局域网地址，例如：`http://192.168.1.20:8080`，点击“开始监听”即可播放。

## 示例配置

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
    volume: 1.0
```

## 设计原则

- 本地优先：默认只面向局域网使用。
- 声音优先：先做好稳定的音频监听，不追求视频功能。
- 简单优先：手机浏览器能打开，家人就能用。
- 实时优先：宁可丢掉太旧的数据，也尽量播放最新声音。
- 中文友好：文档、配置示例、场景说明都用中文写清楚。

## 安全提醒

请不要把服务直接暴露到公网。当前原型没有账号、密码、HTTPS 和访问控制。建议只在家庭局域网、Tailscale、WireGuard 等可信网络中使用。

## 项目结构

```text
home-sound-monitor/
├── README.md
├── LICENSE
├── config.example.yaml
├── src/
│   ├── homesound.py
│   └── web/
│       └── index.html
└── docs/
    ├── architecture.md
    ├── deployment.md
    └── scenarios.md
```

## 路线图

- 支持每个房间单独静音和音量调节
- 支持 WebM/Opus 低延迟播放
- 增加简单访问令牌
- 增加 Docker 部署方式
- 增加摄像头在线状态页
- 增加 Prometheus 指标
- 支持更多输入音频格式和自动重采样

## 许可证

MIT License
