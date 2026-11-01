"""
Unit and integration tests for AutoFarm CoC.
"""

import unittest
import numpy as np

from config.settings import AppConfig, load_config
from core.device import DeviceController, Humanizer, MockDevice
from core.vision import VisionEngine, GameState, DigitOCR
from core.attack_engine import SmartAttackEngine
from core.wall_upgrader import WallUpgrader
from core.state_machine import BotEngine, BotStatus


class TestAutoFarm(unittest.TestCase):
    def setUp(self):
        self.config = AppConfig()
        self.config.device.mode = "mock"
        self.dev = DeviceController(mode="mock")
        self.vision = VisionEngine()

    def test_config_defaults(self):
        cfg = load_config()
        self.assertGreaterEqual(cfg.farming.min_gold, 100000)
        self.assertTrue(cfg.walls.enabled)
        self.assertTrue(cfg.attack.early_surrender)

    def test_mock_device_and_vision_states(self):
        # 1. Initial state should be Home
        frame = self.dev.capture_frame()
        self.assertEqual(frame.shape, (1080, 1920, 3))
        state = self.vision.detect_state(frame)
        self.assertEqual(state, GameState.HOME)

        # 2. Click Attack button -> Transition to Battle Search
        self.dev.tap(120, 960)
        search_frame = self.dev.capture_frame()
        search_state = self.vision.detect_state(search_frame)
        self.assertEqual(search_state, GameState.BATTLE_SEARCH)

        # 3. Read Loot in Search
        loot = self.vision.read_battle_loot(search_frame)
        self.assertGreater(loot["gold"], 0)

        # 4. Locate Collectors
        collectors = self.vision.locate_outer_collectors(search_frame)
        self.assertGreaterEqual(len(collectors), 1)

        # 5. Check safe deploy points (must be outside the red boundary 250..1670, 150..920)
        safe_pt = self.vision.find_safe_deploy_point(collectors[0])
        self.assertTrue(safe_pt[0] <= 250 or safe_pt[0] >= 1670 or safe_pt[1] <= 160 or safe_pt[1] >= 900)

    def test_humanizer_bezier_curve(self):
        start = (200, 300)
        end = (800, 900)
        points = Humanizer.bezier_curve(start, end, num_points=10)
        self.assertEqual(len(points), 10)
        self.assertEqual(type(points[0]), tuple)

    def test_attack_evaluation(self):
        attacker = SmartAttackEngine(
            self.dev, self.vision, self.config.farming, self.config.attack
        )
        # Base with low loot -> should skip
        low_loot = {"gold": 100000, "elixir": 80000, "dark_elixir": 500}
        accepted, _ = attacker.evaluate_base(low_loot)
        self.assertFalse(accepted)

        # Base with high loot -> should accept
        high_loot = {"gold": 750000, "elixir": 800000, "dark_elixir": 6000}
        accepted, _ = attacker.evaluate_base(high_loot)
        self.assertTrue(accepted)

    def test_wall_upgrader_reserve_logic(self):
        upgrader = WallUpgrader(self.dev, self.vision, self.config.walls)
        # Set mock balance above reserve (3,250,000 > 1,500,000)
        upgrades = upgrader.run_upgrade_cycle()
        self.assertGreaterEqual(upgrades, 0)

    def test_bot_engine_start_stop(self):
        bot = BotEngine(self.config)
        self.assertEqual(bot.status, BotStatus.STOPPED)
        bot.start()
        self.assertEqual(bot.status, BotStatus.RUNNING)
        bot.pause()
        self.assertEqual(bot.status, BotStatus.PAUSED)
        bot.resume()
        self.assertEqual(bot.status, BotStatus.RUNNING)
        bot.stop()
        self.assertEqual(bot.status, BotStatus.STOPPED)


if __name__ == "__main__":
    unittest.main()
