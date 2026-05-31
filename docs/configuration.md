# 配置说明

HomeSound 默认读取 `config.yaml`。你可以从示例文件开始：

```bash
cp config.example.yaml config.yaml
```

Windows PowerShell：

```powershell
Copy-Item config.example.yaml config.yaml
```

## 完整示例

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

## server

### host

服务监听地址。

```yaml
host: 0.0.0.0
```

常见选择：

- `0.0.0.0`：监听所有网卡，方便手机从局域网访问。
- `127.0.0.1`：只允许本机访问，适合调试。

手机访问时不要输入 `0.0.0.0`，而是输入服务器的真实局域网 IP，例如：

```text
http://192.168.1.20:8080
```

### port

服务端口。

```yaml
port: 8080
```

如果 8080 已经被占用，可以改成 8090、9000 等。

## audio

### sample_rate

内部混音采样率。

```yaml
sample_rate: 48000
```

推荐保持 `48000`。HomeSound 会让 ffmpeg 把输入音频转换到这个采样率。

### channels

当前原型只支持单声道。

```yaml
channels: 1
```

请保持为 `1`。

### buffer_seconds

每个摄像头保留最近多少秒的原始声音块。

```yaml
buffer_seconds: 8
```

这个缓冲区不是录音保存，只是为了让浏览器随时连接时能读到最近声音。一般保持 5 到 10 秒即可。

### output_format

当前原型实际输出 MP3。

```yaml
output_format: mp3
```

这个字段先作为配置占位。后续增加 WebM/Opus、AAC 等输出时会继续使用。

## cameras

摄像头列表。每个摄像头包含 `name`、`url`、`volume`。

### name

显示和日志中使用的名称。

```yaml
name: 儿童房 A
```

建议写成真实房间名，方便排查。

### url

摄像头 RTSP 地址。

```yaml
url: rtsp://user:password@192.168.1.31:554/stream1
```

请先用 ffmpeg 验证：

```bash
ffmpeg -rtsp_transport tcp -i "rtsp://user:password@192.168.1.31:554/stream1"
```

如果地址里有特殊字符，请做 URL 编码。

### volume

该摄像头混音时的音量倍率。

```yaml
volume: 1.0
```

常见值：

- `1.0`：原始音量。
- `0.8`：稍微降低。
- `0.5`：减半。
- `1.5`：放大，但可能更容易爆音。

如果多个房间同时很响，直接相加可能失真。可以把每路音量适当调低，例如两个房间都设为 `0.7`。

## 当前 YAML 限制

为了让原型尽量少依赖，当前代码使用一个很小的 YAML 读取函数，不是完整 YAML 解析器。建议配置保持简单：

- 使用空格缩进，不要使用 Tab。
- 不要写复杂嵌套结构。
- RTSP 地址直接写在一行。
- 如果遇到解析问题，优先参考 `config.example.yaml` 的格式。

后续如果配置复杂度上升，可以引入 PyYAML。
