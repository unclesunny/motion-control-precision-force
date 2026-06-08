# Sim / Discover 模式切换 — 实施方案

> 创建: 2026-06-07 | 关联: `scope_app.py`, `scope_engine.py`, `discover.py`, `ROADMAP.md` Phase 1.9

---

## 一、目标

示波器启动时默认探测真实硬件，无硬件时提示用户选择：

| 模式 | 优先级 | 说明 | 数据源 | 网络要求 |
|------|--------|------|--------|---------|
| **Discover** | **默认** | 物理连接，真实 EtherCAT | `master.exchange()` → Domain Buffer | 至少 1 台 EtherCAT slave |
| **Sim** | 用户选择 | 模拟仿真，虚拟波形 | `_generate_demo_values()` | 无 |

工程师在启动时看到硬件状态，无硬件时必须手动选择 Sim 或退出，不允许静默降级。

---

## 二、UI 设计

```
┌─────────────────────────────────────────────────────────────┐
│  Servo Oscilloscope — 3 Axes               [Sim ⬤] [🔍 Discover] │
├──────────┬──────────────────────────────────────────────────┤
│ Axes     │                                                  │
│ ▸ Motion │              Waveform Plot                       │
│   X      │                                                  │
│   Y      │                                                  │
│   Z      │                                                  │
│ ▸ Diag   │                                                  │
│          │                                                  │
├──────────┼──────────────────────────────────────────────────┤
│ Controls │  Stats  │  AI  │  Cross-Axis                    │
├──────────┴──────────────────────────────────────────────────┤
│ Mode: ● Sim (synthetic)  │ FPS: 381  │ Samples: 12,345    │
└─────────────────────────────────────────────────────────────┘
```

工具栏：
- 启动时自动进入 Discover 扫描流程（默认行为）
- `[🔍 Discover]` 按钮 — 亮绿色 = 当前在 Discover 模式，点击重新扫描
- `[Sim ⬤]` 按钮 — 切换到模拟模式（橙色 = 当前在 Sim 模式）
- 状态栏最左侧显示当前模式 + 连接状态

**无硬件时的提示对话框：**

```
┌──────────────────────────────────────────┐
│  ⚠ No EtherCAT Hardware Detected         │
│                                           │
│  No EtherCAT-compatible NIC found or      │
│  no slaves responded on the bus.          │
│                                           │
│  Check:                                   │
│   • Npcap/WinPcap installed               │
│   • NIC connected to servo drives         │
│   • Servo drives powered on               │
│                                           │
│     [Run in Sim Mode]    [Exit]           │
└──────────────────────────────────────────┘
```

Discover 扫描中显示进度：
```
┌──────────────────────────────────┐
│  Scanning EtherCAT Bus...        │
│  ████████████░░░░░░  3/5 slaves  │
│  ✓ Slave 0: Delta ASDA-A3-E     │
│  ✓ Slave 1: Delta ASDA-A3-E     │
│  ✓ Slave 2: Delta ASDA-A3-E     │
│  ⏳ Slave 3: reading SII...      │
│  ⏳ Slave 4: pending             │
└──────────────────────────────────┘
```

---

## 三、状态机

```
                        启动
                         │
                         ▼
              ┌──────────────────┐
              │  SCANNING        │  (默认行为 — 总是先尝试真实硬件)
              │  1. detect NIC   │
              │  2. master.scan()│
              │  3. discover()   │──→ 失败 ──→ ┌──────────────────────┐
              │  4. auto_name()  │             │  No EtherCAT found    │
              └──────┬───────────┘             │  ┌──────┐ ┌────────┐ │
                     │ 成功                     │  │ Sim  │ │  Exit  │ │
                     ▼                         │  └──┬───┘ └───┬────┘ │
              ┌──────────────────┐             └─────┼─────────┼──────┘
              │  DISCOVER        │                   │         │
              │  - 真实 PDO 采集 │         用户选 Sim│         │选 Exit
              │  - 树节点 = 扫描 │                   ▼         ▼
              │    结果          │          ┌─────────┐   应用退出
              └────┬─────────────┘          │   SIM   │
                   │                        │ (合成)  │
     用户点击 [Sim] │                        └────┬────┘
                   │                             │
                   ▼                             │
     ┌─────────────────────────┐                 │
     │  保存状态:              │                 │
     │  1. scope_axes.json     │                 │
     │  2. last_waveform.npz   │                 │
     │  3. session_meta.json   │                 │
     └─────────┬───────────────┘                 │
               │                                 │
               ▼                                 │
         回到 SIM 模式 ◄──────────────────────────┘
         (加载刚才保存的数据继续显示)
```

