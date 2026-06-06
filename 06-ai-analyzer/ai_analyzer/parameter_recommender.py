"""
AI Parameter Recommendation Engine (P2.5).

Maps AI detector outputs to brand-specific CiA 402 parameter adjustments.

Architecture:
    AIAnnotation[] → TuningRuleEngine → BrandResolver → ParameterRecommendation[]

Usage:
    from parameter_recommender import ParameterRecommender

    rec = ParameterRecommender(brand="yaskawa-sigma7")
    params = rec.recommend(annotations)
    for p in params:
        print(f"  {p.index_hex}: {p.action} → {p.reason}")
"""

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from .tuning_rules import BRAND_ALIASES, PARAM_DESCRIPTIONS, TUNING_RULES
except ImportError:
    from tuning_rules import BRAND_ALIASES, PARAM_DESCRIPTIONS, TUNING_RULES


@dataclass
class ParameterRecommendation:
    """A single parameter adjustment recommendation."""

    index: int                  # hex index (e.g. 0x610B)
    subindex: int = 0           # sub-index (usually 0)
    name: str = ""              # parameter name from brand dictionary
    description: str = ""       # human-readable description
    action: str = ""            # "increase", "decrease", "set", "check", "consider"
    current_value: Optional[float] = None   # current value (if known)
    target_value: Optional[float] = None    # suggested new value
    step_pct: float = 0.0       # % change from current
    reason: str = ""            # why this adjustment
    safety: str = ""            # safety note / warning
    priority: int = 0           # 1 = critical, 2 = recommended, 3 = optional
    triggered_by: str = ""      # which anomaly category triggered this

    @property
    def index_hex(self) -> str:
        return f"0x{self.index:04X}"

    def to_dict(self) -> dict:
        return {
            "index": self.index_hex,
            "subindex": self.subindex,
            "name": self.name,
            "description": self.description,
            "action": self.action,
            "current_value": self.current_value,
            "target_value": self.target_value,
            "step_pct": self.step_pct,
            "reason": self.reason,
            "safety": self.safety,
            "priority": self.priority,
            "triggered_by": self.triggered_by,
        }


