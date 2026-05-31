# 部署说明

## 推荐部署位置

HomeSound 适合运行在家中长期在线的设备上：

- NAS
- 迷你主机
- 树莓派
- 旧电脑
- 家庭服务器

## 网络建议

推荐只在局域网内使用。不要直接把端口暴露到公网。

如果确实需要在外面访问家里的 HomeSound，建议使用：

- Tailscale
- WireGuard
- ZeroTier
- 家庭 VPN

## 摄像头准备

摄像头需要支持 RTSP。常见地址形式类似：

```text
rtsp://用户名:密码@摄像头IP:554/stream1
```

不同品牌路径不一样，请查阅摄像头说明书或管理后台。

## 防止泄露

真实的 `config.yaml` 可能包含摄像头账号密码，所以已经被 `.gitignore` 排除。请只提交 `config.example.yaml`。

## 常见问题

### 手机打不开页面

确认手机和服务器在同一个局域网中，并使用服务器的局域网 IP，而不是 `0.0.0.0`。

### 没有声音

先确认摄像头 RTSP 地址可以被 ffmpeg 打开：

```bash
ffmpeg -i "rtsp://user:password@192.168.1.31:554/stream1"
```

### 延迟较高

当前原型优先兼容性，使用 MP3 输出。后续可以增加 WebM/Opus + MediaSource 的低延迟播放路径。