关键设计原则：
- **启动即 Discover** — 不经过 SIM，直接探测硬件
- **失败不静默** — 弹出明确的选择对话框，不允许无感知降级
- **Sim 是用户主动选择** — 只有工程师点击 "Sim" 按钮才进入模拟模式

---

## 四、启动流程 — Discover 优先

```python
def start_scope(self):
    """示波器启动 — 默认走 Discover，失败则提示 Sim/Exit"""
    success = self._try_discover()
    if not success:
        # 弹对话框让用户选择
        choice = self._prompt_no_hardware()
        if choice == "sim":
            self._enter_sim_mode(load_saved_state=False)
        else:
            self.app.quit()
            return

def _try_discover(self) -> bool:
    """尝试连接真实 EtherCAT 硬件。成功返回 True，失败返回 False。"""
    # 1. 检测 NIC
    try:
        adapter = self._detect_ethercat_adapter()
        if adapter is None:
            return False  # 不是异常 — 就是没硬件
        
        master = EcMaster(adapter=adapter)
        master.scan()
    except Exception:
        return False
    
    # 2. 发现 slave
    slaves = master.discover()
    if not slaves:
        master.close()
        return False
    
    # 3. 匹配 ESI + 自动命名
    axes_cfg = auto_name_axes(slaves)
    save_axis_config(axes_cfg)
    
    # 4. 重建示波器 (Discover 模式)
    self._rebuild_with_axes(axes_cfg, master=master, sim=False)
    
    # 5. 读取主站信息面板
    self._update_master_info(master)
    return True

def _prompt_no_hardware(self) -> str:
    """弹出无硬件提示，返回 'sim' 或 'exit'"""
    msg = QMessageBox(self)
    msg.setWindowTitle("No EtherCAT Hardware Detected")
    msg.setIcon(QMessageBox.Warning)
    msg.setText("No EtherCAT-compatible NIC found or\n"
                "no slaves responded on the bus.")
    msg.setInformativeText(
        "Check:\n"
        "  • Npcap/WinPcap installed\n"
        "  • NIC connected to servo drives\n"
        "  • Servo drives powered on")
    btn_sim = msg.addButton("Run in Sim Mode", QMessageBox.AcceptRole)
    btn_exit = msg.addButton("Exit", QMessageBox.RejectRole)
    msg.exec()
    
    if msg.clickedButton() == btn_sim:
        return "sim"
    return "exit"
```

### 4.1 NIC 自动检测

```python
def _detect_ethercat_adapter(self) -> Optional[str]:
    """Auto-detect available EtherCAT NIC."""
    if sys.platform == "win32":
        # SOEM on Windows: pcap device names
        try:
            from ec_master import _SOEM
            if _SOEM and _SOEM.available:
                adapters = _SOEM.ec_find_adapters()  # SOEM API
                for ad in adapters:
                    if ad.is_ethernet and ad.link_up:
                        return ad.name  # e.g. "\Device\NPF_{GUID}"
        except Exception:
            pass
    else:
        # Linux: check /sys/class/net/eth*/carrier
        for iface in Path("/sys/class/net").iterdir():
            carrier = iface / "carrier"
            if carrier.exists() and carrier.read_text().strip() == "1":
                return iface.name  # e.g. "eth0"
    return None
```

### 4.2 主站信息面板

```python
def _update_master_info(self, master):
    """更新主站信息显示"""
    info = {
        "master_type": "SOEM" if master._backend else "N/A",
        "adapter": master.adapter,
        "slave_count": master.slavecount,
        "is_operational": master._backend._state == EC_STATE_OPERATIONAL,
        "dc_cycle_us": None,  # 需要从 slave SDO 读取 0x0991
    }
    
    # 尝试读取 DC 周期 (从参考时钟 slave 的 SDO)
    if master.slavecount > 0:
        ok, dc_cycle_ns = master.sdo_read(0x0991, 0, slave=1)
        if ok and dc_cycle_ns:
            info["dc_cycle_us"] = dc_cycle_ns / 1000.0
            info["dc_frequency_hz"] = 1_000_000 / info["dc_cycle_us"]
    
    # 更新 UI
    self.master_info_panel.update(info)
```

---

## 五、Discover → Sim 切换时保存状态

用户点击 `[Sim ⬤]` 按钮从 Discover 切换到 Sim：

