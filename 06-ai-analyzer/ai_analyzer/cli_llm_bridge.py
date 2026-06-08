"""
CLI ↔ LLM Bridge — translates natural language to precise CLI commands.

When the LLM is available (ANTHROPIC_API_KEY set), the CLI can accept
natural language input and the LLM translates it to a deterministic command.
When offline, the CLI requires precise command syntax.

Architecture:
    User NL input → [LLM API] → {"command": "hitl feedback ...", ...}
                  → CLI executes command → formatted output

System prompt teaches the LLM the complete CLI command grammar.
"""

import json
import os
import re
from typing import Any, Dict, Optional

# ── CLI Command Grammar (taught to the LLM) ─────────────────────

CLI_GRAMMAR = """
## 伺服诊断 CLI 命令参考

### analyze — 运行 AI 分析
```
analyze                          使用内置演示数据运行分析
analyze --data <file.json>       从 JSON 文件加载数据
analyze --data <file.csv>        从 CSV 文件加载数据
analyze --stride <n>             采样步长（默认10，越大越快）
```

### hitl — 人机交互工作流
```
hitl pending                     列出待处理的工程师提问
hitl history                     查看反馈历史
hitl prompt --all                为所有异常生成工程师提问
hitl prompt --category <name>    为指定类型生成提问
hitl feedback <prompt-id> --text "<描述>" --observation "<检查项>" --auth pending
hitl feedback <prompt-id> --text "<描述>" --auth approved --by "<姓名>"
hitl feedback <prompt-id> --auth rejected
```

### recommend — 参数建议
```
recommend                        生成调参建议
recommend --brand <name>         指定品牌
recommend --format json          JSON 格式输出
```

### params — 参数查询
```
params lookup <0x6083>           查询参数描述
params brands                    列出支持的伺服品牌
```

### log — 审计日志
```
log show                         查看最近事件
log show --last <n>              查看最近 n 条
log summary                      会话摘要
log export                       导出 JSON
log export --file <path>         导出到指定路径
```

### 系统
```
status                           系统状态
status --verbose                 详细状态
session info                     会话信息
help                             命令帮助
quit | exit                      退出
```
"""

CLI_SYSTEM_PROMPT = f"""你是一个伺服诊断 CLI 系统的自然语言接口。
你的唯一任务是将用户的自然语言请求翻译为精确的 CLI 命令。

{CLI_GRAMMAR}

## 翻译规则
1. 如果用户的请求清晰明确，输出精确的命令（不要加解释）
2. 如果用户请求模糊但有最可能的意图，输出该命令 + confidence 0.6-0.8
3. 如果用户请求无法映射到任何命令，设置 command="" 并在 follow_up 中追问
4. 中文和英文输入都支持
5. 对于 HITL feedback，如果用户描述了观察但没有指定 --auth，默认使用 --auth pending

## 输出格式（严格 JSON，不要包含 markdown 标记）
{{{{
  "command": "要执行的 CLI 命令（不含 servo> 前缀）",
  "explanation": "为什么选择这个命令（简短）",
  "follow_up": "需要追问的问题（仅当输入模糊时填写）",
  "confidence": 0.95
}}}}

## 示例
用户: "分析一下数据"
输出: {{{{ "command": "analyze", "explanation": "运行AI分析", "follow_up": "", "confidence": 0.95 }}}}

用户: "联轴器橡胶碎了，检查清单第一项"
输出: {{{{ "command": "hitl feedback <prompt_id> --text \\"联轴器橡胶碎了\\" --observation \\"联轴器：是否有橡胶粉尘\\" --auth pending", "explanation": "提交机械磨损观察", "follow_up": "需要提供 prompt_id（从 hitl pending 获取）", "confidence": 0.7 }}}}

用户: "看看安川的参数建议"
输出: {{{{ "command": "recommend --brand yaskawa-sigma7", "explanation": "安川品牌参数建议", "follow_up": "", "confidence": 0.9 }}}}
"""


class CLICommandTranslator:
    """Translates natural language → CLI commands via Claude API.

    Uses the same pattern as LLMDiagnosisRefiner: requests + env var API key.
    """

    def __init__(self, api_key: str = None, model: str = "claude-sonnet-4-6",
                 timeout: int = 20):
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self.model = model
        self.timeout = timeout
        self._api_url = "https://api.anthropic.com/v1/messages"
        self._last_error = ""

    @property
    def available(self) -> bool:
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

    def translate(self, user_input: str) -> Optional[Dict[str, Any]]:
        """Translate natural language input to a CLI command dict.

        Returns:
            {"command": "analyze", "explanation": "...",
             "follow_up": "", "confidence": 0.95}
            or None on failure.
        """
        if not self.available or not user_input.strip():
            return None

        user_message = f"用户输入: {user_input}\n\n请翻译为 CLI 命令。"

        try:
            import requests
            resp = requests.post(
                self._api_url,
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": self.model,
                    "max_tokens": 512,
                    "temperature": 0.1,
                    "system": CLI_SYSTEM_PROMPT,
                    "messages": [{"role": "user", "content": user_message}],
                },
                timeout=self.timeout,
            )

            if resp.status_code != 200:
                self._last_error = f"API {resp.status_code}"
                return None

            data = resp.json()
            text = data["content"][0]["text"]

            # Parse JSON from response
            return self._parse_translation(text)

        except Exception as e:
            self._last_error = str(e)
            return None

    @staticmethod
    def _parse_translation(text: str) -> Optional[Dict[str, Any]]:
        """Extract JSON translation from LLM response."""
        if not text:
            return None

        # Try direct parse
        try:
            return json.loads(text.strip())
        except json.JSONDecodeError:
            pass

        # Try ```json block
        m = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1).strip())
            except json.JSONDecodeError:
                pass

        # Try any JSON object with "command" key
        m = re.search(r'\{[^{}]*"command"[^{}]*\}', text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass

        return None

    def health_check(self) -> dict:
        """Quick API health check."""
        if not self.available:
            return {"status": "unavailable", "reason": self._last_error}
        try:
            import requests
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
            return {"status": "ok" if resp.status_code == 200 else "error",
                    "http_status": resp.status_code}
        except Exception as e:
            return {"status": "error", "reason": str(e)}
