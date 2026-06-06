"""
Unified Brand Loader — load any supported servo brand's parameter library.

Usage:
    from brand_loader import BrandLoader
    loader = BrandLoader()
    brands = loader.list_brands()           # all 12 brands
    params = loader.load("yaskawa-sigma7")  # get full parameter set
    scope_cfg = loader.scope_config("inovance-sv660")  # 8-ch config
"""

import json
from pathlib import Path
from typing import Dict, List, Optional


class BrandLoader:
    """Load any brand's parameter library, scope config, and CoE objects."""

    def __init__(self, base_dir: Optional[Path] = None):
        self.base = base_dir or Path(__file__).resolve().parent
        self._registry = None

    @property
    def registry(self) -> dict:
        if self._registry is None:
            with open(self.base / "brands.json", encoding="utf-8") as f:
                self._registry = json.load(f)
        return self._registry

    def list_brands(self) -> List[dict]:
        """List all supported brands with metadata."""
        return [
            {"key": k, **v}
            for k, v in self.registry["brands"].items()
        ]

    def get_brand(self, key: str) -> Optional[dict]:
        """Get metadata for a specific brand."""
        return self.registry["brands"].get(key)

    def load_objects(self, key: str) -> Optional[dict]:
        """Load CoE object dictionary for a brand."""
        brand = self.get_brand(key)
        if not brand:
            return None
        path = self.base / brand["coe_objects"]
        if not path.exists():
            return None
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def load_pdo_mapping(self, key: str) -> Optional[dict]:
        """Load PDO mapping for a brand."""
        brand = self.get_brand(key)
        if not brand:
            return None
        path = self.base / brand["pdo_mapping"]
        if not path.exists():
            return None
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def scope_config(self, key: str) -> Optional[dict]:
        """Load 8-channel scope configuration for a brand."""
        brand = self.get_brand(key)
        if not brand:
            return None

        # Try generated config first, then fall back to existing
        cfg_path = self.base / brand["scope_config"]
        if cfg_path.exists():
            with open(cfg_path, encoding="utf-8") as f:
                return json.load(f)

        return None

    def find_object(self, key: str, index: str) -> Optional[dict]:
        """Find a specific CoE object by index (e.g. '0x6078')."""
        objects = self.load_objects(key)
        if not objects:
            return None
        for obj in objects.get("objects", []):
            if obj["index"] == index:
                return obj
        return None

    def get_cia402_objects(self, key: str) -> List[dict]:
        """Get all CiA 402 objects for a brand."""
        objects = self.load_objects(key)
        if not objects:
            return []
        return [o for o in objects.get("objects", [])
                if o.get("category") == "cia402"]

    def summary(self) -> str:
        """Multi-line summary of all brands."""
        lines = []
        for key, b in self.registry["brands"].items():
            tier_icon = {"premium": "◆", "mid": "◇", "value": "○"}.get(b["tier"], "?")
            lines.append(
                f"  {tier_icon} {key:20s} {b['objects']:>4d} obj  "
                f"{b['cia402']:>2d} CiA402  {b['country']}  {b['name'][:40]}"
            )
        return "\n".join(lines)


# ── CLI ─────────────────────────────────────────────────────

def main():
    import sys

    loader = BrandLoader()

    if len(sys.argv) > 1 and sys.argv[1] == "list":
        print(loader.summary())
        return

    if len(sys.argv) > 2 and sys.argv[1] == "find":
        brand, idx = sys.argv[2], sys.argv[3]
        obj = loader.find_object(brand, idx)
        if obj:
            print(json.dumps(obj, indent=2, ensure_ascii=False))
        else:
            print(f"Object {idx} not found in {brand}")
        return

    # Default: summary
    print("Servo Parameter Library — Brand Loader")
    print("=" * 50)
    print(loader.summary())
    print(f"\n  Total: {loader.registry['summary']['total_brands']} brands, "
          f"{loader.registry['summary']['total_objects']} objects")
    print("\nUsage:")
    print("  python brand_loader.py list")
    print("  python brand_loader.py find yaskawa-sigma7 0x6078")


if __name__ == "__main__":
    main()
