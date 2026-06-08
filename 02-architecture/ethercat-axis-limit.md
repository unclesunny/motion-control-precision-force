# EtherCAT 多轴监控原理与轴数上限分析

> 创建: 2026-06-07 | 关联: `03-ethercat-master/`, `04-oscilloscope/`, `multi-axis-architecture.md`

---

## 一、EtherCAT "飞读飞写" (Processing on the Fly) 原理

EtherCAT 与传统现场总线的核心区别：**Master 只发一帧，所有 Slave 在帧经过的瞬间读写数据，而不是轮询**。

```
Master 发出一帧 Ethernet Frame:
┌──────────────────────────────────────────────────────────────┐
│ Eth Hdr(14B) │ Datagram LRW │ WKC(2B) │ FCS(4B)            │
│              │ addr=0x0000  │         │                     │
│              │ len=所有Slave │         │                     │
│              │ 的PDO总和     │         │                     │
└──────────────────────────────────────────────────────────────┘
     │
     ▼  帧以线速(100Mbps)穿过每个 slave 的 ESC 芯片 (纯硬件, <1μs/slave)
┌─────────┐    ┌─────────┐    ┌─────────┐
│ Slave 0 │───→│ Slave 1 │───→│ Slave 2 │───→ ... → 回到 Master
│ Axis X  │    │ Axis Y  │    │ Axis Z  │
│ ESC 在帧│    │ ESC 在帧│    │ ESC 在帧│
│ 偏移0   │    │ 偏移23B │    │ 偏移46B │
│ 写入PDO │    │ 处写入  │    │ 处写入  │
└─────────┘    └─────────┘    └─────────┘

关键特性:
  - 只有一帧 — 不是"问 Slave1 → 等应答 → 问 Slave2"
  - ESC 芯片纯硬件处理 — 延迟 <1μs/slave
  - 数据在帧内连续排列 — 偏移0=AxisX, 偏移23=AxisY, 偏移46=AxisZ...
```

在本项目的 IgH 后端中，所有轴注册到**同一个 domain**，`exchange()` 一次调用，全部数据到位：

```python
# ec_master.py:539 — 所有轴共享一个 domain buffer
for index, subindex, data_type in entries:  # 8 CiA 402 通道
    lib.ecrt_slave_config_reg_pdo_entry(slave_cfg, index, subindex,
                                         self._domain,  # ← 同一个 domain!
                                         offset_ptr)     # ← 写入字节偏移量

# ec_master.py:622 — 一次交换, 所有轴数据同时到达
def exchange(self):
    self.receive()          # domain_data 包含所有轴的完整 PDO
    self.queue_and_send()
```

---

## 二、一帧能装多少轴？

### 2.1 有效载荷计算

SOEM 中标准 Ethernet 帧的最大 EtherCAT 数据区：

```
EC_MAXECATFRAME  = 1518 bytes        (标准 Ethernet MTU)
EC_MAXLRWDATA    = 1518 - 14(Eth Hdr) - 2(Length) - 10(Datagram Hdr) - 2(WKC) - 4(FCS)
                 = 1486 bytes         (有效 EtherCAT 载荷)
```

### 2.2 每轴 PDO 数据量 (8 CiA 402 通道)

| 通道 | CoE 对象 | 数据类型 | 字节 |
|------|---------|---------|------|
| Position Actual | 0x6064 | DINT | 4 |
| Velocity Actual | 0x606C | DINT | 4 |
| Current Actual  | 0x6078 | INT  | 2 |
| Torque Actual   | 0x6077 | INT  | 2 |
| Following Error | 0x60F4 | DINT | 4 |
| Digital Inputs  | 0x60FD | UDINT| 4 |
| Statusword      | 0x6041 | UINT | 2 |
| Op Mode Display | 0x6061 | SINT | 1 |
| **每轴合计**    |         |      | **23 bytes** |

### 2.3 轴数上限

```
标准帧 (1518 bytes, 1486 有效):  1486 / 23 = 64 轴   ← 项目 UI 硬限制
Jumbo帧 (9000 bytes, 8968 有效):  8968 / 23 = 389 轴
两帧/cycle (标准帧 × 2):          1486 × 2 / 23 = 129 轴
```

