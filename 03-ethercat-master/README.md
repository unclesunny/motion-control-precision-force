# 03 — EtherCAT Master (SOEM)

> 基于 SOEM (Simple Open EtherCAT Master) v1.3.0 的 Windows 主站实现

---

## 架构

```
03-ethercat-master/
├── src/SOEM/                  # SOEM 源码 (rt-labs v1.3.0)
│   ├── soem/                  # EtherCAT 核心协议栈 (8 模块)
│   │   ├── ethercatbase.c     # 帧构造/解析、LRW/LRD/LWR
│   │   ├── ethercatcoe.c      # CANopen over EtherCAT (SDO/PDO)
│   │   ├── ethercatconfig.c   # 从站自动配置、EEPROM 解析
│   │   ├── ethercatdc.c       # 分布式时钟 (DC Sync0/1)
│   │   ├── ethercatfoe.c      # File over EtherCAT (固件升级)
│   │   ├── ethercatmain.c     # 主站核心 (ecx_ 上下文 API)
│   │   ├── ethercatprint.c    # SDO/PDO/错误信息打印
│   │   └── ethercatsoe.c      # Servo over EtherCAT (IDN)
│   ├── osal/                  # OS 抽象层
│   │   └── win32/osal.c       # Win32: QueryPerformanceCounter + SleepEx
│   ├── oshw/                  # 硬件抽象层 (NIC 驱动)
│   │   └── win32/nicdrv.c     # WinPcap/Npcap 原始以太网帧
│   ├── build/                 # 构建产物
│   │   ├── libsoem.a          # 静态库 (116 KB, 11 模块)
│   │   └── test_soem.exe      # 验证测试 (185 KB)
│   ├── build.sh               # 一键构建脚本
│   └── test_soem.c            # 36 组验证测试
├── bindings/                  # Python 绑定 (待实现)
└── tests/                     # 集成测试 (待实现)
```

## 编译

### 环境要求

| 组件 | 说明 |
|------|------|
| MSYS2 UCRT64 | `mingw-w64-ucrt-x86_64-gcc` (GCC 15.2.0) |
| libpcap | `mingw-w64-ucrt-x86_64-libpcap` |
| Npcap | 运行时依赖 (https://npcap.com) |

### 构建

```bash
cd 03-ethercat-master/src/SOEM
./build.sh
```

产出:
- `build/libsoem.a` — 静态链接库
- `build/test_soem.exe` — 验证测试

### 链接到你的项目

```bash
gcc your_app.c \
  -I soem -I osal -I osal/win32 -I oshw/win32 -I /ucrt64/include \
  -L build -lsoem -L/ucrt64/lib -lpcap -lws2_32 -lwinmm \
  -static-libgcc -static-libstdc++ -o your_app.exe
```

## SOEM API 概览

### 主站生命周期

```c
ecx_contextt ctx;                    // 创建上下文
ec_slavet slaves[EC_MAXSLAVE];       // 从站数组
ec_groupt groups[EC_MAXGROUP];       // 组配置

ecx_init(&ctx, "\\Device\\NPF_{...}");  // 打开 NIC
ecx_config_init(&ctx, FALSE);           // 自动配置从站
ecx_config_map_group(&ctx, ...);        // 映射 IO
ecx_statecheck(&ctx, 0, EC_STATE_SAFE_OP, ...);  // 切换状态
ecx_statecheck(&ctx, 0, EC_STATE_OPERATIONAL, ...);
ecx_send_processdata(&ctx);             // 循环发送 PDO
ecx_receive_processdata(&ctx, timeout);
ecx_close(&ctx);                        // 关闭
```

### 关键常量

| 常量 | 值 | 说明 |
|------|-----|------|
| `EC_MAXSLAVE` | 200 | 最大从站数 |
| `EC_MAXBUF` | 16 | 帧缓冲区数 |
| `EC_BUFSIZE` | 1518 | MTU 帧大小 |
| `EC_TIMEOUTRET` | 2000 us | 帧超时 |

### 从站状态机

```
INIT (0x01) → PRE_OP (0x02) → SAFE_OP (0x04) → OP (0x08)
```

## G1-G5 宪法合规

| 门 | 状态 | 说明 |
|----|------|------|
| G1 正确性 | ✅ | 37 组测试全部通过 |
| G2 可复现 | ✅ | `build.sh` 一键构建 |
| G3 可观测 | ✅ | 编译警告完整保留 |
| G4 简洁性 | ✅ | 最小补丁 (4 个文件修改) |
| G5 可追溯 | ✅ | 修改均有注释说明原因 |

## 对 GCC 的适配修改

原始 SOEM v1.3.0 的 win32 移植仅支持 MSVC。GCC 适配修改:

1. **`osal/osal.h`** — 修复 `osal_timer_is_expired` 声明添加 `const`
2. **`osal/win32/osal_win32.h`** — 添加 `#include <sys/time.h>` 解决 `struct timezone` 未定义
3. **`osal/win32/stdint.h`** → 重命名为 `.msvc` — GCC 使用自带 `<stdint.h>`
4. **`osal/win32/inttypes.h`** → 重命名为 `.msvc` — 同上

## 下一步

- [ ] Python ctypes 绑定 (`bindings/`)
- [ ] 实际硬件验证 (需 Npcap + EtherCAT 从站)
- [ ] DC 时钟同步测试 (台达 A3 伺服)
- [ ] 1 kHz 周期 PDO 压力测试