```python
def _enter_sim_mode(self, load_saved_state=True):
    """从 Discover 切换到 SIM 模式"""
    # 1. 保存当前最后一帧波形
    if hasattr(self, '_engine') and self._engine:
        for aid in self._engine.axis_ids:
            data, ts = self._engine.get_waveform(n_samples=60000, axis_id=aid)
            np.savez_compressed(
                f"last_waveform_{aid}.npz",
                data=data, timestamps=ts,
                axis_id=aid,
                timestamp=datetime.now().isoformat()
            )
    
    # 2. 保存当前拓扑配置 (如果还没存)
    save_axis_config(self._axes_cfg)
    
    # 3. 保存会话元数据
    session_meta = {
        "mode": "sim",
        "switched_at": datetime.now().isoformat(),
        "previous_axes": [ax["id"] for ax in self._axes_cfg],
        "previous_slave_count": self._engine.axis_count if self._engine else 0,
    }
    with open("session_meta.json", "w") as f:
        json.dump(session_meta, f, indent=2)
    
    # 4. 关闭 Master 连接
    if hasattr(self, '_master') and self._master:
        self._master.close()
        self._master = None
    
    # 5. 重建为 Sim 模式
    if load_saved_state and self._axes_cfg:
        # 从 Discover 切过来 — 加载刚才保存的数据
        self._rebuild_with_axes(self._axes_cfg, master=None, sim=True)
    else:
        # 无硬件直接进 Sim — 生成默认 demo 轴
        self._rebuild_demo_axes(master=None)
```

注意 `load_saved_state` 参数：
- `True` (默认): 用户从 Discover 手动切到 Sim — 保存了真实拓扑和波形，回放
- `False`: 启动时无硬件，用户选 Sim — 没有保存状态，生成 demo 轴

---

## 六、被动读取模式 (Passive Read)

用于示波器与运动控制器共享 Master 的场景。ScopeEngine 不调用 `exchange()`，只从已有的 Domain Buffer 读取。

```python
# scope_engine.py — 新增 passive 参数
class ScopeEngine:
    def __init__(self, master, sample_rate_hz=1000, passive=False):
        ...
        self._passive = passive  # True: 不调 exchange, 只读
    
    def _loop(self):
        while self._running:
            if not self._passive:
                self.master.exchange()  # 独立模式才调
            
            # 读取数据 (两种模式都走这里)
            for axis in self._axes_config:
                values = []
                for idx in self._active_indices:
                    val = self.master.read_pdo(idx, 0, slave=axis["slave_position"])
                    values.append(float(val) if val is not None else 0.0)
                self._buffers[axis["id"]].append(values, elapsed)
            
            if self._passive:
                time.sleep(self.period_ms / 1000.0)  # 被动等
            else:
                dt = (time.perf_counter() - t0) * 1000
                if dt < self.period_ms:
                    time.sleep((self.period_ms - dt) / 1000.0)
```

---

## 七、连线断开保护

```python
class ScopeEngine:
    def _loop(self):
        consecutive_errors = 0
        while self._running:
            try:
                if not self._passive:
                    wkc = self.master.exchange()
                    if wkc <= 0:  # WorkCounter = 0 → 总线异常
                        consecutive_errors += 1
                    else:
                        consecutive_errors = 0
                
                if consecutive_errors > 100:  # 100ms 连续异常
                    self._signal_disconnect()  # emit signal → UI 弹提示
                    break  # 停止采集
                    
            except Exception as e:
                consecutive_errors += 1
                if consecutive_errors > 10:
                    self._signal_disconnect()
                    break
    
    def _signal_disconnect(self):
        """通知 UI：连接丢失"""
        self._running = False
        # Qt signal → main thread
        self.disconnected.emit({
            "message": "EtherCAT connection lost. Switching to SIM mode.",
            "last_sample": self._sample_count,
            "timestamp": time.time(),
        })
```

---

## 八、改动文件清单

| 文件 | 改动 | 工作量 |
|------|------|--------|
| `scope_app.py` | +150 行 — Sim/Discover 切换、工具栏、状态栏、进度对话框 | 4h |
| `scope_engine.py` | +40 行 — `passive` 参数、断线检测、disconnect signal | 2h |
| `discover.py` | +30 行 — `detect_adapter()` NIC 自动检测 | 1h |
| `ec_master.py` | +20 行 — `scan(adapter=...)` 传递 adapter、主站信息导出 | 0.5h |
| `scope_server.py` | +10 行 — Web 前端模式显示 | 0.5h |
| `scope_tk.py` | +30 行 — tkinter 版 Sim/Discover 切换 | 1h |
| **合计** | **~280 行** | **~9h (1.5 天)** |

---

## 九、命令行接口

```bash
# 默认 — 启动即 Discover，无硬件则交互式提示 Sim/Exit
servo -c "scope"

# 跳过 Discover，直接进入 Sim 模式
servo -c "scope --sim"

# Discover 模式 + 指定 NIC
servo -c "scope --adapter eth0"

# Sim 模式 + 自定义轴数
servo -c "scope --sim --axes 6"

# 非交互模式 — 无硬件直接退 (CI/脚本)
servo -c "scope --no-interactive"          # 无硬件 → exit 1
servo -c "scope --no-interactive --sim"    # 无硬件 → 自动 fallback Sim
```