**`scope_app.py:895` 的 `min(n_axes, 64)` 不是随便写的——恰好等于一帧标准 MTU 能装下的最大轴数。**

---

## 三、64 轴 vs 128 轴 vs 更多

### 3.1 物理约束对比

| 维度 | 64 轴 | 128 轴 | 200 轴 (SOEM上限) |
|------|-------|--------|-------------------|
| PDO 数据量 | 1,472 bytes | 2,944 bytes | 4,600 bytes |
| 所需帧数 | 1 帧 (标准MTU) | **2 帧** 或 1 Jumbo | 4 帧 或 2 Jumbo |
| 帧传输时间 (100Mbps) | ~124μs | ~248μs (2帧) | ~496μs (4帧) |
| Slave 传播延迟 (1μs/slave) | ~64μs | ~128μs | ~200μs |
| **总线周期占用** | **~188μs** | **~376μs** | **~696μs** |

### 3.2 不同采样率下的可行性

```
10kHz DC 周期 (100μs):
  → 100μs - 20μs(帧开销) = 80μs 可用
  → 80μs / (1μs + 1.84μs/轴) ≈ 28 轴  ← 10kHz 物理极限

1kHz DC 周期 (1ms):
  → 标准帧 (64轴): 188μs, 剩余 812μs — 宽松
  → 两帧 (128轴):  376μs, 剩余 624μs — 可行
  → Jumbo (250轴):  ~500μs, 剩余 500μs — 可行

100Hz DC 周期 (10ms):
  → 几乎不受限, 200 轴完全可行
```

### 3.3 多帧与跨周期数据一致性

**一个 DC 周期内可以发多个帧。只要总传输时间 < DC 周期，所有轴的数据都是同一周期的。**

```
DC 周期 = 1ms, 128 轴, 两帧:

│
├─ SYNC0 中断 → 所有 slave 同时锁存 PDO 数据
│
├─ Frame 1 (124μs): Slave 0..63   ← 当次周期新鲜数据
├─ Frame 2 (124μs): Slave 64..127 ← 仍是当次周期新鲜数据!
│
├─ 剩余 ~690μs: AI 分析 + UI 渲染
│
└─ 下一个 SYNC0
```

**但如果帧传输时间超过 DC 周期，出现跨周期错位：**

```
DC 周期 = 100μs, 128 轴:

Cycle 0: SYNC0(所有slave锁存) → Frame1(Slave0..63, 124μs)
         ├─ Frame1 还没传完, Cycle 1 的 SYNC0 又来了
         └─ Slave 再次锁存新数据 ⚠️

Cycle 1: Frame1 延迟返回(上个周期数据)
         Frame2(Slave64..127, 124μs) → 这是 Cycle 1 锁存的数据

结果: Frame1 = Cycle0数据, Frame2 = Cycle1数据 → 不同步 ❌
```

**数据错位示意：**

```
轴数 ↑
128 ┤                              ████ Frame2 (Slave64..127)
    │                    ████ Frame1 (Slave0..63)
 64 ┤          ████ Frame1                    ████ Frame1
    │    ████                                   ╲
  0 ┼────┼────┼────┼────┼────┼────┼────┼────→ 时间
       Cycle0   Cycle1   Cycle2   Cycle3   Cycle4

图例: ████ = 一帧传输 (124μs @ 100Mbps, 64轴/帧)

帧总时间 124μs > DC 100μs:
  - Frame1 从 Cycle0 开始传输, Cycle1 才返回 → Frame1 是 Cycle0 的数据
  - Frame2 从 Cycle1 开始传输, Cycle2 才返回 → Frame2 是 Cycle1 的数据
  - ⚠️ 同一采样时刻的数据分散在 2 个 DC 周期到达
```

**结论：**

| 条件 | 数据一致性 |
|------|-----------|
| 帧传输总时间 < DC 周期 | 全部轴同一周期, 严格同步 ✅ |
| 帧传输总时间 > DC 周期 | 后发的帧滞后 1 个周期, 部分轴数据时间戳错位 ⚠️ |
| 帧传输总时间 >> DC 周期 | 多帧分散在多周期, 严重错位 ❌ |

**这解释了为什么 1ms 周期可以轻松跑 200+ 轴，而 100μs 周期连 64 轴都勉强。不是协议限制了轴数，是物理时间限制了同步性。Beckhoff 的"无限轴"建立在足够大的 DC 周期之上。**

