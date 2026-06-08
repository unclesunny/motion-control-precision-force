"""
Engineer Prompt Templates — multi-modal diagnostic checklists.

Each template maps an anomaly category to a structured prompt for the engineer.
Prompts are designed for multi-modal feedback:
  - text:  free-form description of what the engineer sees/hears/feels
  - image: photo of the mechanical component (coupling, bearing, guide rail, etc.)
  - audio: recording of machine sound during operation
  - video: short clip showing mechanical motion behavior

Template structure (per category):
    question:           Core diagnostic question in the engineer's language
    context_template:   Python format string — filled with annotation metadata
    suggested_checks:   Concrete inspection items with modality hints [可拍照] etc.
    expected_modalities: Which feedback channels to offer
    urgency_map:        severity -> urgency level

Design principle:
    "AI bridges what sensors can detect with what requires human sensory input."
    The engineer confirms/refines the AI's hypothesis with information the
    electrical signals cannot provide.
"""

from typing import Dict, List

# ── Ambiguous category prompts (need engineer observation first) ──────────

AMBIGUOUS_PROMPTS: Dict[str, dict] = {
    "current_wear": {
        "question": "电流持续漂移 — 疑似机械磨损。请现场检查并反馈观察结果：",
        "context_template": (
            "AI 检测：电流从 {baseline_mean:.0f}% 渐变漂移至 {current_value:.0f}%，"
            "持续 {consecutive_count} 采样周期。CUSUM 漂移检测器触发置信度 {confidence:.0%}。\n"
            "这通常意味着机械部件存在渐进磨损，但电信号无法定位具体部件。"
        ),
        "suggested_checks": [
            "【联轴器】是否有橡胶粉尘/碎屑？是否有目视可见的偏摆或不对中？[可拍照]",
            "【联轴器】用手转动电机轴（断电后），是否有松动/间隙感？[可输入感受]",
            "【丝杆/滚珠丝杆】运动时是否有异常噪音（咯噔声、啸叫声）？[可录音]",
            "【丝杆】螺母座是否有黑色粉末（润滑脂变质）？[可拍照]",
            "【轴承】电机/丝杆轴承座温度是否超过 60°C？（用手背试温或用测温枪）[可输入温度]",
            "【轴承】转动时是否有周期性振动或异响？[可录音]",
            "【皮带】（如适用）张力是否正常？皮带齿面是否有磨损？[可拍照]",
            "【导轨】滑块处是否有爬行/抖动现象？润滑是否充足？[可录视频]",
            "【其他】最近是否更换过机械部件或调整过安装？[可输入描述]",
        ],
        "expected_modalities": ["text", "image", "audio", "video"],
        "urgency_map": {"info": "routine", "warning": "soon", "critical": "immediate"},
        "refinement_prompt": (
            "工程师反馈：{response_text}\n"
            "观察确认：{selected_observation}\n"
            "基于以上机械检查结果，请将诊断从通用的'机械磨损'精化为具体的部件级诊断"
            "（例如：'联轴器弹性体磨损 — 建议更换' 或 '丝杆螺母润滑不足 — 建议补充润滑脂'），"
            "并给出对应的参数调整建议（如果需要临时补偿）。"
        ),
    },

    "tracking_mechanical_bind": {
        "question": "跟随误差与电流同步上升 — 疑似机械卡滞。请现场检查：",
        "context_template": (
            "AI 检测：跟随误差突然增大至 {error_value:.0f} 脉冲，"
            "同时电流上升至 {current_value:.0f}%，两者相关系数 {correlation:.2f}。\n"
            "此模式表明运动受阻（机械卡滞），但受阻原因需要人工判断。"
        ),
        "suggested_checks": [
            "【导轨】滑块/导轨润滑状态：是否干涩？导轨面是否有划痕/损伤？[可拍照]",
            "【导轨】手动推动负载（断电后），是否有明显阻力/卡顿点？[可输入描述]",
            "【丝杆】用千分表测量反向间隙是否超标？[可输入数值：___ μm]",
            "【防护罩/线槽】是否与运动部件干涉/刮擦？[可拍照]",
            "【负载】被驱动机构是否有卡死或过载？（如夹具未松开、工件卡住）[可拍照]",
            "【异物】导轨或丝杆上是否有切屑/异物？[可拍照]",
        ],
        "expected_modalities": ["text", "image", "audio"],
        "urgency_map": {"info": "soon", "warning": "immediate", "critical": "immediate"},
        "refinement_prompt": (
            "工程师反馈：{response_text}\n"
            "观察确认：{selected_observation}\n"
            "基于以上检查结果，精化诊断为具体的卡滞原因（导轨润滑不足/丝杆间隙/异物干涉等），"
            "并给出针对性的修复建议。"
        ),
    },
    # ── Cross-axis ambiguous ──
    "cross_bus_sag": {
        "question": "多个轴同时掉电 — 疑似供电不足。请现场检查：",
        "context_template": (
            "AI 检测到 {drop_count}/{n_axes} 个轴同时出现电流下降（平均下降 {avg_drop_pct:.0%}）。\n"
            "轴：{involved_axes}\n"
            "这种同步模式通常指向共享 DC 母线或 PSU 容量不足。"
        ),
        "suggested_checks": [
            "测量 DC 母线电压（所有轴同时加载时）",
            "核对 PSU 额定功率 vs 实际负载",
            "检查共享 DC 母线接线端子扭矩",
            "确认制动电阻状态和容量",
            "考虑错峰加减速或 PSU 升级",
        ],
        "expected_modalities": ["text", "image"],
        "urgency_map": {"warning": "soon", "critical": "immediate"},
    },
    "cross_contouring_error": {
        "question": "多轴轨迹偏差 — 疑似插补/耦合问题。请现场检查：",
        "context_template": (
            "AI 检测到 {axis_pair} 轴对的组合跟随误差 {combined_error:.0f} 脉冲，"
            "超过阈值 {threshold:.0f} 脉冲。\n"
            "单轴误差正常，但组合偏差表明轨迹偏离指令路径。"
        ),
        "suggested_checks": [
            "检查 CNC 插补器参数（G64/G61 模式）",
            "验证位置环增益匹配（X/Y 的 0x60FB 是否一致）",
            "检查机械耦合（联轴器/丝杆反向间隙）",
            "降低插补进给率测试是否改善",
            "运行圆度测试（ISO 230-4）量化轮廓误差",
        ],
        "expected_modalities": ["text", "image"],
        "urgency_map": {"warning": "soon", "critical": "immediate"},
    },
    "cross_ring_emi": {
        "question": "EtherCAT 偶发丢帧 — 疑似 EMI/RFI 干扰。请现场检查：",
        "context_template": (
            "AI 检测到 {sporadic_count}/{total_slaves} 个从站出现间歇性帧错误。\n"
            "错误率 {sporadic_rate:.0%}，错误随机分布不呈级联模式。"
        ),
        "suggested_checks": [
            "EtherCAT 线缆是否远离变频器/电机动力线（至少 20cm）",
            "线缆屏蔽层是否正确接地（两端接地？单端？）",
            "检查 RJ45 连接器是否为金属外壳屏蔽型",
            "测量 EtherCAT 线缆附近的电磁场强度",
            "考虑增加磁环或更换双屏蔽线缆",
        ],
        "expected_modalities": ["text", "image"],
        "urgency_map": {"warning": "routine", "critical": "soon"},
    },
    "cross_mechanical_coupling": {
        "question": "跨轴机械耦合振动 — 疑似门桥/龙门结构问题。请现场检查：",
        "context_template": (
            "AI 检测到 {source_axis} 轴的振动幅度随 {target_axis} 轴位置变化。\n"
            "在 {target_axis} 约 {peak_position:.0f} 位置时，{source_axis} 振动增大 {magnitude_ratio:.1f}×。"
        ),
        "suggested_checks": [
            "检查龙门桥架连接螺栓扭矩",
            "验证双轴平行度（激光对准仪）",
            "检查导轨滑块预压和润滑",
            "测量龙门刚性（千分表）",
            "考虑交叉补偿（Cross-compensation）参数",
        ],
        "expected_modalities": ["text", "image", "video"],
        "urgency_map": {"warning": "soon", "critical": "immediate"},
    },
}

