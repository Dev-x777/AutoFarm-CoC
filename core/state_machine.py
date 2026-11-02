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

        self.automation_enabled = False  # SAFETY DEFAULT: Autonomous attacking paused for inspection
        self.detection_overlay = True    # Bounding boxes overlay on website
        self.device.touch_enabled = False  # HARD SAFETY SHIELD: Hardware touch injection disabled!
        self.attacks_in_session = 0
        self.current_action = "Inspection Mode (Observe & Identify)"

        # Asynchronous perception worker: runs at 3-4 Hz without blocking video streamer
        self._perception_running = True
        self._perception_thread = threading.Thread(target=self._perception_worker, daemon=True, name="AsyncPerceptionWorker")
        self._perception_thread.start()

    def _perception_worker(self):
        """Asynchronously computes CV detections and village skeletons at 3-4 Hz without blocking video stream."""
        while getattr(self, "_perception_running", True):
            try:
                frame = self.device.capture_frame()
                if frame is not None and frame.size > 0:
                    state = self.vision.detect_state(frame)
                    entities = self.vision.detect_all_entities(frame)
                    self.vision.update_cached_detections(entities, state)
                time.sleep(0.25)
            except Exception:
                time.sleep(0.5)

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
        if hasattr(self.device, "ensure_game_running"):
            self.device.ensure_game_running()
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
        self._perception_running = False
        self.status = BotStatus.STOPPED
        self.current_action = "Stopped"
        self.device.stop_streamer()
        self.log("AutoFarm engine stopped.")

    def get_summary(self) -> Dict:
        """Returns real-time session telemetry."""
        is_fg = True
        if hasattr(self.device, "is_game_foreground"):
            is_fg = self.device.is_game_foreground()
        return {
            "status": self.status,
            "current_action": self.current_action,
            "automation_enabled": self.automation_enabled,
            "touch_enabled": getattr(self.device, "touch_enabled", False),
            "detection_overlay": self.detection_overlay,
            "is_game_foreground": is_fg,
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
        self.log("Inspection Mode Active: Learning & identifying village elements without tapping.")

        while not self._stop_event.is_set():
            if self._pause_event.is_set():
                time.sleep(1.0)
                continue

            try:
                # SAFETY SHIELD 1: Verify Clash of Clans is actively focused in foreground
                if self.device.mode != "mock" and hasattr(self.device, "is_game_foreground"):
                    if not self.device.is_game_foreground():
                        self.current_action = "Paused (Clash of Clans Inactive)"
                        time.sleep(1.0)
                        continue

                # SAFETY SHIELD 2: If automation / attacking is disabled (Inspection Mode)
                if not self.automation_enabled:
                    self.current_action = "Inspection Mode (Observe & Identify)"
                    time.sleep(0.5)
                    continue

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

                # 5. Attack Selection Menu (Multiplayer / Single player)
                if state == GameState.ATTACK_MENU:
                    self.current_action = "Selecting Multiplayer"
                    self.log("Attack menu open. Tapping 'Find a Match'...")
                    btn_find = self.vision.match_template(frame, "btn_find_match")
                    if btn_find:
                        self.device.tap(btn_find[0], btn_find[1])
                    else:
                        if self.device.device_width >= 2200:
                            self.device.tap(431, 793)
                        else:
                            self.device.tap(1420, 750)
                    time.sleep(1.8)
                    continue

                # 6. Army Confirmation Screen ("My Army" overview before battle search)
                if state == GameState.ARMY_CONFIRMATION:
                    self.current_action = "Confirming Army & Initiating Matchmaking"
                    self.log("Army screen verified. Tapping Battle to search base...")
                    btn_army = self.vision.match_template(frame, "btn_army_battle")
                    if btn_army:
                        self.device.tap(btn_army[0], btn_army[1])
                    else:
                        if self.device.device_width >= 2200:
                            self.device.tap(1947, 976)
                        else:
                            self.device.tap(1420, 750)
                    time.sleep(2.5)
                    continue

                # 7. Home Screen: Full Routine
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
                    btn_home = self.vision.match_template(frame, "btn_battle")
                    if btn_home:
                        self.device.tap(btn_home[0], btn_home[1])
                    else:
                        if self.device.device_width >= 2200:
                            self.device.tap(228, 960)
                        else:
                            self.device.tap(120, 960)
                    time.sleep(1.5)
                    continue

                # Unknown state: do NOT tap blindly. Wait safely for recognized view.
                self.current_action = "Observing (Awaiting Village Screen)"
                time.sleep(1.0)
                continue

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
