# EtherCAT 網絡設備分類、非侵入式掃描與網絡診斷

> 創建: 2026-06-08 | 關聯: `discover.py`, `VENDOR_TO_BRAND`, `sim-discover-mode.md`

---

## 一、EtherCAT 設備全分類

### 1.1 伺服驅動器 (Servo Drive) — CoE / CiA 402

**可監控性: ✅ 完全支持** (8 CiA 402 通道)

| 製造商 | 型號系列 | Vendor ID | 狀態 | ESI 庫中有? |
|--------|---------|-----------|------|:---:|
| **Delta (台達)** | ASDA-A3-E, A2-E, B3-E | 0x000001DD | 量產 | ✅ |
| **Yaskawa (安川)** | Σ-7 (SGD7S), Σ-5 (SGDV) | 0x00000083 | 量產 | ✅ |
| **Panasonic (松下)** | MINAS A6B, A6S, A5B | 0x0000006A / 0x00000634 | 量產 | ✅ |
| **Inovance (匯川)** | SV660, SV630, SV820 | — | 量產 | ✅ |
| **Estun (埃斯頓)** | ProNet, ProNet Plus | 0x00000168 | 量產 | ✅ |
| **INVT (英威騰)** | DA200, DA180 | 0x0000004B | 量產 | ✅ |
| **Leadshine (雷賽)** | DM3E, CL3-EC, 2CL3-EC | 0x0000060A / 0x000008B6 | 量產 | ✅ |
| **Elmo** | Gold, Gold Solo, Platinum | 0x00000539 / 0x00000911 | 量產 | ✅ |
| **Servotronix** | CDHD, CDHD2 | 0x0000009A | 量產 | ✅ |
| **Lenze (倫茨)** | i700, i950 | 0x000001B9 | 量產 | ✅ |
| **Mitsubishi (三菱)** | MR-J4-GF, MR-J5-G, MR-JE-C | 0x00000086 | 量產 | ⬜ 需新增 |
| **Siemens (西門子)** | Sinamics S210, S120 (CU320) | 0x0000000A | 量產 | ⬜ 需新增 |
| **Bosch Rexroth** | IndraDrive Cs, ML, Mi | 0x00000051 | 量產 | ⬜ 需新增 |
| **Kollmorgen** | AKD, AKD2G, S700 | 0x000002BE | 量產 | ⬜ 需新增 |
| **Parker** | P-Series, Compax3 | 0x000002E1 | 量產 | ⬜ 需新增 |
| **Schneider Electric** | Lexium 32, 52, 62 | 0x00000054 | 量產 | ⬜ 需新增 |
| **ABB** | MotiFlex e180, MicroFlex | 0x00000042 | 量產 | ⬜ 需新增 |
| **Omron (歐姆龍)** | Accurax G5, 1S-series | 0x00000083¹ / 0x0000066F | 量產 | ⬜ 需新增 |
| **Fuji Electric** | ALPHA5 Smart Plus | 0x00000069 | 量產 | ⬜ 需新增 |
| **Sanyo Denki** | R-ADVANCED, SANMOTION | 0x00000044 | 量產 | ⬜ 需新增 |
| **CKD** | ABSODEX, DD Motor | 0x00000021 | 量產 | ⬜ 需新增 |
| **Oriental Motor** | AZE, ARLE | 0x00000319 | 量產 | ⬜ 需新增 |
| **Beckhoff** | AX5000, AX8000, EL7201 | 0x00000002 | 量產 | ⬜ 需新增 |
| **Hiwin (上銀)** | D2, D3 | — | 量產 | ⬜ 需新增 |
| **Teco (東元)** | JSDE, JSDG2 | — | 量產 | ⬜ 需新增 |
| **Shihlin (士林)** | SDM-C | — | 量產 | ⬜ 需新增 |
| **Danfoss** | VLT ISD 410 | 0x000000B1 | 量產 | ⬜ 需新增 |

¹ Omron 與 Yaskawa 共用部分 Vendor ID（歷史原因）