# ── Actionable category prompts (AI knows the fix, needs authorization) ───

ACTIONABLE_PROMPTS: Dict[str, dict] = {
    "resonance_detected": {
        "question": "检测到机械共振 — 建议配置陷波滤波器。请审核并授权：",
        "context_template": (
            "AI 检测：在速度信号中检测到 {fundamental_hz:.0f} Hz 共振峰值，"
            "信噪比 {snr:.1f} dB。\n"
            "建议将陷波滤波器 1 (0x610B) 设置为 {fundamental_hz:.0f} Hz。"
        ),
        "suggested_checks": [
            "确认机器在该频率下运行是否正常？（无异常振动或噪音）",
            "确认设置陷波滤波器不会影响系统的带宽和响应速度",
            "建议先设置 Q 值（宽度）为较窄的值（如 0.5），再根据效果调整",
        ],
        "expected_modalities": ["text"],
        "urgency_map": {"info": "routine", "warning": "soon", "critical": "immediate"},
        "authorization_prompt": (
            "即将执行以下操作：\n"
            "  1. 设置 0x610B (Notch Filter 1 Frequency) = {fundamental_hz:.0f} Hz\n"
            "  2. 建议 Q = 0.5 (窄带陷波)\n"
            "  安全提示：陷波滤波器设置不当可能导致系统不稳定。\n"
            "  回滚方案：将 0x610B 设回原值。\n\n"
            "请确认是否授权执行。"
        ),
    },

    "resonance_harmonic": {
        "question": "检测到谐波共振模式 — 需要多陷波滤波器配置。请审核并授权：",
        "context_template": (
            "AI 检测到谐波共振：基频 {fundamental_hz:.0f} Hz，"
            "谐波次数 {harmonic_count}，最高峰 {peak_hz:.0f} Hz。\n"
            "建议配置 1-2 个陷波滤波器覆盖基频和最强谐波。"
        ),
        "suggested_checks": [
            "确认这是结构共振而非外部干扰（如变频器开关频率）",
            "检查机器底座/安装是否牢固 — 结构共振可能需要机械加固",
            "多陷波滤波器可能相互影响，建议逐个配置和测试",
        ],
        "expected_modalities": ["text"],
        "urgency_map": {"info": "routine", "warning": "soon", "critical": "immediate"},
        "authorization_prompt": (
            "即将：配置陷波滤波器覆盖 {fundamental_hz:.0f} Hz 及其谐波。\n"
            "注意：多陷波滤波器会降低相位裕度，可能导致振荡。\n"
            "请确认授权。"
        ),
    },

    "tracking_gain_deficiency": {
        "question": "位置环增益不足 — 建议提高增益参数。请审核并授权：",
        "context_template": (
            "AI 检测：跟随误差/速度比值为 {gain_ratio:.1f}，超过阈值 {threshold:.1f}。\n"
            "这表明位置环比例增益 (Kp) 不足，系统刚度过低。"
        ),
        "suggested_checks": [
            "确认提高增益不会引起振荡（先增加 10-15%，观察响应）",
            "确认机械系统可以承受更高的刚度",
            "如果已经接近振荡边界，考虑先增加速度前馈 (0x60B1)",
        ],
        "expected_modalities": ["text"],
        "urgency_map": {"info": "routine", "warning": "soon", "critical": "immediate"},
        "authorization_prompt": (
            "建议操作：\n"
            "  1. 增加 0x60FB (Position Control Gain) 25%\n"
            "  2. 增加 0x60B1 (Velocity Feedforward) 50%\n"
            "  安全提示：以 10-15% 步长递增，每次递增后观察是否有振荡。\n"
            "  如有振荡，立即回退 20%。\n\n"
            "请确认授权。"
        ),
    },

    "tracking_absolute_limit": {
        "question": "跟随误差超限 — EMERGENCY。请立即处理并授权诊断操作：",
        "context_template": (
            "AI 检测：跟随误差 {error_value:.0f} 脉冲，超过硬件限制 {limit_value:.0f} 脉冲。\n"
            "这是严重故障 — 可能导致紧急停机。"
        ),
        "suggested_checks": [
            "立即检查机械限位 — 是否有碰撞/超程？",
            "检查编码器反馈 — 线缆是否松动或断线？",
            "检查位置指令 — 是否有不合理的跳变？",
            "检查电机动力线 — 是否有缺相？",
        ],
        "expected_modalities": ["text", "image", "video"],
        "urgency_map": {"info": "immediate", "warning": "immediate", "critical": "immediate"},
        "authorization_prompt": (
            "紧急操作：\n"
            "  1. 临时扩大 0x6065 (Following Error Window) 以防止误停机\n"
            "  警告：这只是诊断措施，找到根因后必须恢复原值！\n"
            "  请立即检查机械状况后再授权。"
        ),
    },

    # ── Low-pass filter prompts ──
    "current_ripple": {
        "question": "检测到高频电流纹波 — 建议配置低通滤波器。品牌参数不同，请确认：",
        "context_template": (
            "AI 检测：电流信号中存在高频纹波成分，可能源自编码器噪声、PWM 谐波或轻微机械振动。\n"
            "电流测量值 {current_value:.0f}%，纹波幅值约 {ripple_amplitude:.0f}%。\n"
            "低通滤波可以有效平滑电流指令，但这不在 CiA 402 标准对象字典中，每个品牌使用不同的参数。"
        ),
        "suggested_checks": [
            "确认当前品牌: Delta=P1-07(扭矩滤波)/P2-25(共振抑制LPF), Yaskawa=Pn412, Servotronix=0x20E1",
            "确认纹波频率是否与 PWM 载波频率或其谐波相关（载波频率通常是 8/12/16 kHz）",
            "如果纹波是间歇性的，可能与特定速度段相关 → 检查该速度段是否有轻微机械共振",
            "先尝试小幅滤波（1-2ms），观察电流平滑度和跟踪误差的变化",
        ],
        "expected_modalities": ["text"],
        "urgency_map": {"info": "routine", "warning": "soon", "critical": "soon"},
        "authorization_prompt": (
            "建议操作：\n"
            "  1. 启用扭矩指令低通滤波（品牌特定参数）\n"
            "  2. 设置滤波时间常数 1-2ms（根据纹波频率调整）\n"
            "  3. 如果纹波与特定频率相关，可配置共振抑制 LPF\n"
            "  安全：滤波过多会增加相位滞后，导致跟踪误差增大。\n"
            "  回滚：将滤波时间常数设回 0（禁用）。\n\n"
            "请确认品牌和授权。"
        ),
    },

    # ── S-curve / Jerk prompts ──
    "velocity_ripple": {
        "question": "检测到速度高频振荡 — 建议启用 S 曲线加减速 + 降低 Jerk。请审核：",
        "context_template": (
            "AI 检测：速度信号中存在非共振频率的高频振荡。\n"
            "这通常由梯形加减速的加速度突变（infinite jerk）激发。\n"
            "切换到 jerk-limited S 曲线可以有效抑制此类振荡。"
        ),
        "suggested_checks": [
            "确认当前运动曲线类型：0x6086 (Motion Profile Type) — 0=线性, 3=sin² jerk-limited",
            "检查当前 Jerk 设置：0x60A4 (Profile Jerk) — 如果为 0 表示使用梯形曲线",
            "确认 S 曲线增加的运动时间是否在产线节拍允许范围内（通常增加 5-15%）",
            "如果已经使用 S 曲线但仍有振荡，同时检查速度指令滤波器 (0x2106)",
        ],
        "expected_modalities": ["text"],
        "urgency_map": {"info": "routine", "warning": "soon", "critical": "immediate"},
        "authorization_prompt": (
            "建议操作：\n"
            "  1. 设置 0x6086 (Motion Profile Type) = 3 (sin² jerk-limited)\n"
            "  2. 设置 0x60A4 (Profile Jerk) 为合理值（初始值：加速度/加速时间）\n"
            "  3. 如果仍有振荡，启用速度指令滤波器 0x2106\n"
            "  安全：S 曲线会增加加减速时间，确认不影响产线节拍。\n"
            "  回滚：将 0x6086 设回 0（线性梯形）。\n\n"
            "请确认授权。"
        ),
    },

    "current_saturation": {
        "question": "电流饱和 — 建议降低负载或调整参数限制。请审核并授权：",
        "context_template": (
            "AI 检测：电流 {current_value:.0f}% 超过饱和限制 {saturation_limit:.0f}%。\n"
            "持续饱和会损坏电机绕组。"
        ),
        "suggested_checks": [
            "确认负载是否卡滞/过载 — 检查机械状况",
            "确认加减速是否过于激进",
            "确认电机选型是否偏小",
        ],
        "expected_modalities": ["text"],
        "urgency_map": {"info": "routine", "warning": "soon", "critical": "immediate"},
        "authorization_prompt": (
            "建议操作：\n"
            "  1. 降低 0x6072 (Max Torque) 10%\n"
            "  2. 降低 0x6083 (Profile Acceleration) 20%\n"
            "  注意：这会增加周期时间，确认产线节拍可接受。\n\n"
            "请确认授权。"
        ),
    },
    # ── Cross-axis actionable ──
    "cross_ring_cascade": {
        "question": "EtherCAT 帧错误级联 — 需要更换线缆/连接器。请确认授权：",
        "context_template": (
            "AI 检测到从站 {first_error_slave} 是首个错误点，"
            "共 {cascade_depth} 个从站受到级联影响。\n"
            "受影响从站：{cascaded_slaves}\n"
            "上游从站正常，根因定位在从站 {first_error_slave-1}→{first_error_slave} 之间的物理链路。"
        ),
        "suggested_checks": [
            "更换 EtherCAT 线缆（从站 {first_error_slave-1} → 从站 {first_error_slave}）",
            "检查 RJ45 连接器是否有氧化/松动",
            "确认该从站 EtherCAT PHY 芯片温度是否异常",
            "验证屏蔽接地连续性",
        ],
        "expected_modalities": ["text", "image"],
        "urgency_map": {"critical": "immediate"},
        "authorization_prompt": (
            "建议操作：\n"
            "  1. 更换从站 {first_error_slave-1} → 从站 {first_error_slave} 之间的 EtherCAT 线缆\n"
            "  2. 重新插拔并确认锁紧\n"
            "  3. 如果问题复现，检查从站 {first_error_slave} 的 PHY 芯片\n"
            "  安全提示：更换线缆前可将该从站后的节点设为旁路（bypass）模式。\n"
            "\n请确认是否授权执行。"
        ),
    },
}

