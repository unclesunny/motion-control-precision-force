"""
LLM Diagnosis Refiner — Claude-powered servo mechanical diagnosis.

Replaces the keyword-matching `_refine_diagnosis()` in hitl_gate.py with
LLM-powered reasoning. The LLM understands natural language engineer feedback
(Chinese, English, mixed), correlates it with the AI's electrical signal
detection, and produces a structured, actionable diagnosis.

Architecture:
    EngineerFeedback (natural language)
        + EngineerPrompt (signal context + checklist)
        → LLMDiagnosisRefiner.refine()
        → Structured diagnosis dict
        → HITLGate → AIAnnotation

Graceful degradation:
    LLM available    → Claude API → structured diagnosis
    LLM unavailable  → keyword matching (current behavior)
    API timeout/error → keyword matching fallback

Dependencies:
    - requests (stdlib-like, almost always available)
    - ANTHROPIC_API_KEY environment variable (or passed explicitly)

Usage:
    from llm_refiner import LLMDiagnosisRefiner

    refiner = LLMDiagnosisRefiner()  # reads ANTHROPIC_API_KEY
    if refiner.available:
        result = refiner.refine(prompt, feedback)
        print(result["diagnosis"])
        print(result["recommendation"])
"""

import json
import os
import re
import time
from typing import Any, Dict, List, Optional

try:
    from .config import LLM_REFINER_CONFIG
except ImportError:
    from config import LLM_REFINER_CONFIG

try:
    from .hitl_types import EngineerFeedback, EngineerPrompt
except ImportError:
    from hitl_types import EngineerFeedback, EngineerPrompt


# ── System Prompt ───────────────────────────────────────────────

SYSTEM_PROMPT = """你是一位伺服系统机械诊断专家，拥有20年现场调试经验。
你的任务是根据 AI 检测到的电信号异常 + 工程师的现场观察，给出精化的部件级诊断和可操作的建议。

## 你的能力边界
- AI 电信号能检测：电流变化、振动频谱、跟随误差、扭矩波动
- AI 电信号不能检测：视觉状态（磨损/粉尘/颜色）、声音（异响类型）、触觉（温度/振动手感）、嗅觉（烧焦味）
- 工程师的现场反馈弥补了 AI 的盲区——你负责把两者结合起来做推理

## 输入信息
你会收到：
1. **AI 检测上下文**：异常类型、测量值、漂移趋势、置信度
2. **AI 检查清单**：AI 建议工程师检查的项目列表
3. **工程师反馈**：工程师在现场用自然语言描述的观察（可能是文字、也可能是照片/录音/视频的文字转述）

## 输出格式
严格返回 JSON（不要包含 markdown 代码块标记）：
{
  "refined_category": "异常子类型代码",
  "diagnosis": "精化诊断（中文，1-2句，明确指向具体部件）",
  "recommendation": "具体操作步骤（含测量工具/标准值/扭矩/型号建议）",
  "confidence": 0.85,
  "requires_parts": ["需采购的零件"],
  "urgency": "routine|soon|immediate",
  "additional_checks": ["如果上述建议无效，进一步排查的步骤"],
  "parameter_adjustment": "临时参数补偿建议（如降增益、扩窗口、降加速度），无建议时为空字符串"
}

## 异常子类型代码（必须从以下列表中选择）
**current_wear 系列（电流渐变漂移 → 机械磨损）：**
- current_wear_coupling: 联轴器磨损/弹性体老化/不对中
- current_wear_ballscrew: 丝杆/滚珠丝杆磨损/滚道剥落
- current_wear_bearing: 轴承磨损/点蚀/保持架损坏
- current_wear_belt: 皮带磨损/齿面剥落/张力下降
- current_wear_guide: 导轨滑块磨损/润滑不足/爬行
- current_wear_other: 其他机械磨损（需说明具体位置）

**tracking_bind 系列（跟随误差+电流同步上升 → 机械卡滞）：**
- tracking_bind_guide: 导轨卡滞/润滑干涩/防护罩刮擦
- tracking_bind_backlash: 丝杆反向间隙过大
- tracking_bind_interference: 线槽/防护罩与运动部件干涉
- tracking_bind_debris: 切屑/异物进入运动副
- tracking_bind_other: 其他卡滞原因（需说明）

## 诊断原则
1. **工程师的观察优先**：他们在现场能看到 AI 看不到的。相信他们的描述。
2. **模糊时追问**：如果工程师反馈太模糊（如"声音不太对"），confidence 设为 0.5-0.6，在 additional_checks 中给出最可能的方向和具体验证步骤。
3. **具体可操作**："检查联轴器"太笼统 → "断电后，用千分表测量联轴器外圆径向跳动，标准 <0.05mm；目视检查弹性体是否有裂纹或橡胶粉末"
4. **confidence 诚实**：工程师给了清晰的视觉证据（如"联轴器橡胶全碎了"）→ confidence ≥ 0.9；工程师说"好像有点不对劲"→ confidence ≤ 0.6
5. **多问题并存**：如果工程师描述了多个部件的异常，在 diagnosis 中列出所有问题，refined_category 选最主要的一个，additional_checks 覆盖次要问题"""


