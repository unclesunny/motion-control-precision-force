"""
Shared fixtures for motion-control-precision-force integration tests.

Provides simulated EtherCAT master, scope engine, and AI pipeline fixtures
so tests can run without hardware.
"""

import sys
from pathlib import Path

import numpy as np
import pytest

# Ensure all source modules are on the path
_project_root = Path(__file__).resolve().parent.parent
_ecat_path = _project_root / "03-ethercat-master" / "bindings"
_scope_path = _project_root / "04-oscilloscope" / "src"
_ai_path = _project_root / "06-ai-analyzer"
_ai_src = _project_root / "06-ai-analyzer" / "ai_analyzer"

for _p in [_ecat_path, _scope_path, _ai_path, _ai_src]:
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


@pytest.fixture
def ec_master_sim():
    """Simulated EtherCAT master with one Delta A3 slave."""
    from ec_master import EcMaster
    master = EcMaster(adapter="sim")
    master.scan()
    yield master
    try:
        master.close()
    except Exception:
        pass


@pytest.fixture
def scope_engine_sim(ec_master_sim):
    """Scope engine attached to simulated master, fast sample rate for tests."""
    from scope_engine import ScopeEngine
    engine = ScopeEngine(
        master=ec_master_sim,
        sample_rate_hz=100,
        buffer_seconds=5,
        demo_mode=True,
    )
    yield engine
    engine.stop()


@pytest.fixture
def ai_pipeline():
    """AI analyzer pipeline with all detectors enabled."""
    from ai_analyzer import AIAnalyzerPipeline
    return AIAnalyzerPipeline(sample_rate_hz=100.0)


@pytest.fixture
def synthetic_waveform_1000():
    """Generate 1000 samples of 8-channel synthetic servo data.

    Returns:
        data: np.ndarray shape (8, 1000)
        timestamps: np.ndarray shape (1000,)
        channel_names: List[str]
    """
    sample_rate = 1000.0
    n_samples = 1000
    t = np.arange(n_samples) / sample_rate

    data = np.zeros((8, n_samples), dtype=np.float32)
    data[0] = 1000.0 * np.sin(2 * np.pi * 2.0 * t)              # Position
    data[1] = 500.0 * np.sin(2 * np.pi * 3.5 * t + 0.5)         # Velocity
    data[2] = 80.0 + 30.0 * np.sin(2 * np.pi * 5.0 * t)         # Current
    data[3] = 60.0 * np.sin(2 * np.pi * 2.0 * t + 1.2)          # Torque
    data[4] = 15.0 * np.sin(2 * np.pi * 7.0 * t)                # Foll.Err
    data[5] = (np.arange(n_samples) % 100 > 50).astype(np.float32)  # DIO
    data[6] = np.where(np.arange(n_samples) % 200 < 100, 0x0237, 0x0007).astype(np.float32)  # Status
    data[7] = (np.arange(n_samples) // 50 % 8).astype(np.float32)  # OpMode

    channel_names = ["Position", "Velocity", "Current", "Torque",
                     "Foll.Err", "DIO", "Status", "OpMode"]

    return data, t, channel_names