### 1.2 變頻器 (VFD / Inverter) — CoE / CiA 402 或 Drive Profile

**可監控性: ⚠️ 部分支持** (有 PDO 但非標準 CiA 402 8ch)

| 製造商 | 型號 | Vendor ID | 常見 PDO | 可監控通道 |
|--------|------|-----------|---------|:---:|
| **Delta** | VFD-E-C, C2000 | 0x000001DD | Speed, Current, DC Bus V | 3-5 |
| **Yaskawa** | GA500, GA700, U1000 | 0x00000083 | Speed, Current, Power | 3-5 |
| **ABB** | ACS880, ACS580, ACS380 | 0x00000042 | Speed, Torque, DC V | 3-5 |
| **Siemens** | Sinamics G120, G120X | 0x0000000A | Speed, Current, Status | 4-6 |
| **Danfoss** | FC-302, FC-280 | 0x000000B1 | Speed, Torque, Power | 3-4 |
| **Schneider** | ATV340, ATV630, ATV930 | 0x00000054 | Speed, Current | 3-4 |
| **Lenze** | i550, i950 | 0x000001B9 | Speed, Torque, Current | 4-5 |
| **INVT** | GD20-EC, GD350 | — | Speed, Current, DC V | 3-4 |
| **Hitachi** | WJ200, NE-S1 | — | Speed, Current | 3 |

**與伺服驅動器的差異**：VFD 的 CoE 對象字典結構不同，CiA 402 對象不全（通常沒有 0x6064 Position，沒有 0x60F4 Following Error）。需要單獨的 PDO 映射配置。

### 1.3 I/O 模塊 (Bus Coupler + I/O Terminal)

**可監控性: ⚠️ 僅 DIO 點位** (無 CiA 402, 只有 Digital/Analog I/O)

| 製造商 | 系列 | Vendor ID | PDO 類型 |
|--------|------|-----------|---------|
| **Beckhoff** | EK1100 + EL1004/EL2004/EL3064/EL4004... | 0x00000002 | Digital IN/OUT, Analog IN/OUT |
| **Beckhoff** | EP (IP67) | 0x00000002 | 同上 |
| **Wago** | 750-3xx (EtherCAT coupler + I/O) | 0x00000021 ? | Digital/Analog |
| **Omron** | NX-ECC + NX-I/O | 0x00000083 | Digital/Analog |
| **Phoenix Contact** | Axioline AXL E | — | Digital/Analog |
| **Weidmüller** | u-remote | — | Digital/Analog |
| **Murrelektronik** | MVK Pro | — | Digital/Analog |
| **Balluff** | BNI ECT | 0x00000556 | Digital IO-Link |
| **SMC** | EX260-SEC | 0x00000588 | Digital (valve manifold) |
| **Festo** | CPX-AP-I-EC | — | Digital/Analog |

**示波器視角**：I/O 模塊提供 Digital 狀態和 Analog 數值，可以用示波器監控，但無 CiA 402 的 8 通道標準佈局。需要按 slave 的 PDO mapping 動態生成通道。

### 1.4 編碼器 / 位置傳感器 (Encoders)

**可監控性: ⚠️ 部分支持** (有 PDO 但通常是單通道或雙通道)

| 製造商 | 型號 | Vendor ID | 典型 PDO |
|--------|------|-----------|---------|
| **Hengstler** | ACURO-XE | — | Position (32/64bit), Velocity |
| **Kübler** | Sendix F5888 | — | Position, Speed |
| **Baumer** | EAM/EAL580 | — | Position, Status |
| **SICK** | AFS/AFM60 | — | Position, Velocity |
| **POSITAL** | EtherCAT Kit | — | Position, Velocity, Temperature |
| **Heidenhain** | EnDat/EtherCAT gateway | — | 需經 gateway |

**示波器視角**：編碼器的 PDO 以 Position（位置）為主，通常只有 1-3 個通道。可以監控，通道數少。

### 1.5 傳感器 / 測量設備

**可監控性: ⚠️ 視設備而定**