class LLMDiagnosisRefiner:
    """LLM-powered servo mechanical diagnosis refinement.

    Calls the Anthropic Claude API to convert engineer natural language
    feedback into structured, actionable diagnosis.

    Parameters:
        api_key: Anthropic API key. If None, reads ANTHROPIC_API_KEY env var.
        model: Claude model ID. Default from LLM_REFINER_CONFIG.
        timeout: API call timeout in seconds.
        max_tokens: Max response tokens.
        temperature: LLM temperature (low = more deterministic).
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        timeout: Optional[int] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ):
        cfg = LLM_REFINER_CONFIG
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self.model = model or cfg.get("model", "claude-sonnet-4-6")
        self.timeout = timeout or cfg.get("timeout_seconds", 30)
        self.max_tokens = max_tokens or cfg.get("max_tokens", 1024)
        self.temperature = temperature or cfg.get("temperature", 0.3)
        self._api_url = "https://api.anthropic.com/v1/messages"
        self._last_error: str = ""

    @property
    def available(self) -> bool:
        """Check if the LLM refiner is ready to use."""
        if not self.api_key:
            self._last_error = "ANTHROPIC_API_KEY not set"
            return False
        try:
            import requests  # noqa: F401
            return True
        except ImportError:
            self._last_error = "requests library not installed"
            return False

    @property
    def last_error(self) -> str:
        return self._last_error

    # ── Main API ─────────────────────────────────────────────

    def refine(
        self, prompt: EngineerPrompt, feedback: EngineerFeedback
    ) -> Optional[Dict[str, Any]]:
        """Refine an ambiguous diagnosis using LLM reasoning.

        Args:
            prompt: The original engineer prompt (signal context + checklist).
            feedback: Engineer's natural language feedback.

        Returns:
            Structured diagnosis dict, or None if LLM is unavailable/fails.
            Caller should fall back to keyword matching on None.
        """
        if not self.available:
            return None

        user_message = self._build_user_message(prompt, feedback)

        try:
            response = self._call_api(user_message)
            parsed = self._parse_response(response)
            if parsed:
                parsed["_source"] = "llm"
                parsed["_model"] = self.model
            return parsed
        except Exception as e:
            self._last_error = str(e)
            return None

    def _build_user_message(
        self, prompt: EngineerPrompt, feedback: EngineerFeedback
    ) -> str:
        """Construct the user message for the LLM."""

        # AI detection context
        detection_info = ""
        if prompt.metadata:
            md = prompt.metadata
            detection_info = (
                f"异常类型: {prompt.category}\n"
                f"原始分类: {prompt.classification}\n"
                f"AI 置信度: {md.get('annotation_confidence', 0):.0%}\n"
                f"测量值: {md.get('annotation_value', 'N/A')}\n"
                f"AI 初步判断: {md.get('annotation_message', 'N/A')}\n"
            )

        # Signal context from prompt
        context = prompt.context or "（无额外上下文）"

        # Checklist
        checks = "\n".join(
            f"  {i+1}. {c}" for i, c in enumerate(prompt.suggested_checks)
        ) if prompt.suggested_checks else "（无检查清单）"

        # Engineer feedback
        engineer_text = feedback.response_text or "（工程师未提供文字描述）"
        observation = feedback.selected_observation or "（未选择具体检查项）"
        media_note = ""
        if feedback.media_paths:
            media_note = f"\n附带文件: {', '.join(feedback.media_paths)}"

        return f"""## AI 电信号检测结果
{detection_info}
上下文: {context}

