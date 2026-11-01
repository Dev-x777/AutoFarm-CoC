"""
Resource Collector for Clash of Clans.
Automatically collects Gold, Elixir, and Dark Elixir from village mines and pumps.
"""

import time
from typing import Callable, List, Optional, Tuple

from config.settings import HomeConfig
from core.device import DeviceController
from core.vision import GameState, VisionEngine


class ResourceCollector:
    def __init__(
        self,
        device: DeviceController,
        vision: VisionEngine,
        config: HomeConfig,
        log_callback: Optional[Callable[[str], None]] = None,
    ):
        self.device = device
        self.vision = vision
        self.config = config
        self.log_callback = log_callback or print
        self.last_collect_time: float = 0.0

    def log(self, msg: str):
        self.log_callback(f"[Collector] {msg}")

    def collect_resources(self, force: bool = False):
        """Taps standard resource collector locations on the home village."""
        if not self.config.auto_collect_resources and not force:
            return

        now = time.time()
        if not force and (now - self.last_collect_time) < self.config.collect_interval_seconds:
            return

        self.log("Harvesting home base mines and elixir pumps...")
        # Common collector cluster points across typical village layouts
        collect_points = [
            (680, 480),
            (760, 420),
            (1150, 450),
            (1220, 520),
            (720, 680),
            (820, 720),
            (1100, 700),
            (1200, 640),
        ]

        for x, y in collect_points:
            self.device.tap(x, y)
            time.sleep(0.15)

        self.last_collect_time = now
        self.log("Harvesting completed.")