| 類型 | 接口方式 | 出現在 EtherCAT 總線? |
|------|---------|:---:|
| **力傳感器** (Load Cell) | 經 I/O 模塊 (0-10V → EL3064) 或專用 EtherCAT 模塊 (EL3356) | ❓ 經 I/O |
| **扭矩傳感器** | ETHERCAT DRIVE 內部 (0x6077) 或專用模塊 | ✅ 已在伺服內 |
| **溫度傳感器** (TC/RTD) | 經 Beckhoff EL3314/EL3204 等溫度 I/O | ❓ 經 I/O |
| **振動傳感器** (Accelerometer) | 經 EL3632 (IEPE) 或專用模塊 | ❓ 經 I/O |
| **壓力傳感器** | 經 EL3064 (4-20mA) 或 IO-Link Master | ❓ 經 I/O |
| **流量傳感器** | IO-Link 或專用 EtherCAT 模塊 | ❓ 經 I/O |

**關鍵點：大部分傳感器不直接接 EtherCAT。它們經由 I/O 模塊（類比輸入）或 IO-Link Master 進入 EtherCAT 網絡。** 示波器看到的 PDO 來自 I/O 模塊，而非傳感器本身。

### 1.6 視覺系統 (Vision / CCD)

**典型架構：雙通道分離**

```
                    ┌─ EtherCAT (控制/同步) ──── 觸發、時間戳、狀態、結果
    PC/Master ──────┤
                    └─ GigE Vision / USB3 / Camera Link (圖像數據) ──── 圖像流
```

這種架構非常普遍——EtherCAT 的 100Mbps 帶寬不適合傳圖像，但它的 DC 同步精度 (<1μs) 非常適合做多相機觸發和時間戳對齊。

| 製造商 | 型號 | 高速通道 | EtherCAT 功能 | 可監控? |
|--------|------|---------|--------------|:---:|
| **Cognex** | In-Sight 7000/9000 | GigE Vision | Trigger、Timestamp、Inspection Result (Pass/Fail)、Status | ⚠️ PDO 可見 |
| **Cognex** | DataMan 370/470 | GigE Vision | Trigger、Result、Status | ⚠️ PDO 可見 |
| **Keyence** | CV-X400 + CA-EC | 專用高速總線 | Trigger、Result (OK/NG)、Encoder Position | ⚠️ PDO 可見 |
| **Keyence** | XG-X | 專用高速總線 | Trigger Sync、Result | ⚠️ PDO 可見 |
| **Basler** | ace 2 Pro (EtherCAT) | GigE Vision | Precision Time Protocol (PTP) via EtherCAT DC | ⚠️ PDO: Timestamp |
| **Baumer** | VEXG-xxM (EtherCAT) | GigE Vision | DC Timestamp Sync、Trigger、Exposure Control | ⚠️ PDO 可見 |
| **FLIR** | Oryx (EtherCAT) | 10GigE | DC Sync、Trigger | ⚠️ PDO 可見 |
| **Datalogic** | MX-E 系列 | 專用總線 | Trigger、Result、Status | ✅ 全 EtherCAT |
| **Matrox** | Iris GTR | GigE Vision | DC Timestamp、Trigger、I/O | ⚠️ PDO 可見 |
| **LMI Technologies** | Gocator 3D | GigE Vision | Trigger、Encoder、Result (Pass/Fail) | ⚠️ PDO 可見 |
| **SICK** | Ranger3 | GigE Vision | Trigger、Encoder、Timestamp | ⚠️ PDO 可見 |
| **Teledyne DALSA** | Linea (EtherCAT) | GigE Vision | Trigger Sync、Encoder | ⚠️ PDO 可見 |

**示波器能做什麼：**

