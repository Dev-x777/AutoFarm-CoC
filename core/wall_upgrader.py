"""
Smart Wall Upgrader for Clash of Clans.
Automatically spends surplus Gold and Elixir on walls while strictly preserving safety reserves.
"""

import time
from typing import Callable, List, Optional, Tuple

import cv2
import numpy as np

from config.settings import WallsConfig
from core.device import DeviceController
from core.vision import GameState, VisionEngine


class WallUpgrader:
    def __init__(
        self,
        device: DeviceController,
        vision: VisionEngine,
        config: WallsConfig,
        log_callback: Optional[Callable[[str], None]] = None,
    ):
        self.device = device
        self.vision = vision
        self.config = config
        self.log_callback = log_callback or print
        self.total_walls_upgraded = 0

    def log(self, msg: str):
        self.log_callback(f"[Walls] {msg}")

    def run_upgrade_cycle(self) -> int:
        """
        Executes a wall upgrade sequence if resources exceed the reserve threshold.
        Returns the number of wall pieces successfully upgraded.
        """
        if not self.config.enabled:
            return 0

        self.log("Checking balances for wall upgrades...")
        frame = self.device.capture_frame()
        state = self.vision.detect_state(frame)

        if state != GameState.HOME:
            self.log(f"Cannot upgrade walls from state: {state}. Must be on HOME screen.")
            return 0

        resources = self.vision.read_home_resources(frame)
        gold = resources.get("gold", 0)
        elixir = resources.get("elixir", 0)

        # In mock mode or fallback if top-right bar is obscured
        if gold == 0 and hasattr(self.device, "mock") and self.device.mock:
            gold = self.device.mock.gold
            elixir = self.device.mock.elixir

        surplus_gold = max(0, gold - self.config.reserve_gold)
        surplus_elixir = max(0, elixir - self.config.reserve_elixir)

        self.log(f"Current balances: Gold={gold:,} (Surplus: {surplus_gold:,}), Elixir={elixir:,} (Surplus: {surplus_elixir:,})")

        # Minimum required to attempt an upgrade
        min_wall_cost = 200_000
        can_upgrade_gold = surplus_gold >= min_wall_cost and self.config.preferred_resource in ("gold", "both")
        can_upgrade_elixir = surplus_elixir >= min_wall_cost and self.config.preferred_resource in ("elixir", "both")

        if not can_upgrade_gold and not can_upgrade_elixir:
            self.log("Insufficient surplus resources above reserve threshold. Skipping wall upgrades.")
            return 0

        upgraded_this_cycle = 0
        wall_points = self.config.wall_sample_points or [[960, 540], [900, 500], [1020, 580], [840, 460]]

        for pt in wall_points:
            if upgraded_this_cycle >= self.config.max_upgrades_per_cycle:
                break

            wx, wy = pt[0], pt[1]
            self.log(f"Inspecting wall candidate at ({wx}, {wy})...")
            # Tap wall segment
            self.device.tap(wx, wy)
            time.sleep(0.5)

            inspect_frame = self.device.capture_frame()
            inspect_state = self.vision.detect_state(inspect_frame)

            # Check if wall upgrade button is active
            if inspect_state == GameState.WALL_SELECTED or (
                hasattr(self.device, "mock") and self.device.mock and self.device.mock.current_state == "wall_inspect"
            ):
                self.log(f"Wall upgrade prompt confirmed. Upgrading segment #{upgraded_this_cycle + 1}...")
                # Tap the upgrade button (Center-bottom: 960, 895)
                self.device.tap(960, 895)
                time.sleep(0.6)

                # Tap confirmation if secondary dialog opens
                self.device.tap(1080, 650)
                time.sleep(0.4)

                upgraded_this_cycle += 1
                self.total_walls_upgraded += 1
            else:
                self.log("No upgrade button found at this point. Deselecting.")
                # Tap blank grass to clear selection
                self.device.tap(200, 500)
                time.sleep(0.3)

        # Deselect anything left selected
        self.device.tap(200, 500)
        self.log(f"Wall upgrade cycle complete. Successfully upgraded {upgraded_this_cycle} walls.")
        return upgraded_this_cycle
