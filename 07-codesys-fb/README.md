# CODESYS AI Servo Function Block Library

4 个可直接粘贴进 CODESYS IDE 的功能块，覆盖 EtherCAT 伺服的数据采集、力控、自适应增益、诊断。

## 文件清单

| 文件 | 功能 | 行数 |
|------|------|------|
| `FB_ServoScope.st` | PDO 数据采集 → 环形缓冲区 (8ch × 1000 samples) | ~130 |
| `FB_ForceControl.st` | 力/扭矩闭环控制 (6 状态机: Idle→Approach→Contact→Hold→Retract→Fault) | ~170 |
| `FB_GainScheduler.st` | 自适应增益调度 (4 工况区 × 线性插值 + EMA 平滑) | ~140 |
| `FB_ServoDiag.st` | 伺服诊断 (电流异常/跟踪误差/温度/磨损趋势) | ~180 |
| `DUT_ServoAI_Params.st` | 统一参数结构体 (所有 FB 的可调参数集中管理) | ~40 |

## 使用方法

### 1. 导入 CODESYS

在 CODESYS IDE 中:
- `POU` → 右键 → `Add Object` → `Function Block`
- 将 `.st` 文件内容粘贴到对应的 FB 中
- `DUT` → 右键 → `Add Object` → `DUT`
- 粘贴 `DUT_ServoAI_Params.st`

### 2. 在 PLC_PRG 中实例化

```
PROGRAM PLC_PRG
VAR
    aiParams    : DUT_ServoAI_Params;   // 参数结构体
    fbScope     : FB_ServoScope;        // 示波器采集
    fbForce     : FB_ForceControl;      // 力控闭环
    fbGain      : FB_GainScheduler;     // 增益调度
    fbDiag      : FB_ServoDiag;         // 伺服诊断
END_VAR
```

### 3. 映射 EtherCAT PDO

```
fbScope(
    iPosActual := %ID0,     // 0x6064 → PDO Input offset 0
    iVelActual := %ID4,     // 0x606C → PDO Input offset 4
    iCurActual := %ID8,     // 0x6078 → PDO Input offset 8
    iTrqActual := %ID10,    // 0x6077 → PDO Input offset 10
    bEnable := TRUE
);
```

## 与 AI&ML Agent 模块的对应关系

| CODESYS FB | AI&ML Agent 模块 |
|-----------|-----------------|
| FB_ServoDiag (电流异常) | Solution 02 — Servo Current Anomaly |
| FB_ServoDiag (故障诊断) | Solution 03 — Multi-Sensor Fault Diagnosis |
| FB_GainScheduler | Solution 01 — PPO PID Auto-Tuning |
| FB_ForceControl | AR4 — Solution Auto-Generator (力控场景) |

## 参数更新流程

```
边缘IPC: train → export params → Modbus TCP → PLC Holding Registers
    ↓
CODESYS: DUT_ServoAI_Params ← copy from Modbus registers
    ↓
FB instances: read from DUT_ServoAI_Params
```
