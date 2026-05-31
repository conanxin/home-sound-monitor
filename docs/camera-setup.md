# 摄像头接入指南

HomeSound 通过 RTSP 读取摄像头音频。接入摄像头前，先确认它能在局域网里提供带音频的 RTSP 流。

## 一句话判断

如果你能用下面命令打开摄像头，并且输出里能看到 `Audio:`，HomeSound 通常就可以接入：

```bash
ffmpeg -rtsp_transport tcp -i "rtsp://user:password@192.168.1.31:554/stream1"
```

## 需要什么类型的摄像头

推荐使用：

- 支持 RTSP 的网络摄像头。
- 支持 ONVIF 的安防摄像头。
- 支持 RTSP 输出的 NVR 通道。
- 可以在管理后台开启 RTSP 的家用摄像头。

需要注意：

- 摄像头必须有麦克风，或者 RTSP 流里必须有音频轨道。
- 服务器要能访问摄像头 IP。
- 摄像头账号需要有观看或拉流权限。

## 不同设备的常见线索

不同品牌和型号的 RTSP 路径差别很大，但排查方向类似：

1. 打开摄像头管理后台。
2. 查找“网络”、“高级设置”、“视频流”、“ONVIF”、“RTSP”或“开放协议”。
3. 打开 RTSP 或 ONVIF。
4. 创建或确认摄像头用户名和密码。
5. 在说明书、后台帮助或品牌文档中查找 RTSP 路径。

常见地址形式：

```text
rtsp://用户名:密码@摄像头IP:554/stream1
rtsp://用户名:密码@摄像头IP:554/live
rtsp://用户名:密码@摄像头IP:554/h264/ch1/main/av_stream
rtsp://用户名:密码@摄像头IP:554/cam/realmonitor?channel=1&subtype=0
```

这些只是示例，不保证适用于你的设备。真正地址以设备说明为准。

## 如何确认有声音

运行：

```bash
ffmpeg -rtsp_transport tcp -i "你的 RTSP 地址"
```

看输出中是否有类似：

```text
Stream #0:1: Audio: aac, 8000 Hz, mono
Stream #0:1: Audio: pcm_alaw, 8000 Hz, mono
Stream #0:1: Audio: opus, 48000 Hz, mono
```

只要 ffmpeg 能读到音频，HomeSound 原型会尝试把它转成 `48000Hz mono s16le` 后混音。

如果只看到：

```text
Stream #0:0: Video: h264
```

那说明这个 RTSP 地址可能只有视频，没有音频。请尝试另一个码流地址，或在摄像头后台开启音频。

## 主码流和子码流怎么选

很多摄像头有主码流和子码流：

- 主码流：画质高，带宽大。
- 子码流：画质低，带宽小。

HomeSound 只需要声音，所以优先选择稳定、低带宽、带音频的那一路。通常子码流更合适，但有些设备只有主码流带音频，需要实际测试。

## 账号密码里的特殊字符

RTSP 地址中如果密码包含特殊字符，可能需要 URL 编码：

```text
@  -> %40
#  -> %23
%  -> %25
空格 -> %20
```

例如密码是：

```text
abc@123
```

URL 里应写成：

```text
rtsp://user:abc%40123@192.168.1.31:554/stream1
```

## 多个摄像头

HomeSound 支持在 `config.yaml` 里写多个摄像头：

```yaml
cameras:
  - name: 儿童房 A
    url: rtsp://user:password@192.168.1.31:554/stream1
    volume: 1.0
  - name: 儿童房 B
    url: rtsp://user:password@192.168.1.32:554/stream1
    volume: 0.8
```

服务启动后会为每个摄像头创建一个后台读取线程。浏览器连接时，服务端会把这些摄像头的声音混成一路。

## 排查清单

如果接不进去，按这个顺序检查：

1. 摄像头和服务器是否在同一局域网。
2. 摄像头 IP 是否能 ping 通。
3. 摄像头后台是否开启 RTSP/ONVIF。
4. 用户名和密码是否正确。
5. RTSP 地址是否能被 ffmpeg 打开。
6. ffmpeg 输出里是否有 `Audio:`。
7. 摄像头是否开启了麦克风或音频编码。
8. 防火墙是否拦截了摄像头端口，常见是 554。

## 隐私建议

摄像头账号密码通常会写在 `config.yaml` 里。请不要把真实配置提交到 GitHub，也不要截图公开包含 RTSP 地址的页面。