### 3.4 软件瓶颈 (本项目的实际情况)

| 瓶颈 | 64 轴 | 128 轴 |
|------|-------|--------|
| RingBuffer 内存 | ~246 MB (64×3.84MB) | ~492 MB |
| AI Pipeline 实例 | 64 个 (每轴 3 检测器) | 128 个 |
| **CrossAxisAnalyzer 配对** | **2,016 对** (64×63/2) | **8,128 对** (128×127/2) |
| PyQt 曲线数 | 512 条 | 1,024 条 |
| 1ms 内 AI 计算 | 64×3=192 次 FFT | 128×3=384 次 FFT |

**CrossAxisAnalyzer 的 bus_sag 检测器做 O(n²) Pearson 相关，128 轴时 8,128 对是 64 轴时的 4 倍。** 这比 EtherCAT 带宽更早成为瓶颈。

---

## 四、Beckhoff 为什么能"无限"？

Beckhoff TwinCAT 没有硬编码轴数上限。原理：

### 4.1 多帧/cycle

一个 DC 周期内可以发多个 Ethernet frame：

```
一个 1ms DC 周期:
  Frame 1 (1518B): Slave 0..63   的 PDO
  Frame 2 (1518B): Slave 64..127 的 PDO
  Frame 3 (1518B): Slave 128..191 的 PDO
  ...

条件: 所有帧的总传输时间 < DC 周期
```

### 4.2 Jumbo Frame

9000 bytes MTU → 8968 bytes 有效载荷 → 约 389 轴单帧。需要全网卡/交换机支持。

### 4.3 并非真正"无限"

Beckhoff 不设软件上限，但物理定律自动限制：

> 你选 1ms DC 周期 → 比 100μs 周期多带 10 倍的轴
> 你选 100Mbps 以太网 → 比 1Gbps 少带 10 倍的轴
> **这个 tradeoff 是物理决定的，不是软件写的。**

---

## 五、本项目突破 64 轴的方案

| 方案 | 上限 | 代价 |
|------|------|------|
| Jumbo Frame (9KB MTU) | ~250 轴 | 全网卡/交换机需支持 9K MTU |
| 多帧/cycle (标准 MTU×N) | ~200 轴 (SOEM EC_MAXSLAVE) | 增加周期占用时间 |
| 降低通道数 (4ch/轴) | 128 轴 (标准帧) | 减少监控信号 |
| 降低采样率 (100Hz) | 200 轴 | 失去高频细节 |
| 改 SOEM `EC_MAXSLAVE 200→400` | 400 轴 | 重新编译 SOEM, 内存翻倍 |

---

## 六、示波器如何读取 EtherCAT 数据（不干扰总线）

### 6.1 会不会干扰运动控制？

**不会。** 前提：示波器与运动控制器**共享同一个 Master 实例**，而不是各自创建 Master。

```
❌ 错误做法 — 双 Master 冲突:

运动控制器 (Master A) ──→ NIC eth0 ──→ Slave0, Slave1, Slave2...
示波器 (Master B)       ──→ NIC eth0 ──→ ❌ 两个 Master 抢同一条总线


✅ 正确做法 — 共享 Master:

Master (唯一实例) ──→ exchange() ──→ Domain Buffer (所有 slave 的 PDO)
                        ↑                  ↑
                  运动控制读/写        示波器只读 (read_pdo)

- 一个 NIC, 一个 Master 实例
- 示波器不发送任何帧 (不做 exchange)
- 只从 Domain Buffer 读取已存在的 PDO 数据
- 对总线零干扰
```

**但注意**：如果示波器也调用 `exchange()`，则与运动控制器的 `exchange()` 产生竞态。实际的正确做法：

```python
# 运动控制器线程 (负责 exchange)
while running:
    master.exchange()                    # ← 唯一的 exchange() 调用者
    motion_control_loop()
    # exchange 后 Domain Buffer 已更新

# 示波器线程 (只读)
while running:
    engine.read_from_domain_buffer()     # 只从已有 buffer 读取
    # 不调用 exchange()
```

当前项目中 `scope_engine.py` 调用了 `master.exchange()`，用于独立运行场景（没有外部运动控制器）。集成到实际运动控制系统时，需改用 passive 读取模式。

