# Syncthing 深度解构 — 为映记嵌入做准备

> 2026-06-30 | v0.1
> 目的：在写代码之前，彻底理解 Syncthing 的架构、数据流、API 面、用户痛点和 CUI 机会

---

## 一、系统架构总览

```
┌─────────────────────────────────────────────────────┐
│                  Syncthing 实例                      │
│                                                      │
│  ┌──────────┐  ┌──────────┐  ┌──────────────────┐   │
│  │ REST API  │  │  Event   │  │   Block Exchange  │   │
│  │ (8384)    │  │  Stream  │  │   Protocol (BEP)  │   │
│  │           │  │          │  │   (22000 TCP/QUIC)│   │
│  └─────┬─────┘  └─────┬────┘  └────────┬─────────┘   │
│        │              │                 │             │
│  ┌─────┴──────────────┴─────────────────┴──────────┐ │
│  │               Core 模型层                        │ │
│  │  ┌──────────┐ ┌──────────┐ ┌────────────────┐  │ │
│  │  │  设备    │ │  文件夹  │ │  本地数据库    │  │ │
│  │  │ (Device) │ │ (Folder) │ │ (LevelDB/bolt) │  │ │
│  │  └──────────┘ └──────────┘ └────────────────┘  │ │
│  └─────────────────────────────────────────────────┘ │
│                                                      │
│  ┌──────────────────────────────────────────────┐   │
│  │  连接管理层                                     │   │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────────┐  │   │
│  │  │ LAN发现   │ │ NAT穿透  │ │ 全球发现      │  │   │
│  │  │(mDNS/QUIC)│ │(UPnP/STUN)│ │(Global Disc) │  │   │
│  │  └──────────┘ └──────────┘ └──────────────┘  │   │
│  │  ┌──────────┐                                    │   │
│  │  │ 中继连接 │                                    │   │
│  │  │ (Relay)  │                                    │   │
│  │  └──────────┘                                    │   │
│  └──────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────┘
```

### 内部模块分解

| 层级 | 组件 | 语言 | 作用 |
|------|------|------|------|
| **传输** | BEP (Block Exchange Protocol) | Go | 文件块级同步，自定义协议，跑在 TCP/QUIC 上 |
| **发现** | mDNS / Global Discovery / Relay | Go | 四层级联的设备发现策略 |
| **存储** | LevelDB (via `bep/` 包) | Go | 文件元数据索引 + 块索引 |
| **配置** | JSON 配置文件 (`config.xml`) | XML → 内部 Go struct | 所有设备/文件夹/选项的持久化 |
| **API** | REST API + Event Stream | Go `net/http` | GUI 的前端后端接口 |
| **GUI** | React (纯前端) + REST 调用 | TypeScript | Web 管理界面 |
| **文件监控** | fsnotify (跨平台) | Go | 实时检测本地文件变更 |

---

## 二、REST API 全景图（36+ 端点）

### 2.1 系统类

```
GET    /rest/system/status        → 系统状态（内存、连接服务、发现错误、启动时间）
GET    /rest/system/connections   → 设备连接列表（在线/离线、流量统计）
GET    /rest/system/version       → 版本号
GET    /rest/system/error         → 错误列表
POST   /rest/system/error/clear   → 清空错误
GET    /rest/system/log           → 日志
POST   /rest/system/pause         → 暂停所有同步
POST   /rest/system/resume        → 恢复所有同步
POST   /rest/system/restart        → 重启
POST   /rest/system/shutdown       → 关闭
GET    /rest/system/ping           → 心跳检测
GET    /rest/system/browse         → 文件浏览（本地路径）
GET    /rest/system/discovery      → 发现状态
POST   /rest/system/discovery      → 触发发现
```

### 2.2 配置类（v1.12+ 新增，比旧端点好用）

```
GET/PUT    /rest/config                     → 全量读写配置
GET/PUT    /rest/config/folders             → 所有文件夹配置
POST/DEL   /rest/config/folders/{id}        → 增删改单个文件夹
GET/PUT    /rest/config/devices             → 所有设备配置
POST/DEL   /rest/config/devices/{id}        → 增删改单个设备
GET/PUT    /rest/config/options             → 全局选项
GET/PUT    /rest/config/gui                 → GUI 设置
GET        /rest/config/restart-required    → 是否需要重启
```

### 2.3 文件夹运行时状态

