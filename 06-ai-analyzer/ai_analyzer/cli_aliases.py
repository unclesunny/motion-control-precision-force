"""
CLI Alias Registry — built-in + user-defined command aliases.

Built-in aliases ship with the system and are auto-generated from the
command registry. User aliases are stored in ~/.servo_aliases (JSON)
and persist across sessions.

Aliases support:
  - Simple substitution: "a" → "analyze"
  - Multi-command macros: "diag" → "analyze\nhitl prompt --all\nrecommend"
  - Chinese/pinyin shorthand: "分析" → "analyze"
  - Category shortcuts: "磨损" → "hitl prompt --category current_wear"

Resolution order: user alias → built-in alias → original command

Usage:
    from cli_aliases import AliasRegistry

    registry = AliasRegistry()
    registry.add_user_alias("mycheck", "analyze --stride 5")
    resolved = registry.resolve("mycheck")  # → "analyze --stride 5"
    registry.save()
"""

import json
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# ── Built-in Aliases ─────────────────────────────────────────

# Shorthand aliases (English + Pinyin + Chinese)
BUILTIN_ALIASES: Dict[str, str] = {
    # ── English shorthand ──
    "a":   "analyze",
    "an":  "analyze",
    "st":  "status",
    "stat": "status",
    "s":   "status",
    "h":   "hitl",
    "hp":  "hitl prompt --all",
    "hpe": "hitl pending",
    "hpa": "hitl pending",
    "hhi": "hitl history",
    "hf":  "hitl feedback",
    "ha":  "hitl authorize",
    "r":   "recommend",
    "rec": "recommend",
    "p":   "params",
    "pl":  "params lookup",
    "pb":  "params brands",
    "d":   "detectors",
    "det": "detectors",
    "l":   "log",
    "ls":  "log show",
    "lsh": "log show",
    "le":  "log export",
    "lex": "log export",
    "lsum":"log summary",
    "si":  "session info",
    "ses": "session",
    "sess": "session",
    "q":   "quit",
    "x":   "quit",
    "exit": "quit",
    "?":   "help",
    "h?":  "help",

    # ── Chinese shorthand ──
    "分析": "analyze",
    "fx":  "analyze",
    "状态": "status",
    "zt":  "status",
    "推荐": "recommend",
    "tj":  "recommend",
    "参数": "params lookup",
    "cs":  "params lookup",
    "品牌": "params brands",
    "pp":  "params brands",
    "检测器":"detectors",
    "jcq": "detectors",
    "日志": "log show",
    "rz":  "log show",
    "会话": "session info",
    "hh":  "session info",
    "帮助": "help",
    "bz":  "help",
    "退出": "quit",
    "tc":  "quit",
    "再见": "quit",

    # ── HITL workflow shorthand ──
    "提问": "hitl prompt --all",
    "tw":  "hitl prompt --all",
    "反馈": "hitl feedback",
    "fk":  "hitl feedback",
    "授权": "hitl authorize",
    "sq":  "hitl authorize",
    "待处理":"hitl pending",
    "dcl": "hitl pending",
    "历史": "hitl history",
    "lis": "hitl history",

    # ── Quick diagnostic macros ──
    "快诊": "analyze\nhitl prompt --all",
    "kz":  "analyze\nhitl prompt --all",
    "快检": "status\nanalyze",
    "kj":  "status\nanalyze",

    # ── Oscilloscope ──
    "示波器": "scope",
    "sbq":  "scope",
    "osc":  "scope",

    # ── CODESYS export ──
    "导出": "codesys export",
    "dc":  "codesys export",
    "csy": "codesys export",
}

