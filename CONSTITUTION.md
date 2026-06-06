---
name: motion-control-constitution
description: Governing principles for the Precision Force Control project. All contributions must pass these gates.
---

# Motion Control — Precision Force Control Project Constitution

> 本宪法是项目最高治理文件。与同级 AI&ML Agent 项目共享知识，但独立治理。

## 第一条 — 项目身份

### 1.1 项目是什么

**基于 EtherCAT 的 3C 点胶机精密力控系统**，包含：
- EtherCAT 实时主站协议栈
- 多品牌伺服参数离线识别与自动配置
- 杀手级调试示波器 (8 通道, 10 kHz, AI 辅助分析)
- 力觉闭环自学习 (PPO 力控参数自动整定)
- CODESYS 功能块 (PLC 侧部署)

### 1.2 项目不是什么

- ❌ 万能运动控制器
- ❌ 通用 CNC 系统
- ❌ 机器人操作系统 (ROS)
- ❌ 纯学术研究项目

## 第二条 — 内容门禁 (G1-G5)

与 AI&ML Agent 项目 CONSTITUTION.md 保持一致：
- G1: 必须直接服务于精密力控/伺服调试/EtherCAT 通讯
- G2: 所有代码可运行 (`python xxx.py` 或 `gcc xxx.c`)
- G3: 不重复已有模块
- G4: 不接受空壳演示代码
- G5: CODESYS ST 含完整 FB 定义

## 第三条 — 同级项目知识共享规则

```
D:\GitHub\
├── AI&ML Agent\          ← 可读 (AI/ML 能力复用)
│   └── ...               ← 不可写 (独立治理)
│
├── motion-control-precision-force\  ← 本项目
│   └── ...
│
└── other-team-project\   ← 可读 (知识参考)
    └── ...               ← 不可写
```

- **读权限:** 可以引用同级项目的 KNOWLEDGE.md、Python 脚本、ST 代码
- **写权限:** 仅限本项目目录内
- **共享方式:** 通过 `../AI&ML Agent/` 相对路径引用，不拷贝代码

## 第四条 — 外部资源请求协议

当需要以下资源时，**必须停下来提示用户协调获取**，不得自行实现或猜测：

1. 闭源协议 SDK (松下 RTEX, 三菱 SSCNET)
2. 官方伺服参数手册 (完整对象字典)
3. 已存在的开源实现 (SOEM, IgH EtherCAT Master, LinuxCNC)
4. 硬件设备 (伺服驱动器, 力传感器,  EtherCAT 网卡)
5. 竞品软件 (PANATERM, ASDA-Soft, TwinCAT) 用于对比分析

提示格式:
```
🔴 需要外部资源: [资源名称]
   用途: [在这个项目中的具体用途]
   选项: [已知的可选方案]
   优先级: [P0/P1/P2]
```