# ── Prompt generation helpers ──────────────────────────────────────────

def get_prompt_template(category: str) -> dict:
    """Get the prompt template for an anomaly category.

    Returns:
        dict with question, context_template, suggested_checks, etc.
        Empty dict if the category has no HITL prompt.
    """
    if category in AMBIGUOUS_PROMPTS:
        return AMBIGUOUS_PROMPTS[category]
    if category in ACTIONABLE_PROMPTS:
        return ACTIONABLE_PROMPTS[category]
    return {}


def get_classification(category: str) -> str:
    """Get HITL classification for a category.

    Returns:
        "ambiguous", "actionable", or "safe".
    """
    if category in AMBIGUOUS_PROMPTS:
        return "ambiguous"
    if category in ACTIONABLE_PROMPTS:
        return "actionable"
    return "safe"


def format_context(template: str, annotation_metadata: dict, annotation_value: float,
                   annotation_confidence: float) -> str:
    """Fill a context_template with values from an annotation.

    Uses safe formatting — missing keys are left as-is rather than raising.
    """
    try:
        return template.format(
            baseline_mean=annotation_metadata.get("baseline_mean", annotation_value),
            current_value=annotation_value,
            consecutive_count=annotation_metadata.get("consecutive", 0),
            confidence=annotation_confidence,
            error_value=annotation_value,
            correlation=annotation_metadata.get("correlation", 0.0),
            fundamental_hz=annotation_metadata.get("fundamental_hz", annotation_value),
            snr=annotation_metadata.get("snr", 0.0),
            harmonic_count=annotation_metadata.get("harmonic_count", 0),
            peak_hz=annotation_metadata.get("peak_hz", annotation_value),
            gain_ratio=annotation_metadata.get("gain_ratio", 0.0),
            threshold=annotation_metadata.get("threshold", 0.0),
            limit_value=annotation_metadata.get("limit_value", 0.0),
            saturation_limit=annotation_metadata.get("saturation_limit", 200.0),
        )
    except (KeyError, ValueError, IndexError):
        # Fall back to a simple context if template variables don't match
        return (
            f"AI 检测：{annotation_metadata.get('message', '异常事件')}，"
            f"测量值 {annotation_value:.1f}，置信度 {annotation_confidence:.0%}。"
        )


def format_authorization_text(template: str, annotation_metadata: dict,
                              annotation_value: float) -> str:
    """Fill an authorization_prompt template."""
    try:
        return template.format(
            fundamental_hz=annotation_metadata.get("fundamental_hz", annotation_value),
            harmonic_count=annotation_metadata.get("harmonic_count", 0),
            peak_hz=annotation_metadata.get("peak_hz", annotation_value),
            gain_ratio=annotation_metadata.get("gain_ratio", 0.0),
            threshold=annotation_metadata.get("threshold", 0.0),
            error_value=annotation_value,
            limit_value=annotation_metadata.get("limit_value", 1000000.0),
            current_value=annotation_value,
            saturation_limit=annotation_metadata.get("saturation_limit", 200.0),
        )
    except (KeyError, ValueError, IndexError):
        return "请确认是否授权执行此参数修改。回滚方案：恢复原参数值。"
