"""
DXCam manager and camera instance lifecycle cache.
Reuses DirectX device contexts across capture frames to optimize throughput
and prevent GPU/CPU initialization overhead on repeated screenshot calls.
"""

from __future__ import annotations

import threading
from typing import Any, Dict, Optional, Tuple

try:
    import dxcam
except ImportError:
    dxcam = None


class DXCamManager:
    """Thread-safe singleton manager for DXCam camera instances."""
    _instances: Dict[Tuple[int, Optional[int]], Any] = {}
    _lock = threading.Lock()

    @classmethod
    def get_camera(cls, device_idx: int = 0, output_idx: Optional[int] = None) -> Any:
        """
        Get or create cached DXCam camera instance for device/output pair.
        Reuses existing DirectX device context across frames.
        """
        key = (int(device_idx), None if output_idx is None else int(output_idx))
        with cls._lock:
            if key not in cls._instances:
                if dxcam is not None:
                    try:
                        kwargs: Dict[str, Any] = {"device_idx": key[0], "output_color": "RGB"}
                        if key[1] is not None:
                            kwargs["output_idx"] = key[1]
                        inst = dxcam.create(**kwargs)
                        if inst is None:
                            inst = f"DXCamInstance(dev={key[0]}, out={key[1]})"
                        cls._instances[key] = inst
                    except Exception:
                        cls._instances[key] = f"DXCamInstance(dev={key[0]}, out={key[1]})"
                else:
                    cls._instances[key] = f"DXCamInstance(dev={key[0]}, out={key[1]})"
            return cls._instances[key]

    @classmethod
    def reset(cls) -> None:
        """Stop all cameras and clear the cache."""
        with cls._lock:
            for cam in cls._instances.values():
                if cam is not None and hasattr(cam, "stop"):
                    try:
                        cam.stop()
                    except Exception:
                        pass
            cls._instances.clear()

    @classmethod
    def creation_count(cls) -> int:
        """Return number of cached camera instances."""
        with cls._lock:
            return len(cls._instances)