```
GET    /rest/db/status?folder={id}          → 文件夹同步状态（global/local/need/state）
GET    /rest/db/completion?folder=&device=  → 同步完成百分比
GET    /rest/db/need                        → 需要同步的文件列表
GET    /rest/db/file?folder=&file=          → 单个文件元数据
GET    /rest/db/browse?folder=&prefix=      → 浏览文件夹内容
POST   /rest/db/scan?folder=                → 触发重新扫描
POST   /rest/db/override?folder=            → 用本地版本覆盖冲突
POST   /rest/db/revert?folder=              → 撤销本地修改
POST   /rest/db/prio?folder=&file=          → 优先同步某个文件
GET    /rest/folder/errors?folder=          → 文件夹同步错误
```

### 2.4 事件流

```
GET    /rest/events?since={id}&limit={n}           → Long-polling 事件流
GET    /rest/events/disk?since={id}&limit={n}      → 磁盘持久化的事件
```

### 2.5 事件类型（31 种）

按语义分组：

```
系统生命周期    : Starting, StartupComplete, ConfigSaved, LoginAttempt
设备连接        : DeviceConnected, DeviceDisconnected, DeviceDiscovered
                DevicePaused, DeviceResumed
文件夹状态      : StateChanged, FolderErrors, FolderSummary, FolderPaused/FolderResumed
                FolderCompletion, FolderScanProgress, FolderWatchStateChanged
文件同步        : ItemStarted, ItemFinished, DownloadProgress
变更检测        : LocalChangeDetected, RemoteChangeDetected
                LocalIndexUpdated, RemoteIndexUpdated
集群管理        : ClusterConfigReceived, PendingDevicesChanged, PendingFoldersChanged
网络状态        : ListenAddressesChanged
```

### 2.6 无鉴权端点

```
GET    /rest/noauth/health   → 健康检查
```

---

## 三、数据模型

### 3.1 设备 (Device)

```
DeviceID       : string (52 chars base32, 公钥哈希)
Name           : string (人类可读名)
Addresses      : []string (动态/静态地址)
Compression    : "always" | "metadata" | "never"
CertName       : string (TLS 证书 CN)
Introducer     : bool (能否介绍其他设备)
Paused         : bool
MaxSendKbps    : int
MaxRecvKbps    : int
```

### 3.2 文件夹 (Folder)

```
ID             : string (唯一标识)
Label          : string (显示名)
Path           : string (本地路径)
Type           : "sendonly" | "receiveonly" | "sendreceive"
Devices        : []DeviceID (共享给谁)
RescanInterval : duration
IgnorePerms    : bool
AutoNormalize  : bool
Versioning     : { Type: "trashcan"|"simple"|"staggered"|"external", Params: {} }
Paused         : bool
```

### 3.3 同步状态模型

```
global*        : 集群最新版本（所有设备综合）
local*         : 本地存在的数据（无论版本）
inSync*        : 本地与集群一致的数据
need*          : 需要同步的数据（global - inSync）
receiveOnly*   : 接收专用文件夹中本地修改的数据
pullErrors     : 拉取失败的文件数
state          : "idle" | "syncing" | "scanning" | "error"
stateChanged   : 状态变更时间戳
```

### 3.4 事件流数据模型

```json
{
  "id": 42,
  "globalID": 42,
  "type": "ItemFinished",
  "time": "2026-06-30T22:00:00+08:00",
  "data": {
    "folder": "default",
    "folderID": "default-folder-id",
    "item": "report.pdf",
    "itemType": "FILE",
    "error": null,
    "version": 12345
  }
}
```

---

## 四、连接拓扑（Discovery Stack）

这是 Syncthing 最复杂的部分，也是面试常考题：

```
Layer 1: LAN Discovery (mDNS)
  → 同一广播域自动发现
  → 零配置，不经过任何外部服务
  
Layer 2: NAT Traversal (UPnP / NAT-PMP)
  → 尝试在路由器上自动打洞（端口转发）
  → 失败则进入下一层

Layer 3: STUN / QUIC
  → 尝试 UDP 打洞（类似 WebRTC 的 ICE）
  → SYNCTHING v1.24+ 支持 QUIC

Layer 4: Global Discovery Servers
  → 把你的公网地址注册到 syncthing.net 的发现服务器
  → 其他设备可以查到你的地址
  → 协议：HTTPS POST + TLS 证书验证
  
Layer 5: Relay Servers
  → 所有直连方式都失败后使用
  → 社区志愿者运行的公共中继
  → 数据全程加密（End-to-End），中继无法查看内容
```