```
相機在 EtherCAT 總線上的 PDO 通常包含:
  ├─ Trigger Counter      (相機觸發計數)
  ├─ Timestamp            (DC 同步時間戳)
  ├─ Exposure Status      (曝光狀態)
  ├─ Inspection Result    (OK/NG — 對 AI 分析極有價值!)
  ├─ Encoder Position     (觸發時的編碼器位置)
  └─ Error Code           (通訊/曝光錯誤)

示波器可以監控這些 PDO:
  - 關聯 Trigger Counter ↔ 軸位置 (知道你拍照時軸在什麼位置)
  - 關聯 Inspection Result ↔ 力/電流曲線 (知道 NG 時伺服在幹嘛)
  - 監控 Trigger 頻率 vs DC 周期 (觸發是否穩定)
```

**核心價值**：示波器不需要看圖像。它看 EtherCAT 側的時序信號，能診斷「拍照時刻是否與運動軌跡對齊」——這在 3C 點膠機的視覺對位中非常關鍵。

### 1.7 通訊網關 (Gateway)

**可監控性: ⚠️ 僅網關自身狀態，不透明傳輸後端設備數據**

| 製造商 | 型號 | 後端協議 | Vendor ID |
|--------|------|---------|-----------|
| **HMS / Anybus** | EtherCAT Slave Gateway | Modbus RTU/TCP, PROFIBUS, CANopen | 0x0000005A |
| **Hilscher** | netX 90 | 任意協議 (可編程) | 0x00000044 |
| **Beckhoff** | EL6023 (Serial), EL6731 (PROFIBUS) | Serial, PROFIBUS | 0x00000002 |
| **Moxa** | MGate 5114 | Modbus RTU ↔ EtherCAT | — |
| **ICP DAS** | ECAT-2610 | Modbus RTU ↔ EtherCAT | — |

**示波器視角**：網關本身有 PDO 數據，但其"後端"設備（Modbus 網絡上的 VFD 等）在 EtherCAT 側是不可見的。只能監控網關的 EtherCAT 側數據。

### 1.8 安全控制器 (Safety)

| 製造商 | 型號 | 協議 | Vendor ID |
|--------|------|------|-----------|
| **Beckhoff** | EL6900, EL6910 | FSoE (Safety over EtherCAT) | 0x00000002 |
| **SICK** | Flexi Soft | FSoE | — |
| **Pilz** | PNOZ m EF | FSoE | — |
| **Omron** | NX-SL | FSoE | 0x00000083 |
| **Schmersal** | PSC1 | FSoE | — |

**示波器視角**：安全設備使用 FSoE (Safety over EtherCAT) 協議，在標準 EtherCAT 幀中佔用獨立 datagram。示波器可以讀取安全模塊的狀態位，但不應嘗試修改安全參數。

### 1.9 液壓 / 氣動控制器

| 製造商 | 型號 | PDO | Vendor ID |
|--------|------|-----|-----------|
| **Bosch Rexroth** | IAC-R, HACD | Position, Force, Pressure | 0x00000051 |
| **Parker** | Compax3H, P-Series (液壓) | Position, Pressure | 0x000002E1 |
| **Moog** | E124-xxx | Position, Force, Pressure | — |
| **Festo** | CPX-E-CEC | Position, Pressure | — |
| **SMC** | JXCE1/EX260 | Position (stepper, servo-pneumatic) | 0x00000588 |

### 1.10 電源模塊 (Power Supply / DC Bus)

| 製造商 | 型號 | PDO | Vendor ID |
|--------|------|-----|-----------|
| **Delta** | PMC-D | DC Bus Voltage, Current, Temp | 0x000001DD |
| **Beckhoff** | EL9410 (power) | 無 PDO (純供電) | 0x00000002 |
| **Murrelektronik** | Emparro | DC OK, Current, Temp | — |
| **PULS** | CP10.241-ETC | Status, DC Voltage | — |

---

## 二、非侵入式掃描架構

### 2.1 掃描安全層級