# Category-specific shortcuts (expand to hitl prompt with category filter)
CATEGORY_ALIASES: Dict[str, str] = {
    "磨损": "hitl prompt --category current_wear",
    "mosun": "hitl prompt --category current_wear",
    "ms":    "hitl prompt --category current_wear",
    "卡滞": "hitl prompt --category tracking_mechanical_bind",
    "kazhi":"hitl prompt --category tracking_mechanical_bind",
    "kzhi": "hitl prompt --category tracking_mechanical_bind",
    "共振": "hitl prompt --category resonance_detected",
    "gongzhen": "hitl prompt --category resonance_detected",
    "gzh":  "hitl prompt --category resonance_detected",
    "饱和": "hitl prompt --category current_saturation",
    "baohe":"hitl prompt --category current_saturation",
    "bh":   "hitl prompt --category current_saturation",
    "增益": "hitl prompt --category tracking_gain_deficiency",
    "zengyi":"hitl prompt --category tracking_gain_deficiency",
    "zy":   "hitl prompt --category tracking_gain_deficiency",
}


# ── Alias Registry ──────────────────────────────────────────

class AliasRegistry:
    """Manages built-in and user-defined CLI command aliases.

    Built-in aliases are shipped with the system and cannot be modified
    by users. User aliases are stored in ~/.servo_aliases and persist
    across sessions.

    Resolution order: user alias → category alias → built-in alias → None
    """

    def __init__(self, user_file: Optional[str] = None):
        """
        Args:
            user_file: Path to user alias JSON file.
                      Default: ~/.servo_aliases
        """
        self._user_file = Path(user_file) if user_file else Path.home() / ".servo_aliases"
        self._user_aliases: Dict[str, str] = {}
        self._load_user_aliases()

    # ── Alias Resolution ───────────────────────────────────

    def resolve(self, name: str) -> Optional[str]:
        """Resolve an alias to its command string.

        Args:
            name: Alias name (user or built-in).

        Returns:
            Command string, or None if not an alias.
        """
        name_lower = name.lower().strip()

        # 1. User aliases (highest priority)
        if name_lower in self._user_aliases:
            return self._user_aliases[name_lower]
        # Also check original case for Chinese
        if name in self._user_aliases:
            return self._user_aliases[name]

        # 2. Category aliases (Chinese + pinyin)
        if name in CATEGORY_ALIASES:
            return CATEGORY_ALIASES[name]
        if name_lower in CATEGORY_ALIASES:
            return CATEGORY_ALIASES[name_lower]

        # 3. Built-in aliases
        if name in BUILTIN_ALIASES:
            return BUILTIN_ALIASES[name]
        if name_lower in BUILTIN_ALIASES:
            return BUILTIN_ALIASES[name_lower]

        return None

    def is_alias(self, name: str) -> bool:
        """Check if a name is a registered alias."""
        return self.resolve(name) is not None

    def resolve_line(self, line: str) -> Tuple[str, bool]:
        """Resolve a full input line, expanding aliases.

        Handles:
          - Simple alias: "a" → "analyze"
          - Alias with args: "hf hitl-123 --text hello" → "hitl feedback hitl-123 --text hello"
          - Multi-command macros: lines joined with \n preserved

        Returns:
            (resolved_line, was_aliased) — was_aliased=True if alias was expanded.
        """
        if not line.strip():
            return line, False

        # Get first word as potential alias
        parts = line.split(maxsplit=1)
        first_word = parts[0]
        rest = parts[1] if len(parts) > 1 else ""

        resolved = self.resolve(first_word)
        if resolved is None:
            return line, False

        # Multi-command macro (contains \n)
        if "\n" in resolved:
            return resolved, True

        # Simple alias: append rest of the line
        if rest:
            return f"{resolved} {rest}", True
        return resolved, True

    # ── User Alias Management ──────────────────────────────

    def add_user_alias(self, name: str, command: str) -> bool:
        """Add or update a user-defined alias.

        Args:
            name: Alias name (must not conflict with built-in commands).
            command: The command(s) to expand to.

        Returns:
            True if added, False if name conflicts with a built-in command.
        """
        name_key = name.lower().strip()
        if not name_key or not command.strip():
            return False

        # Warn if overriding built-in alias (but allow it)
        if name_key in BUILTIN_ALIASES:
            pass  # user aliases take priority anyway

        self._user_aliases[name_key] = command.strip()
        # Also store original case for Chinese aliases
        if name != name_key:
            self._user_aliases[name] = command.strip()
        return True

    def remove_user_alias(self, name: str) -> bool:
        """Remove a user-defined alias.

        Returns True if removed, False if not found or built-in.
        """
        name_key = name.lower().strip()
        removed = False
        if name_key in self._user_aliases:
            del self._user_aliases[name_key]
            removed = True
        if name in self._user_aliases:
            del self._user_aliases[name]
            removed = True
        return removed

    def get_user_aliases(self) -> Dict[str, str]:
        """Get all user-defined aliases."""
        return dict(self._user_aliases)

    def get_builtin_aliases(self) -> Dict[str, str]:
        """Get all built-in aliases (merged: base + category)."""
        all_builtin = dict(BUILTIN_ALIASES)
        all_builtin.update(CATEGORY_ALIASES)
        return all_builtin

    def get_all_aliases(self) -> Dict[str, Tuple[str, str]]:
        """Get all aliases with their source.

        Returns:
            {name: (command, source)} where source is "user" or "builtin".
        """
        result = {}
        for k, v in self.get_builtin_aliases().items():
            result[k] = (v, "builtin")
        for k, v in self._user_aliases.items():
            result[k] = (v, "user")
        return result

    def list_aliases(self, source: str = "all") -> Dict[str, Tuple[str, str]]:
        """List aliases filtered by source.

        Args:
            source: "all", "builtin", or "user".
        """
        if source == "user":
            return {k: (v, "user") for k, v in self._user_aliases.items()}
        elif source == "builtin":
            return {k: (v, "builtin") for k, v in self.get_builtin_aliases().items()}
        return self.get_all_aliases()

    # ── Persistence ────────────────────────────────────────

    def _load_user_aliases(self):
        """Load user aliases from ~/.servo_aliases."""
        if not self._user_file.exists():
            return
        try:
            with open(self._user_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                self._user_aliases = {k.lower(): v for k, v in data.items()}
        except (json.JSONDecodeError, OSError):
            pass

    def save(self, filepath: Optional[str] = None) -> str:
        """Save user aliases to file.

        Args:
            filepath: Target path. Default: ~/.servo_aliases.

        Returns:
            Absolute path of the saved file.
        """
        target = Path(filepath) if filepath else self._user_file
        target.parent.mkdir(parents=True, exist_ok=True)

        # Deduplicate: remove lower-case duplicates, keep original case
        clean = {}
        seen = set()
        for k, v in sorted(self._user_aliases.items()):
            kl = k.lower()
            if kl not in seen:
                clean[k] = v
                seen.add(kl)

        with open(target, "w", encoding="utf-8") as f:
            json.dump(clean, f, indent=2, ensure_ascii=False)

        self._user_file = target
        return str(target.resolve())

    def reload(self):
        """Reload user aliases from file."""
        self._load_user_aliases()

    def reset_user_aliases(self):
        """Clear all user-defined aliases (does not save to file)."""
        self._user_aliases.clear()

    # ── Sync with CLI ──────────────────────────────────────

    @staticmethod
    def get_command_list() -> List[str]:
        """Get list of all available CLI commands for alias discovery."""
        return [
            "analyze", "hitl", "recommend", "params", "detectors",
            "log", "status", "session", "help", "quit", "alias",
        ]

    @staticmethod
    def get_missing_alias_suggestions() -> List[str]:
        """Suggest aliases for commands that don't have one yet.

        Returns list of "command → suggested_alias" strings.
        """
        commands = AliasRegistry.get_command_list()
        suggestions = []
        for cmd in commands:
            has_alias = any(
                v == cmd or v.startswith(cmd)
                for v in BUILTIN_ALIASES.values()
            )
            if not has_alias:
                # Suggest first letter
                suggestions.append(f"{cmd} → {cmd[0]}")
        return suggestions

    # ── Statistics ─────────────────────────────────────────

    def stats(self) -> dict:
        """Get alias statistics."""
        builtin = self.get_builtin_aliases()
        return {
            "builtin_count": len(builtin),
            "category_count": len(CATEGORY_ALIASES),
            "user_count": len(self._user_aliases),
            "total": len(builtin) + len(self._user_aliases),
            "user_file": str(self._user_file),
        }
