"""
Troop Training Manager for Clash of Clans.
Automates army replenishment using the in-game 'Quick Train' feature.
"""

import time
from typing import Callable, Optional

from config.settings import TrainingConfig
from core.device import DeviceController
from core.vision import GameState, VisionEngine


class TroopTrainer:
    def __init__(
        self,
        device: DeviceController,
        vision: VisionEngine,
        config: TrainingConfig,
        log_callback: Optional[Callable[[str], None]] = None,
    ):
        self.device = device
        self.vision = vision
        self.config = config
        self.log_callback = log_callback or print

    def log(self, msg: str):
        self.log_callback(f"[Trainer] {msg}")

    def train_army(self) -> bool:
        """Opens training menu and queues the selected Quick Train army slot."""
        if not self.config.auto_train:
            return False

        self.log(f"Queuing Army from Quick Train Slot #{self.config.quick_train_slot}...")
        # 1. Tap Army Overview icon at bottom-left: (95, 825)
        self.device.tap(95, 825)
        time.sleep(0.8)

        # 2. Tap 'Quick Train' tab at top: (1050, 130)
        self.device.tap(1050, 130)
        time.sleep(0.6)

        # 3. Tap 'Train' button for configured slot:
        # Slot 1: ~ (1420, 310)
        # Slot 2: ~ (1420, 480)
        # Slot 3: ~ (1420, 650)
        slot_y = 310 + (self.config.quick_train_slot - 1) * 170
        self.device.tap(1420, slot_y)
        time.sleep(0.5)

        # 4. Close Training Menu (X button at top-right: 1620, 120)
        self.device.tap(1620, 120)
        time.sleep(0.5)

        self.log("Army training queued successfully.")
        return True