class ParameterRecommender:
    """Engine that converts AI annotations into tuning parameter recommendations.

    Parameters:
        brand: Brand key (e.g. "yaskawa-sigma7", "delta-a3"). If None, uses
               CiA 402 standard indices only.
        brand_loader: Optional BrandLoader instance for parameter lookup.
    """

    def __init__(self, brand: Optional[str] = None, brand_loader=None):
        self.brand = brand
        self._loader = brand_loader
        self._brand_objects: Dict[str, dict] = {}  # index → object cache

        # Load brand parameter dictionary if available
        if brand and self._loader is None:
            self._try_load_loader()

    def _try_load_loader(self):
        """Lazy-load BrandLoader if available."""
        try:
            _params_path = Path(__file__).resolve().parent.parent.parent / "05-servo-params"
            sys.path.insert(0, str(_params_path))
            from brand_loader import BrandLoader
            self._loader = BrandLoader()
        except ImportError:
            pass

    def _load_brand_objects(self):
        """Load CoE objects for current brand into lookup cache."""
        if not self._loader or not self.brand:
            return
        if self._brand_objects:
            return  # already loaded

        try:
            objects = self._loader.load_objects(self.brand)
            if objects:
                for obj in objects.get("objects", []):
                    self._brand_objects[obj["index"]] = obj
        except Exception:
            pass

    def _resolve_index(self, standard_idx: int) -> int:
        """Resolve a CiA 402 standard index to the brand-specific equivalent."""
        if not self.brand or self.brand not in BRAND_ALIASES:
            return standard_idx

        aliases = BRAND_ALIASES[self.brand]
        return aliases.get(standard_idx, standard_idx)

    def _get_param_name(self, idx: int) -> str:
        """Get parameter name from brand dictionary or fallback."""
        hex_key = f"0x{idx:04X}"

        # Try brand dictionary
        if hex_key in self._brand_objects:
            return self._brand_objects[hex_key].get("name", "")

        # Fallback to standard descriptions
        return PARAM_DESCRIPTIONS.get(idx, f"Object {hex_key}")

    def recommend(self, annotations: list) -> List[ParameterRecommendation]:
        """Generate parameter recommendations from AI annotations.

        Args:
            annotations: List of AIAnnotation from AIAnalyzerPipeline.

        Returns:
            List of ParameterRecommendation, sorted by priority.
        """
        if not annotations:
            return []

        self._load_brand_objects()
        recommendations: List[ParameterRecommendation] = []
        seen_indices = set()

        for ann in annotations:
            category = ann.category
            if category not in TUNING_RULES:
                continue

            rule = TUNING_RULES[category]

            for param_rule in rule.get("params", []):
                # Resolve to brand-specific index
                standard_idx = param_rule["index"]
                brand_idx = self._resolve_index(standard_idx)

                # Also check alt_index
                if "alt_index" in param_rule:
                    alt_idx = self._resolve_index(param_rule["alt_index"])
                else:
                    alt_idx = None

                # Deduplicate: same index + same triggered_by = skip
                dedup_key = f"{brand_idx}:{category}"
                if dedup_key in seen_indices:
                    continue
                seen_indices.add(dedup_key)

                param_name = self._get_param_name(brand_idx)

                # Compute target value if we have frequency data
                target_value = None
                if param_rule["direction"] == "set" and "fundamental_hz" in ann.metadata:
                    target_value = ann.metadata["fundamental_hz"]

                rec = ParameterRecommendation(
                    index=brand_idx,
                    subindex=param_rule.get("subindex", 0),
                    name=param_name,
                    description=PARAM_DESCRIPTIONS.get(brand_idx, ""),
                    action=param_rule["direction"],
                    current_value=None,
                    target_value=target_value,
                    step_pct=param_rule.get("step_pct", 0),
                    reason=param_rule.get("reason", ""),
                    safety=param_rule.get("safety", ""),
                    priority=rule.get("priority", 3),
                    triggered_by=category,
                )
                recommendations.append(rec)

                # If there's an alt_index, add it as a secondary recommendation
                if alt_idx and alt_idx != brand_idx:
                    alt_dedup_key = f"{alt_idx}:{category}"
                    if alt_dedup_key not in seen_indices:
                        seen_indices.add(alt_dedup_key)
                        alt_rec = ParameterRecommendation(
                            index=alt_idx,
                            subindex=param_rule.get("subindex", 0),
                            name=self._get_param_name(alt_idx),
                            description=PARAM_DESCRIPTIONS.get(alt_idx, ""),
                            action=param_rule["direction"],
                            current_value=None,
                            target_value=target_value,
                            step_pct=param_rule.get("step_pct", 0),
                            reason=f"(Alternative index for this brand) {param_rule.get('reason', '')}",
                            safety=param_rule.get("safety", ""),
                            priority=rule.get("priority", 3) + 1,
                            triggered_by=category,
                        )
                        recommendations.append(alt_rec)

        # Sort by priority (1 = critical, 3 = optional)
        recommendations.sort(key=lambda r: (r.priority, r.index))
        return recommendations

    def format(self, recommendations: List[ParameterRecommendation]) -> str:
        """Format recommendations as a human-readable tuning report."""
        if not recommendations:
            return "No parameter adjustments needed."

        lines = ["", "=" * 60, "  AI Tuning Recommendations", "=" * 60]

        current_cat = ""
        for i, rec in enumerate(recommendations):
            if rec.triggered_by != current_cat:
                current_cat = rec.triggered_by
                rule = TUNING_RULES.get(current_cat, {})
                lines.append(f"\n  [{rule.get('summary', current_cat)}]")

            action_icon = {
                "increase": "↑", "decrease": "↓", "set": "→", "check": "?", "consider": "○"
            }.get(rec.action, "?")

            lines.append(
                f"  {action_icon} {rec.index_hex} {rec.name[:45]}"
            )
            lines.append(f"    Action: {rec.action}")
            if rec.target_value:
                lines.append(f"    Target: {rec.target_value:.0f}")
            lines.append(f"    Reason: {rec.reason}")
            if rec.safety:
                lines.append(f"    Safety: {rec.safety}")

        lines.append("\n" + "=" * 60)
        return "\n".join(lines)


# ── CLI ─────────────────────────────────────────────────────

def main():
    """Demo: generate recommendations from simulated annotations."""
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "06-ai-analyzer"))

    from analyzer_base import AIAnnotation

    # Simulate a resonance detection annotation
    ann = AIAnnotation(
        timestamp=0.0,
        channel="Velocity",
        category="resonance_detected",
        severity="warning",
        confidence=0.95,
        message="Resonance peak at 75 Hz",
        suggestion="Set notch filter",
        value=75.0,
        metadata={"fundamental_hz": 75.0},
    )

    rec = ParameterRecommender(brand="yaskawa-sigma7")
    params = rec.recommend([ann])
    print(rec.format(params))

    # Test with Delta brand
    rec2 = ParameterRecommender(brand="delta-a3")
    params2 = rec2.recommend([ann])
    print(rec2.format(params2))


if __name__ == "__main__":
    main()
