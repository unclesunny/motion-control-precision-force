# AI Analyzer Models

Place trained model files here. The `AIAnalyzerBridge` loads them at runtime.

## Expected Files

| File | Purpose | Source |
|------|---------|--------|
| `force_ppo.pth` | PPO policy network for force control | Phase 2 — PPO training |
| `root_cause_model.txt` | LightGBM text model (drift root cause) | AI&ML Agent SL1 |
| `servo_current_params.json` | Linear regression weights + thresholds | AI&ML Agent Solution 02 |

## Format: servo_current_params.json

```json
{
  "weights": [0.0, 1.5, 0.02],
  "bias": 10.0,
  "high_threshold": 1.25,
  "low_threshold": 0.70,
  "r_squared": 0.92
}
```

## Format: root_cause_model.txt

Standard LightGBM `model_to_string()` text format. Loaded by `RootCauseClassifier`.