## AI 建议的检查清单
{checks}

## 工程师现场反馈
文字描述: {engineer_text}
确认的检查项: {observation}{media_note}

请根据以上信息，给出精化的部件级诊断。"""

    # ── API Call ─────────────────────────────────────────────

    def _call_api(self, user_message: str) -> str:
        """Call the Anthropic Claude API and return the text response."""
        import requests

        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

        payload = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "system": SYSTEM_PROMPT,
            "messages": [
                {"role": "user", "content": user_message},
            ],
        }

        resp = requests.post(
            self._api_url,
            headers=headers,
            json=payload,
            timeout=self.timeout,
        )

        if resp.status_code != 200:
            error_body = resp.text[:500] if resp.text else "No response body"
            raise RuntimeError(
                f"Claude API returned {resp.status_code}: {error_body}"
            )

        data = resp.json()
        content_blocks = data.get("content", [])
        if not content_blocks:
            raise RuntimeError("Claude API returned empty content")

        return content_blocks[0].get("text", "")

    # ── Response Parsing ─────────────────────────────────────

    @staticmethod
    def _parse_response(text: str) -> Optional[Dict[str, Any]]:
        """Parse the LLM's JSON response from text.

        Handles:
          - Pure JSON: {"refined_category": ...}
          - JSON in code block: ```json {...} ```
          - JSON in code block without language: ``` {...} ```
        """
        if not text:
            return None

        # Try direct parse first
        try:
            return json.loads(text.strip())
        except json.JSONDecodeError:
            pass

        # Try extracting from ```json ... ``` block
        json_block_patterns = [
            r'```json\s*\n?(.*?)\n?```',
            r'```\s*\n?(\{.*?\})\s*\n?```',
        ]
        for pattern in json_block_patterns:
            m = re.search(pattern, text, re.DOTALL)
            if m:
                try:
                    return json.loads(m.group(1).strip())
                except json.JSONDecodeError:
                    continue

        # Try to find any JSON object in the text
        json_obj_pattern = r'\{[^{}]*"refined_category"[^{}]*\}'
        m = re.search(json_obj_pattern, text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass

        # Last resort: try to find anything that looks like JSON
        brace_pattern = r'\{.*\}'
        m = re.search(brace_pattern, text, re.DOTALL)
        if m:
            try:
                candidate = json.loads(m.group(0))
                if "diagnosis" in candidate or "refined_category" in candidate:
                    return candidate
            except json.JSONDecodeError:
                pass

        return None

    # ── Utility ──────────────────────────────────────────────

    def health_check(self) -> Dict[str, Any]:
        """Quick check: is the API reachable and key valid?"""
        if not self.available:
            return {"status": "unavailable", "reason": self._last_error}

        import requests
        try:
            resp = requests.post(
                self._api_url,
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": self.model,
                    "max_tokens": 10,
                    "messages": [{"role": "user", "content": "ping"}],
                },
                timeout=10,
            )
            if resp.status_code == 200:
                return {"status": "ok", "model": self.model}
            else:
                return {"status": "error", "http_status": resp.status_code,
                        "body": resp.text[:200]}
        except Exception as e:
            return {"status": "error", "reason": str(e)}
