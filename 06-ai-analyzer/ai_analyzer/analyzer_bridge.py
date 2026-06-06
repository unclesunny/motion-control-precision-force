"""
AI&ML Agent Bridge — stable interface to sibling project capabilities.

Per CONSTITUTION.md Article 3:
  - References AI&ML Agent code via relative path (never copies)
  - All imports are lazy (inside methods) to avoid import errors when absent
  - Graceful degradation: bridge_available=False when AI&ML Agent not present
  - Single update point if AI&ML Agent project is restructured

Capabilities bridged:
  - Solution 01: PPO PID auto-tuning (PPOPIDTuner)
  - Solution 02: Servo current anomaly regression model
  - SL1: Drift root cause classifier (LightGBM)
  - AR4: Solution auto-generator (SolutionAutoGenerator)
  - Streaming anomaly detection patterns
  - PLC-compatible feature extraction algorithms
"""

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional


class AIAnalyzerBridge:
    """Lazy-loading bridge to AI&ML Agent project.

    All imports are deferred to method calls. If the AI&ML Agent project
    is not at the expected path, methods return sensible defaults and
    bridge_available is set to False.
    """

    def __init__(self, agent_path: Optional[str] = None):
        """
        Args:
            agent_path: Path to AI&ML Agent Claude Main directory.
                       Defaults to ../../AI&ML Agent/AI&ML_knowledge_Base/Claude Main
                       relative to this file's location.
        """
        if agent_path is None:
            # Resolve relative to this file: 06-ai-analyzer/src/ → project root
            this_dir = Path(__file__).resolve().parent  # src/
            ai_analyzer_dir = this_dir.parent           # 06-ai-analyzer/
            project_root = ai_analyzer_dir.parent       # motion-control-precision-force/
            agent_path = str(project_root.parent / "AI&ML Agent" / "AI&ML_knowledge_Base" / "Claude Main")

        self.agent_root = Path(agent_path)
        self._bridge_available: Optional[bool] = None  # lazy check

    @property
    def bridge_available(self) -> bool:
        """Check if AI&ML Agent project is accessible."""
        if self._bridge_available is None:
            self._bridge_available = self.agent_root.exists() and self.agent_root.is_dir()
        return self._bridge_available

    def _resolve_module_path(self, relative_path: str) -> Path:
        """Resolve a path relative to the AI&ML Agent Claude Main directory.

        Args:
            relative_path: Path relative to Claude Main root.
                          e.g. "01-knowledge-base/09-industrial-edge-plc/solutions/02-servo-current-anomaly/edge/train_servo_regression.py"
        """
        return self.agent_root / relative_path

    # ── Solution 01: PPO PID Auto-Tuning ──────────────────────────

    def load_ppo_tuner(self, **kwargs) -> Any:
        """Load the PPOPIDTuner from Solution 01.

        Returns None if bridge is unavailable.

        Args:
            **kwargs: Passed to PPOPIDTuner constructor (kp0, ki0, kd0, plc_ip).

        Returns:
            PPOPIDTuner instance or None.
        """
        if not self.bridge_available:
            return None

        tuner_path = self._resolve_module_path(
            "01-knowledge-base/09-industrial-edge-plc/solutions/"
            "01-furnace-temperature-pid/edge/train_poly_reg.py"
        )
        if not tuner_path.exists():
            return None

        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location("train_poly_reg", str(tuner_path))
            module = importlib.util.module_from_spec(spec)
            sys.modules["train_poly_reg"] = module
            spec.loader.exec_module(module)
            return module.PPOPIDTuner(**kwargs)
        except Exception:
            return None

    # ── Solution 02: Servo Current Regression Model ──────────────────

    def load_servo_current_model(self) -> Optional[Dict[str, Any]]:
        """Load the trained servo current regression model from Solution 02.

        Returns the model weights and thresholds as a dict:
          {"weights": [w0, w1, w2], "bias": float, "high_threshold": float,
           "low_threshold": float, "r_squared": float}

        Returns empty dict if bridge is unavailable.
        """
        if not self.bridge_available:
            return None

        model_dir = self._resolve_module_path(
            "01-knowledge-base/09-industrial-edge-plc/solutions/"
            "02-servo-current-anomaly/codesys/"
        )
        if not model_dir.exists():
            return None

        # Try to load model parameters from the CODESYS init file
        model_file = model_dir / "FB_Servo_CurrentCalc_Init.st"
        if not model_file.exists():
            return None

        try:
            return self._parse_servo_current_init(str(model_file))
        except Exception:
            return None

    def _parse_servo_current_init(self, filepath: str) -> Dict[str, Any]:
        """Parse FB_Servo_CurrentCalc_Init.st to extract model parameters."""
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()

        import re
        result: Dict[str, Any] = {}

        # Extract weight assignments like: wSpeed := 0.123;
        weight_patterns = {
            "weights": [
                (r"wSpeed\s*:=\s*([\d.eE+-]+)", 0),
                (r"wTorque\s*:=\s*([\d.eE+-]+)", 1),
                (r"wRuntime\s*:=\s*([\d.eE+-]+)", 2),
            ],
            "bias": r"bBias\s*:=\s*([\d.eE+-]+)",
            "high_threshold": r"rHighThreshold\s*:=\s*([\d.eE+-]+)",
            "low_threshold": r"rLowThreshold\s*:=\s*([\d.eE+-]+)",
        }

        weights = [0.0, 0.0, 0.0]
        for pattern, idx in weight_patterns["weights"]:
            m = re.search(pattern, content)
            if m:
                weights[idx] = float(m.group(1))
        result["weights"] = weights

        for key, pattern in [("bias", weight_patterns["bias"]),
                              ("high_threshold", weight_patterns["high_threshold"]),
                              ("low_threshold", weight_patterns["low_threshold"])]:
            m = re.search(pattern, content)
            if m:
                result[key] = float(m.group(1))

        return result if len(result) >= 4 else {}

    # ── SL1: Drift Root Cause Classifier ───────────────────────────

    def load_root_cause_classifier(self) -> Any:
        """Load the LightGBM root cause classifier from SL1.

        Returns a RootCauseClassifier instance or None.
        """
        if not self.bridge_available:
            return None

        classifier_path = self._resolve_module_path(
            "01-knowledge-base/06-engineering-cloud-platform/scripts/"
            "monitoring/drift_root_cause.py"
        )
        if not classifier_path.exists():
            return None

        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location(
                "drift_root_cause", str(classifier_path)
            )
            module = importlib.util.module_from_spec(spec)
            sys.modules["drift_root_cause"] = module
            spec.loader.exec_module(module)

            model_path = str(self._resolve_module_path(
                "01-knowledge-base/06-engineering-cloud-platform/scripts/"
                "monitoring/root_cause_model.txt"
            ))
            return module.RootCauseClassifier(model_path=model_path)
        except Exception:
            return None

    # ── AR4: Solution Auto-Generator ───────────────────────────────

    def load_solution_generator(self) -> Any:
        """Load the SolutionAutoGenerator from AR4.

        Returns a SolutionAutoGenerator instance or None.
        """
        if not self.bridge_available:
            return None

        gen_path = self._resolve_module_path(
            "01-knowledge-base/09-industrial-edge-plc/"
            "edge-common/solution_generator.py"
        )
        if not gen_path.exists():
            return None

        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location(
                "solution_generator", str(gen_path)
            )
            module = importlib.util.module_from_spec(spec)
            sys.modules["solution_generator"] = module
            spec.loader.exec_module(module)
            return module.SolutionAutoGenerator()
        except Exception:
            return None

    # ── CODESYS ST Export ──────────────────────────────────────────

    def export_codesys_st(
        self, annotations: List[Any], fb_name: str = "FB_ServoDiag"
    ) -> Optional[str]:
        """Generate CODESYS ST IF-THEN rules from AI annotations.

        Uses the RuleInjector from SL1 to convert detected anomaly patterns
        into PLC-compatible fault diagnosis rules.

        Args:
            annotations: List of AIAnnotation objects.
            fb_name: Target function block name.

        Returns:
            ST code string or None if bridge unavailable/export failed.
        """
        if not self.bridge_available:
            return None

        injector_path = self._resolve_module_path(
            "01-knowledge-base/06-engineering-cloud-platform/scripts/"
            "monitoring/drift_root_cause.py"
        )
        if not injector_path.exists():
            return None

        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location(
                "drift_root_cause", str(injector_path)
            )
            module = importlib.util.module_from_spec(spec)
            sys.modules["drift_root_cause"] = module
            spec.loader.exec_module(module)

            injector = module.RuleInjector()
            rules = []
            for ann in annotations[:20]:  # limit to top 20
                condition = self._annotation_to_condition(ann)
                if condition:
                    rules.append({
                        "condition": condition,
                        "action": ann.suggestion or ann.message,
                        "severity": ann.severity,
                    })

            return injector.inject(rules, fb_name) if rules else None
        except Exception:
            return None

    @staticmethod
    def _annotation_to_condition(ann) -> Optional[str]:
        """Convert an AIAnnotation to a CODESYS-compatible IF condition."""
        ch_map = {
            "Current": "rCurrentActual",
            "Velocity": "rVelocityActual",
            "Foll.Err": "rFollowingError",
            "Torque": "rTorqueActual",
            "Position": "rPositionActual",
        }
        var = ch_map.get(ann.channel)
        if not var:
            return None

        if ann.category == "current_saturation":
            return f"{var} > {ann.value * 0.8:.0f}"
        elif ann.category == "current_sensor_fault":
            return f"{var} = 0.0"
        elif ann.category == "tracking_absolute_limit":
            return f"{var} > {ann.value * 0.9:.0f}"
        elif ann.category in ("tracking_mechanical_bind", "tracking_gain_deficiency"):
            return f"{var} > {ann.value * 0.7:.0f}"
        else:
            return f"{var} > {ann.value * 0.5:.0f}"

    # ── Knowledge Sync ─────────────────────────────────────────────

    def get_solution_catalog(self) -> List[Dict[str, str]]:
        """Get the list of available solutions from AI&ML Agent catalog.

        Returns:
            List of {"name": str, "description": str, "path": str} dicts.
        """
        catalog_path = self.agent_root / "CATALOG.md"
        if not catalog_path.exists():
            return []

        try:
            with open(catalog_path, "r", encoding="utf-8") as f:
                content = f.read()
            # Parse the markdown catalog for solution entries
            solutions = []
            import re
            for match in re.finditer(
                r'###\s+(Solution\s+\d+[:\s]+[^\n]+)', content
            ):
                solutions.append({"name": match.group(1).strip(), "path": ""})
            return solutions
        except Exception:
            return []