```
Level 0 — 被動偵聽 (100% 安全, 不發任何幀)
  ├─ 打開 NIC 為混雜模式 (promiscuous)
  ├─ 監聽 1-2 秒
  ├─ 檢測 EtherCAT 幀 (EtherType = 0x88A4)
  │   ├─ 有幀 → 總線上已有 Master 運行中 → ⚠️ 警告, 拒絕連接
  │   └─ 無幀 → 進入 Level 1
  └─ 不寫入任何數據到總線

Level 1 — 被動識別 (安全, 只發 SII 讀取幀)
  ├─ ec_init() → 初始化 NIC 驅動
  ├─ ec_config_init(FALSE) → 讀 SII EEPROM, 不配置 PDO
  ├─ 遍歷 ec_slave[] 收集: vendor_id, product_code, name
  └─ 不進入 PRE_OP, 不配置任何 slave

Level 2 — 主動配置 (需確認, 會修改 slave 狀態)
  ├─ ec_config_map() → 配置 PDO 映射 (寫入 SM 和 FMMU)
  ├─ ec_configdc() → 配置 DC 時鐘 (可選)
  ├─ statecheck(PRE_OP) → statecheck(SAFE_OP) → statecheck(OP)
  └─ 開始 cyclic exchange()
```

### 2.2 代碼實現

```python
# discover.py — 新增函數

def passive_listen(adapter: str, timeout_s: float = 2.0) -> dict:
    """被動偵聽 EtherCAT 總線，檢測是否已有 Master 在運行。
    
    使用 libpcap/WinPcap 在混雜模式下捕捉 EtherCAT 幀，
    不對總線發送任何數據。
    
    Returns:
        {
            "has_master": bool,          # 檢測到 Master 幀
            "master_mac": str | None,   # Master MAC 地址
            "frame_count": int,         # 捕捉到的 EtherCAT 幀數
            "frame_period_us": float,   # 平均幀間隔 (推測 DC 周期)
            "detected_slaves": int,     # 從幀中推測的 slave 數量
            "wkc_healthy": bool,        # Working Counter 正常
            "safe_to_connect": bool,    # 可以安全連接
        }
    """
    try:
        import pcap  # libpcap Python wrapper
    except ImportError:
        # Fallback: 快速 ec_init + ec_config_init(False) 後立即關閉
        return _quick_scan_and_release(adapter)

    sniffer = pcap.pcap(name=adapter, promisc=True, immediate=True)
    # EtherCAT EtherType filter
    sniffer.setfilter("ether proto 0x88A4")

    frames = []
    deadline = time.time() + timeout_s

    for _, pkt in sniffer:
        if time.time() > deadline:
            break
        if len(pkt) < 14:
            continue
        # EtherCAT 幀: EtherType = 0x88A4
        eth_type = (pkt[12] << 8) | pkt[13]
        if eth_type == 0x88A4:
            frames.append({
                "ts": time.time(),
                "src_mac": pkt[6:12],
                "size": len(pkt),
                "wkc": (pkt[-6] << 8) | pkt[-5],  # Working Counter (最後 2 bytes 前)
            })

    if frames:
        intervals = [
            frames[i]["ts"] - frames[i-1]["ts"]
            for i in range(1, min(len(frames), 10))
        ]
        avg_interval_us = (
            sum(intervals) / len(intervals) * 1_000_000 if intervals else 0
        )
        # 推測 slave 數量 (WKC ≈ slave count)
        slave_estimate = max(f["wkc"] for f in frames)

        return {
            "has_master": True,
            "master_mac": frames[0]["src_mac"].hex(":"),
            "frame_count": len(frames),
            "frame_period_us": round(avg_interval_us),
            "detected_slaves": slave_estimate,
            "wkc_healthy": all(f["wkc"] == slave_estimate for f in frames),
            "safe_to_connect": False,  # 已有 Master → 不安全
        }
    else:
        return {
            "has_master": False,
            "master_mac": None,
            "frame_count": 0,
            "frame_period_us": None,
            "detected_slaves": 0,
            "wkc_healthy": False,
            "safe_to_connect": True,  # 無 Master → 安全
        }


def _quick_scan_and_release(adapter: str) -> dict:
    """沒有 pcap 庫時的備用方案：快速掃描後立即釋放 Master。"""
    from ec_master import EcMaster
    try:
        master = EcMaster(adapter=adapter)
        # ec_init 會檢查 NIC 狀態，但不發 EtherCAT 幀
        # ec_config_init(False) 發一個廣播幀讀取 slave 信息
        count = master.scan()
        master.close()
        return {
            "has_master": False,  # 無幀 → 無 Master
            "detected_slaves": count,
            "safe_to_connect": True,
        }
    except Exception as e:
        return {
            "has_master": False,
            "detected_slaves": 0,
            "safe_to_connect": True,
            "error": str(e),
        }
```