**你的问题集（面试导向）：**
- 设备 ID = TLS 公钥哈希 → 什么是公钥哈希？为什么用这个设计而不直接用 IP？
- 中继服务器本质是什么？—— 一个 TCP 转发代理 + 端到端加密隧道
- 发现服务器的安全性问题？—— 可能被 DDOS，但影响仅限新设备发现，不影响已建立连接的设备

---

## 五、Block Exchange Protocol（BEP）概要

```
Step 1: Hello (TLS 握手 + 交换设备 ID 证书)
Step 2: Index (交换文件列表：所有文件的元数据 + 块哈希列表)
Step 3: Request (发现差异后，请求缺失的块)
Step 4: Response (传输块数据)
Step 5: 重复 2-4 直到双方一致
```

关键设计：
- **分块**：文件被切成 128KB 块（可变，最小 64KB），每块有 SHA256 哈希
- **增量**：只传真正不同的块，不是整个文件
- **断点续传**：已传的块标记为完成，中断后只传剩余
- **最终一致性**：不保证所有设备同时一致，但保证最终一致

---

## 六、用户痛点映射（GUI → CUI 机会）

基于 GitHub issues 和社区反馈的真实痛点：

### 痛点分层

| 优先级 | 痛点 | 场景 | 相关 Issue |
|--------|------|------|-----------|
| 🔴 P0 | 同步卡 XX% 不清楚原因 | 用户看到进度条不动，但不知道哪个文件卡住/为什么卡住 | #9482 |
| 🔴 P0 | 两个设备同步状态不一致 | 设备A说已同步，设备B还在同步，用户无法判断 "到底同步完了没" | #6580 |
| 🔴 P0 | 配置变更触发全量重扫 | 改了个配置项，所有文件夹重新扫描一遍，同步进度重置 | #9949 |
| 🟠 P1 | 文件夹冲突不知如何解决 | 文件名冲突时，用户不确定该保留哪个版本 | #9121 |
| 🟠 P1 | 中继/直连/发现服务故障排查 | 连接不上时，用户需要在五个层级里手动排除 | #9365 |
| 🟠 P1 | 日志太多，找不到关键信息 | `Logs` 页面全是大文本，用户不知道哪个错误值得关注 | #8844 |
| 🟡 P2 | 忘记哪个设备在哪台电脑上 | 多个设备时，设备 ID 难以分辨 | #8511 |
| 🟡 P2 | 多设备拓扑不直观 | 没有网络拓扑可视化 | #7923 |
| 🟢 P3 | 版本控制恢复不清楚 | 文件的旧版本去哪了？怎么恢复？ | #7764 |

### CUI 解决范式

```
GUI 方式：打开浏览器 → 点进文件夹 → 看状态 → 看错误 → 去日志找 → 逐层排查
CUI 方式（Yingji）：

"为什么我的同步卡在 95%？"
→ /rest/db/completion 查 needItems
→ /rest/db/need 查具体哪些文件
→ /rest/folder/errors 查错误
→ 合成一句话回答

"帮我看看第三台设备收到文件了吗"
→ 设备列表 → 连接状态 → 每个文件夹的 completion → 聚合回答

"刚才网络闪断了，现在连回来了没？"
→ 事件流 scan DeviceConnected 事件
→ /rest/system/connections check
```

---

## 七、Yingji 集成方案

### 7.1 架构位置

```
User AI (小云) ─── AI-to-AI 协议 ───→ Yingji 实例
                                          │
                                    SyncthingService
                                          │
                                    Python Syncthing HTTP Client
                                          │
                                    REST API (127.0.0.1:8384)
                                          │
                                    Syncthing 实例
```

### 7.2 需要实现的 API 操作注册（按优先级）