### 6.2 如何读取网络信息？从主站还是分别读各节点？

**全部从 Master 读取。** `scan()` 阶段已将所有 slave 的 SII 信息收集到 Master 内存中，不需要单独问每个 slave。

| 信息 | 来源 | 方式 | 需要 exchange? |
|------|------|------|:---:|
| **Slave 数量** | Master slave list | `ec_slavecount` 或 `slavecount` | 否 |
| **Slave 名称** (SII EEPROM) | Master 内存 | `ec_slave[].name` (scan 时读的) | 否 |
| **Vendor ID / Product Code** | SII EEPROM → Master 内存 | `ec_slave[].eep_man / eep_id` | 否 |
| **Slave 状态** (INIT/PREOP/SAFEOP/OP) | Master slave state | `ec_statecheck()` 或 `ec_slave[].state` | 否 |
| **PDO 数据** (Position, Current...) | Domain Buffer | `read_pdo()` / `read_scope()` | **是** |
| **DC 周期时间** | Slave DC 寄存器 0x0990 | SDO 读取 (mailbox, 非实时) | 否 |
| **DC 同步状态** | Slave DC flags | `ec_slave[].hasdc` + DC sync 标志 | 否 |
| **网络拓扑** | Master slave positions | `ec_slave[0..N-1]` 的位置顺序 | 否 |
| **PDO 映射** (TxPDO/RxPDO) | Slave SII → Master 内存 | `ec_slave[].Ibits / Obits` 或 SDO 读 0x1A00 | 否 |

读取流程：

```
Discover 阶段 (一次性, 低速, 通过 mailbox/SII):
  1. master.scan()        → 枚举所有 slave, 收集 SII EEPROM 到 ec_slave[]
  2. master.discover()    → 遍历 ec_slave[], 提取 vendor/product/name
  3. match_esi()          → 品牌匹配 (delta-a3 / yaskawa-sigma7 / ...)
  4. auto_name_axes()     → 分配轴名称 (X, Y, Z, A, B...)
  5. PDO 映射 (可选)      → SDO 读 0x1A00 (TxPDO mapping) 确认可用通道

实时采集阶段 (高频, 通过 Domain Buffer):
  exchange() → Domain Buffer 更新 → read_pdo(idx, slave=N)
  每轴 23 bytes, 8 个 CiA 402 通道
```

### 6.3 DC 周期信息读取

DC 周期由 Master 在 `go_operational()` 之前通过 SDO 写入参考时钟 slave 的 DC 寄存器。示波器可以从这些寄存器**反向读出**当前的 DC 配置：

```
参考时钟 slave 的 DC 寄存器 (通过 SDO):
  0x0990:0 — DC Sync Activation      (是否启用)
  0x0991:0 — Sync0 Cycle Time        (DC 周期, ns)
  0x0992:0 — Sync0 Shift Time        (偏移, ns)
  0x0990:1 — Sync1 Cycle Time
  0x0992:1 — Sync1 Shift Time
```

---

## 七、关键代码位置

| 组件 | 文件 | 行号 | 说明 |
|------|------|------|------|
| 轴数 UI 上限 | `scope_app.py` | 895 | `min(n_axes, 64)` |
| SOEM slave 上限 | `ethercatmain.h` | 60 | `#define EC_MAXSLAVE 200` |
| 帧数据区大小 | `ethercattype.h` | 80 | `#define EC_MAXLRWDATA (1518-14-2-10-2-4)` |
| IgH domain 注册 | `ec_master.py` | 499-562 | `configure_scope()` 所有轴共享 domain |
| 8ch PDO 定义 | `ec_master.py` | 385-394 | `SCOPE_PDO_ENTRIES` — 23 bytes/轴 |
| 多轴架构文档 | `multi-axis-architecture.md` | 10 | "1-64 axes" |

---

## 七、参考

- SOEM: `ethercattype.h` — EC_MAXECATFRAME, EC_MAXLRWDATA
- SOEM: `ethercatmain.h` — EC_MAXSLAVE = 200
- IgH EtherCAT Master 1.5.2: `ecrt.h` — domain 注册 API
- Beckhoff ETG.1000.4: EtherCAT Data Link Layer specification
- IEEE 802.3: Ethernet frame format, MTU definition