### 2.3 Discover 模式安全啟動流程

```python
def safe_discover(adapter: str = None) -> tuple:
    """安全的 Discover 流程。
    
    Returns:
        (master, axes_cfg, warnings) — master 為 None 表示無法安全連接
    """
    warnings = []
    
    # Step 1: 被動偵聽
    result = passive_listen(adapter, timeout_s=2.0)
    
    if result["has_master"]:
        warnings.append({
            "level": "critical",
            "message": (
                f"檢測到 EtherCAT Master 正在運行!\n"
                f"  Master MAC: {result['master_mac']}\n"
                f"  DC 周期推測: {result['frame_period_us']} μs\n"
                f"  Slave 數量: {result['detected_slaves']}\n"
                f"  總線狀態: {'正常' if result['wkc_healthy'] else '異常'}\n\n"
                f"⚠️ 為了避免破壞正在運行的運動控制系統，\n"
                f"   示波器不會連接到此總線。\n"
                f"   請在機器停機後再使用 Discover 模式。"
            ),
        })
        return None, None, warnings
    
    # Step 2: 安全 — 可以連接
    warnings.append({
        "level": "info",
        "message": "未檢測到 Master。示波器將以臨時 Master 模式進行掃描。"
    })
    
    # Step 3: 非侵入式掃描 (Level 1)
    master = EcMaster(adapter=adapter)
    master.scan()  # ec_config_init(FALSE) → 只讀 SII
    
    slaves = master.discover()
    
    if not slaves:
        warnings.append({
            "level": "warning",
            "message": "總線上未檢測到 EtherCAT 設備。請檢查設備電源和網線連接。"
        })
        master.close()
        return None, None, warnings
    
    # Step 4: 識別設備類型
    for s in slaves:
        s["device_type"] = classify_device_type(s)
        s["monitor_capability"] = assess_monitor_capability(s)
    
    axes_cfg = auto_name_axes(slaves)
    
    return master, axes_cfg, warnings
```

---

## 三、設備類型自動分類