```python
# Yingji capabilities 注册
capabilities.register(
    intent="query_system_status",
    handler=get_system_status,
    description="获取 Syncthing 系统状态（运行时间、内存、版本）"
)
capabilities.register(
    intent="query_device_connections",
    handler=get_device_connections,
    description="查询所有设备连接状态（在线/离线/流量）"
)
capabilities.register(
    intent="query_folder_status",
    handler=get_folder_status,
    description="查询文件夹同步状态（需要/正在/已完成/错误）"
)
capabilities.register(
    intent="query_folder_completion",
    handler=get_folder_completion,
    description="查询同步完成百分比 + 剩余文件数"
)
capabilities.register(
    intent="query_errors",
    handler=get_errors,
    description="查询最近的同步错误"
)
capabilities.register(
    intent="query_pending_devices",
    handler=get_pending_devices,
    description="查询等待接受的设备"
)
capabilities.register(
    intent="query_folder_need",
    handler=get_folder_need,
    description="查询需要同步的具体文件列表"
)
capabilities.register(
    intent="trigger_rescan",
    handler=trigger_rescan,
    description="触发指定文件夹重新扫描"
)
capabilities.register(
    intent="trigger_override",
    handler=local_override,
    description="用本地版本覆盖冲突"
)
capabilities.register(
    intent="query_logs",
    handler=get_logs,
    description="获取最近的日志"
)
```

### 7.3 事件流集成（比轮询更好的方式）

```
Event Stream ─→ Yingji Event Router
                    │
                    ├── DeviceConnected     → 通知用户方 AI："设备 X 上线了"
                    ├── DeviceDisconnected   → 通知："设备 X 掉线了"
                    ├── StateChanged         → 通知："文件夹 X 状态变更：idle → syncing"
                    ├── ItemFinished         → 通知："文件 X 同步完成"
                    ├── FolderErrors         → 通知："文件夹 X 有 Y 个拉取错误"
                    └── LocalChangeDetected  → 通知："本地检测到文件变更"
```

---

## 八、知识点路线图（给小刘的学习路径）

### 按难度分层

```
Level 1 — 直接和 API 打交道
├── HTTP REST 基础（你已有）
├── JSON 数据结构
└── API 调用流程

Level 2 — 理解 Go 写的东西
├── Go 的基础语法（不需要精通，能读懂 API handler）
├── TLS 证书与公钥加密
└── 哈希函数（SHA256 在分块传输中的作用）

Level 3 — 网络协议
├── TCP / QUIC 区别
├── NAT 穿透原理（UPnP / STUN）
├── mDNS 本地服务发现
└── 中继服务器工作方式

Level 4 — 分布式系统概念
├── 最终一致性（Eventual Consistency）
├── 冲突解决策略（Last Writer Wins + 冲突副本）
├── 分块传输（Block Transfer）
└── 断点续传机制
```

### 面试问题答案预览

**Q: 「两台设备都在 NAT 后面怎么连接？」**
→ Syncthing 用五层联级策略：mDNS（局域网直接发现）→ UPnP（路由器打洞）→ STUN（UDP 打洞）→ Global Discovery（注册公网地址）→ Relay（端到端加密中继）。每一层尝试失败后自动 fallback 到下一层，保证最终能连上。

**Q: 「文件冲突了怎么处理？」**
→ Syncthing 的策略是"后写胜出 + 差异副本保留"。假设设备A先改文件，设备B后改，B的版本成为主版本，A的版本被重命名为 `.sync-conflict-20260630-220000-xxxxx.pdf` 保留下来。用户自行决定是删冲突副本还是手动合并。

**Q: 「大文件怎么传输？」**
→ 分块（默认 128KB/块），每块 SHA256 哈希，只传输与远程不同的块。中断后已传的块不重传。这叫"增量同步 + 断点续传"。

**Q: 「安全性怎么保证？」**
→ TLS 1.3 加密传输，基于自签名 TLS 证书的设备 ID 验证（设备 ID = 公钥哈希，MITM 无法伪造），中继服务器无法解密数据（端到端加密）。

**Q: 「你的映记在里面做什么？」**
→ AI 接口层。把 REST API 封装成 Yingji Service，用户方 AI 可以通过自然语言直接查询同步状态、诊断连接问题、处理冲突，不需要打开 GUI 逐层点。

---

## 九、下一步

1. **先把 syncthing.exe 跑起来**，调通 curl 调 `/rest/system/status`
2. **我写 Python SyncthingClient**（纯 HTTP wrapper）
3. **注册到 Yingji capabilities.py**
4. **写几个测试场景**（自然语言问问题，看回复对不对）
5. **用两个实例模拟多设备 + 文件同步**，跑通全流程

---

> 问题？有哪个概念想先深入？还是直接开始写代码？先过完这个文档，你觉得差不多了我就开始写 SyncthingClient。
