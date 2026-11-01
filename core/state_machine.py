"""
Master State Machine for AutoFarm Clash of Clans Bot.
Coordinates Base Management, Smart Farming, Wall Upgrades, and Humanized Sessions.
"""

import random
import threading
import time
from typing import Callable, Dict, List, Optional

from config.settings import AppConfig
from core.attack_engine import SmartAttackEngine
from core.collector import ResourceCollector
from core.device import DeviceController
from core.trainer import TroopTrainer
from core.vision import GameState, VisionEngine
from core.wall_upgrader import WallUpgrader


class BotStatus:
    STOPPED = "STOPPED"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    COOLDOWN = "COOLDOWN"


class BotEngine:
    def __init__(self, config: AppConfig, log_callback: Optional[Callable[[str], None]] = None):
        self.config = config
        self.log_callback = log_callback or print
        self.status = BotStatus.STOPPED
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self.logs: List[str] = []

        # Initialize sub-modules
        self.device = DeviceController(
            mode=config.device.mode,
            serial=config.device.serial,
            adb_path=config.device.adb_path,
        )
        self.vision = VisionEngine()
        self.attacker = SmartAttackEngine(
            self.device, self.vision, config.farming, config.attack, log_callback=self.log
        )
        self.wall_upgrader = WallUpgrader(
            self.device, self.vision, config.walls, log_callback=self.log
        )
        self.trainer = TroopTrainer(
            self.device, self.vision, config.training, log_callback=self.log
        )
        self.collector = ResourceCollector(
            self.device, self.vision, config.home, log_callback=self.log
        )

        self.attacks_in_session = 0
        self.current_action = "Idle"

    def log(self, message: str):
        timestamp = time.strftime("%H:%M:%S")
        entry = f"[{timestamp}] {message}"
        self.logs.append(entry)
        if len(self.logs) > 300:
            self.logs.pop(0)
        self.log_callback(entry)

    def start(self):
        """Starts the autonomous bot loop in a background thread."""
        if self.status == BotStatus.RUNNING:
            return
        self._stop_event.clear()
        self._pause_event.clear()
        self.status = BotStatus.RUNNING
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        self.log("AutoFarm engine started.")

    def pause(self):
        """Pauses the bot operations."""
        self._pause_event.set()
        self.status = BotStatus.PAUSED
        self.log("AutoFarm engine paused.")

    def resume(self):
        """Resumes the bot operations."""
        self._pause_event.clear()
        self.status = BotStatus.RUNNING
        self.log("AutoFarm engine resumed.")

    def stop(self):
        """Stops the bot operations gracefully."""
        self._stop_event.set()
        self.status = BotStatus.STOPPED
        self.current_action = "Stopped"
        self.log("AutoFarm engine stopped.")

    def get_summary(self) -> Dict:
        """Returns real-time session telemetry."""
        return {
            "status": self.status,
            "current_action": self.current_action,
            "bases_scanned": self.attacker.stats.bases_scanned,
            "attacks_completed": self.attacker.stats.bases_attacked,
            "gold_looted": self.attacker.stats.total_gold_looted,
            "elixir_looted": self.attacker.stats.total_elixir_looted,
            "dark_looted": self.attacker.stats.total_dark_looted,
            "walls_upgraded": self.wall_upgrader.total_walls_upgraded,
            "last_loot": self.attacker.stats.last_loot_summary,
            "mode": self.device.mode,
        }

    def _run_loop(self):
        """Main autonomous decision loop."""
        self.log("Beginning autonomous farming cycle...")

        while not self._stop_event.is_set():
            if self._pause_event.is_set():
                time.sleep(1.0)
                continue

            try:
                frame = self.device.capture_frame()
                state = self.vision.detect_state(frame)

                # 1. Handle Reload / Out of sync popups
                if state == GameState.RELOAD_POPUP:
                    self.current_action = "Handling Reload Popup"
                    self.log("Detected Reload / Connection popup. Tapping 'Reload Game'...")
                    self.device.tap(960, 600)
                    time.sleep(5.0)
                    continue

                # 2. Battle End Screen (Return Home)
                if state == GameState.BATTLE_END:
                    self.current_action = "Returning Home from Battle"
                    self.log("Battle completed. Tapping 'Return Home'...")
                    self.device.tap(960, 920)
                    time.sleep(2.5)
                    continue

                # 3. Already in Battle
                if state == GameState.IN_BATTLE:
                    self.current_action = "In Active Battle"
                    self.log("Detected active battle. Resuming attack controller...")
                    self.attacker.execute_smart_attack()
                    continue

                # 4. Searching for Bases
                if state == GameState.BATTLE_SEARCH:
                    self.current_action = "Evaluating Base"
                    loot = self.vision.read_battle_loot(frame)
                    accepted, reason = self.attacker.evaluate_base(loot)
                    self.log(reason)

                    if accepted:
                        self.current_action = "Attacking Target Base"
                        self.attacker.execute_smart_attack()
                        self.attacks_in_session += 1
                        # Check session fatigue
                        if self.attacks_in_session >= self.config.humanizer.session_break_every_attacks:
                            self._trigger_session_break()
                    else:
                        delay = random.uniform(
                            self.config.farming.next_delay_min, self.config.farming.next_delay_max
                        )
                        time.sleep(delay)
                        self.attacker.click_next()
                        time.sleep(1.5)
                    continue

                # 5. Home Screen: Full Routine
                if state in (GameState.HOME, GameState.WALL_SELECTED):
                    self.current_action = "Base Management"
                    # Step A: Harvest internal collectors
                    self.collector.collect_resources()

                    # Step B: Auto Upgrade Walls (Before spending on other tasks)
                    if self.config.walls.enabled:
                        self.current_action = "Upgrading Walls"
                        self.wall_upgrader.run_upgrade_cycle()

                    # Step C: Train Army
                    self.current_action = "Training Army"
                    self.trainer.train_army()

                    # Step D: Initiate Attack Search
                    self.current_action = "Initiating Attack Search"
                    self.log("Initiating search for multiplayer target...")
                    # Tap Attack button at (120, 960)
                    self.device.tap(120, 960)
                    time.sleep(1.2)
                    # Tap "Find a Match" (Right button: 1420, 750)
                    self.device.tap(1420, 750)
                    time.sleep(2.0)
                    continue

                # Unknown state: tap screen center to clear random popovers
                self.current_action = "Syncing View"
                self.log(f"Unrecognized UI state: {state}. Deselecting overlays...")
                self.device.tap(200, 500)
                time.sleep(2.0)

            except Exception as e:
                self.log(f"Loop error: {e}. Retrying in 3 seconds...")
                time.sleep(3.0)

        self.status = BotStatus.STOPPED
        self.log("Bot loop terminated.")

    def _trigger_session_break(self):
        """Simulates human fatigue by resting after several consecutive attacks."""
        duration_min = random.uniform(
            self.config.humanizer.break_duration_minutes_min,
            self.config.humanizer.break_duration_minutes_max,
        )
        self.status = BotStatus.COOLDOWN
        self.current_action = f"Session Cooldown ({duration_min:.1f} mins)"
        self.log(f"Anti-Detection: Taking a human rest break for {duration_min:.1f} minutes.")
        self.attacks_in_session = 0

        # Wait in increments so we can exit if stopped
        end_time = time.time() + (duration_min * 60)
        while time.time() < end_time and not self._stop_event.is_set():
            time.sleep(2.0)

        if not self._stop_event.is_set():
            self.status = BotStatus.RUNNING
            self.log("Break finished. Resuming active farming.")