```python
# discover.py — 新增

def classify_device_type(slave: dict) -> str:
    """根據 vendor_id, product_code, CoE profile 分類設備。
    
    Returns:
        "servo_drive" | "vfd" | "io_module" | "encoder" |
        "gateway" | "safety" | "power_supply" | "camera" |
        "hydraulic" | "unknown_coe" | "unknown_simple"
    """
    esi = slave.get("esi_match", {})
    vendor = slave["vendor_id"]
    product = slave["product_code"]
    
    # 1. 已知伺服品牌
    if esi.get("is_servo_drive"):
        return "servo_drive"
    
    # 2. 已知 VFD
    if vendor in VFD_VENDORS and product in VFD_PRODUCTS:
        return "vfd"
    
    # 3. 已知 I/O
    if vendor in IO_VENDORS:
        return "io_module"
    
    # 4. 已知安全設備
    if vendor in SAFETY_VENDORS:
        return "safety"
    
    # 5. 通過 ESI name 推斷
    name = slave.get("sii_name", "").upper()
    if "VFD" in name or "INVERTER" in name or "FREQ" in name:
        return "vfd"
    if "I/O" in name or "COUPLER" in name or "TERMINAL" in name:
        return "io_module"
    if "SAFETY" in name or "FSOE" in name:
        return "safety"
    if "GATEWAY" in name or "ANYBUS" in name or "NETX" in name:
        return "gateway"
    if "ENCODER" in name:
        return "encoder"
    if "POWER" in name or "PSU" in name or "SUPPLY" in name:
        return "power_supply"
    
    # 6. 有 CoE 但未知類型
    # (可後續通過 SDO 讀取 0x1000 Device Type 來區分)
    return "unknown_coe"


def assess_monitor_capability(slave: dict) -> dict:
    """評估該設備的示波器可監控能力。
    
    Returns:
        {
            "can_monitor": bool,
            "channel_count": int,        # 可監控的通道數
            "channel_source": str,       # "cia402" | "pdo" | "dio_only" | "none"
            "notes": str,
        }
    """
    device_type = slave.get("device_type", "unknown_coe")
    
    if device_type == "servo_drive":
        return {
            "can_monitor": True,
            "channel_count": 8,
            "channel_source": "cia402",
            "notes": "CiA 402 標準 8 通道 (Position/Velocity/Current/Torque/Foll.Err/DIO/Status/OpMode)",
        }
    elif device_type == "vfd":
        return {
            "can_monitor": True,
            "channel_count": 5,
            "channel_source": "pdo",
            "notes": "非 CiA 402 完整 profile，通道數取決於 manufacturer-specific PDO mapping",
        }
    elif device_type in ("io_module",):
        return {
            "can_monitor": True,
            "channel_count": "variable",
            "channel_source": "pdo",
            "notes": "PDO 為 Digital/Analog I/O 點位，非 CiA 402。需按 PDO mapping 動態佈局。",
        }
    elif device_type == "encoder":
        return {
            "can_monitor": True,
            "channel_count": 2,
            "channel_source": "pdo",
            "notes": "主要通道: Position, Velocity",
        }
    elif device_type == "gateway":
        return {
            "can_monitor": False,
            "channel_count": 0,
            "channel_source": "none",
            "notes": "網關設備本身無可用 PDO，後端設備不可見。僅顯示拓撲存在。",
        }
    elif device_type == "safety":
        return {
            "can_monitor": False,
            "channel_count": 0,
            "channel_source": "none",
            "notes": "安全模塊。可顯示狀態位，但不應修改參數。",
        }
    elif device_type == "power_supply":
        return {
            "can_monitor": True,
            "channel_count": 2,
            "channel_source": "pdo",
            "notes": "基本狀態: DC Bus Voltage, Current (如有 PDO)",
        }
    elif device_type == "camera":
        return {
            "can_monitor": False,
            "channel_count": 0,
            "channel_source": "none",
            "notes": "相機圖像數據不走 EtherCAT，僅同步信號。",
        }
    else:
        return {
            "can_monitor": False,
            "channel_count": 0,
            "channel_source": "none",
            "notes": "未知設備類型。可嘗試讀取 SDO 獲取 Device Type (0x1000) 後再分類。",
        }
```

---

## 四、網絡診斷報告

### 4.1 診斷輸出示例

```
===============================================================
  EtherCAT Bus Diagnostics
  2026-06-08 14:30:00
===============================================================

BUS STATUS:
  Mode:            Passive Listen (no transmit)
  Active Master:   NOT DETECTED — safe to connect
  NIC:             \Device\NPF_{GUID} (Intel I210)
  Link Speed:      100 Mbps / Full Duplex

TOPOLOGY (5 slaves discovered):
  Pos  Type        Vendor          Product         Name              Monitor
  ──────────────────────────────────────────────────────────────────────
  0    Servo       Delta Elec.     ASDA-A3-E       "Axis X"          8ch ✅
  1    Servo       Delta Elec.     ASDA-A3-E       "Axis Y"          8ch ✅
  2    Servo       Delta Elec.     ASDA-A3-E       "Axis Z"          8ch ✅
  3    I/O Module  Beckhoff        EK1100          "EK1100"          16ch ✅
  4    VFD         ABB             ACS880          "Spindle VFD"     4ch ⚠️

CAPABILITY SUMMARY:
  Full CiA 402 (8ch):   3 devices  → X, Y, Z axes
  Partial PDO:          1 device   → Spindle VFD (need custom PDO map)
  I/O only:             1 device   → EK1100 (digital I/O, no servo)
  Not monitorable:      0 devices

WARNINGS:
  ⚠️  Pos 4 (ABB ACS880): non-standard PDO mapping.
      Only 4/8 CiA 402 channels available.
      To add 8ch support, provide ESI XML file for this device.

  ⚠️  Pos 3 (Beckhoff EK1100): I/O coupler detected but no
      servo PDO. Use I/O monitor mode instead.

RECOMMENDATIONS:
  • 3 servo axes ready for oscilloscope monitoring.
  • To monitor VFD, load its ESI XML via: servo -c "params import <file>"
  • Bus appears healthy. No errors detected.
===============================================================
```

