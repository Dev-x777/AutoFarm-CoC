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
        self.has_trained_once = False

    def log(self, msg: str):
        self.log_callback(f"[Trainer] {msg}")

    def train_army(self, force: bool = False) -> bool:
        """Opens training menu and queues the selected Quick Train army slot."""
        if not self.config.auto_train:
            return False

        # Modern Clash of Clans zero training period: Queue once, then army is instantly ready
        if getattr(self.config, "instant_training", True) and self.has_trained_once and not force:
            self.log("Modern zero training period active: Army is instantly ready.")
            return True

        self.log(f"Queuing Army from Quick Train Slot #{self.config.quick_train_slot}...")
        # 1. Tap Army / Edit Army button on attack menu or calibrated CPH2707 button
        frame = self.device.capture_frame()
        state = self.vision.detect_state(frame)
        if state == GameState.HOME:
            btn_battle = self.vision.match_template(frame, "btn_battle")
            bx, by = btn_battle if btn_battle else (228, 960)
            self.device.tap(bx, by)
            time.sleep(1.2)
            frame = self.device.capture_frame()

        btn_edit = self.vision.match_template(frame, "btn_edit_army")
        ex, ey = btn_edit if btn_edit else (329, 1008)
        self.device.tap(ex, ey)
        time.sleep(1.2)

        # 2. Tap 'Quick Train' tab at top
        self.device.tap(1050, 130)
        time.sleep(0.6)

        # 3. Tap 'Train' button for configured slot:
        # Slot 1: ~ (1420, 310)
        # Slot 2: ~ (1420, 480)
        # Slot 3: ~ (1420, 650)
        slot_y = 310 + (self.config.quick_train_slot - 1) * 170
        self.device.tap(1420, slot_y)
        time.sleep(0.5)

        # 4. Close Training Menu
        btn_close = self.vision.match_template(self.device.capture_frame(), "btn_army_close")
        cx, cy = btn_close if btn_close else (2110, 86)
        self.device.tap(cx, cy)
        time.sleep(0.8)

        self.has_trained_once = True
        self.log("Army training queued successfully.")
        return True
