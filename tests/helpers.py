"""
Shared test helpers for motion-control-precision-force integration tests.
"""


def assert_annotation_structure(ann):
    """Validate that an AIAnnotation has all required fields."""
    assert hasattr(ann, "timestamp")
    assert hasattr(ann, "channel")
    assert hasattr(ann, "category")
    assert hasattr(ann, "severity")
    assert ann.severity in ("info", "warning", "critical")
    assert hasattr(ann, "confidence")
    assert 0.0 <= ann.confidence <= 1.0
    assert hasattr(ann, "message")
    assert len(ann.message) > 0
    assert hasattr(ann, "suggestion")
    assert hasattr(ann, "value")


def assert_anomaly_event_structure(event):
    """Validate that an AnomalyEvent has all required fields."""
    assert hasattr(event, "timestamp")
    assert hasattr(event, "channel")
    assert hasattr(event, "severity")
    assert hasattr(event, "message")
    assert hasattr(event, "value")