### 4.2 缺失 ESI 時的處理

當發現未知 vendor_id 或 product_code 時：

```
⚠️ Unknown Device Detected:
   Position:    4
   Vendor ID:   0x00000XXX (not in library)
   Product Code: 0x0000XXXX
   SII Name:    "Some Device Name"

   This device cannot be monitored with full CiA 402 channels.
   
   To add support:
   1. Find the ESI XML file in your drive manufacturer's software
      (e.g., C:\Program Files\...\ESI\)
   2. Import it:
      servo -c "esi import --file <path_to_esi.xml>"
   3. The device will then appear in the brand library with
      proper PDO mapping.

   Without ESI, the device will be shown in the topology tree
   but no waveform channels will be available.
```

---

## 五、ESI 導入機制（待實施）

```python
# discover.py — 新增

def import_esi_xml(xml_path: str) -> str:
    """從 ESI XML 文件導入設備定義。
    
    解析 ETG.2000 標準的 ESI XML:
      - <Vendor><Id> → vendor_id
      - <GroupType> → 設備類型
      - <RxPdo>/<TxPdo> → PDO 映射
      - <Dictionary> → 對象字典
    
    存入: 05-servo-params/imported/{vendor_id}_{product_code}.json
    """
    pass  # 待實施


# 通用 ESI 解析器已存在:
# 05-servo-params/extract_esi_generic.py — 支持 3 種格式
```

---

## 六、現有 Vendor ID 庫擴展需求

當前 `discover.py` 收錄了 20+ vendor ID 和 20+ product code。需要補充的：

| 優先級 | 類型 | 數量 | 說明 |
|:---:|------|:---:|------|
| 🔴 P0 | 伺服驅動器 vendor ID | ~15 | 三菱/西門子/Bosch/Kollmorgen/Parker/Schneider/ABB/Omron/Fuji/Sanyo/Hiwin/Teco/Shihlin/CKD/Oriental |
| 🟡 P1 | VFD vendor ID + product | ~10 | Delta VFD/Yaskawa/ABB/Siemens/Danfoss/Schneider/INVT/Hitachi |
| 🟡 P1 | I/O 模塊 vendor ID | ~8 | Beckhoff/Wago/Omron/Phoenix/Weidmüller/Murrelektronik/Balluff/SMC/Festo |
| 🟢 P2 | 編碼器/傳感器 | ~6 | Hengstler/Kübler/Baumer/SICK/POSITAL |
| 🟢 P2 | 安全設備 | ~4 | Beckhoff/SICK/Pilz/Omron/Schmersal |
| 🟢 P2 | 液壓/氣動 | ~4 | Bosch/Parker/Moog/Festo/SMC |
| 🟢 P2 | 網關 | ~3 | HMS/Hilscher/Moxa |
| 🟢 P2 | 電源模塊 | ~2 | Delta PMC/Weidmüller/Murrelektronik/PULS |

**方式**：你從各製造商的軟件安裝目錄中蒐集 ESI XML 文件（通常在 `C:\Program Files\...\ESI\` 下），放到 `05-servo-params/esi-import/`，然後用 `extract_esi_generic.py` 批量解析，自動擴充到 `brands.json`。
