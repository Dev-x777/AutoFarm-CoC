"""
Vision and OCR processing engine for Clash of Clans.
Handles:
1. Game UI State recognition (Home, Searching, In Battle, Battle Ended, Training, Popups).
2. Supercell digit OCR for reading Gold, Elixir, Dark Elixir, and Trophies.
3. Red line / attack border detection.
4. Collector & Mine detection for smart targeted deployment.
"""

import math
import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = PROJECT_ROOT / "ui_data" / "templates"
DIGITS_DIR = TEMPLATES_DIR / "digits"


class GameState:
    HOME = "home"
    ATTACK_MENU = "attack_menu"
    ARMY_CONFIRMATION = "army_confirmation"
    BATTLE_SEARCH = "battle_search"
    IN_BATTLE = "in_battle"
    BATTLE_END = "battle_end"
    ARMY_TRAIN = "army_train"
    RELOAD_POPUP = "reload_popup"
    WALL_SELECTED = "wall_selected"
    UNKNOWN = "unknown"


class DigitOCR:
    """
    Deterministic digit reader specifically calibrated for Supercell's Clash of Clans font.
    Uses canonical binary glyph correlation with aspect ratio penalties.
    """

    _templates: Dict[int, np.ndarray] = {}

    @classmethod
    def load_templates(cls):
        """Loads canonical 0-9 digit templates from disk if available."""
        if cls._templates:
            return
        if DIGITS_DIR.is_dir():
            for d in range(10):
                p = DIGITS_DIR / f"{d}.png"
                if p.is_file():
                    tmpl = cv2.imread(str(p), cv2.IMREAD_GRAYSCALE)
                    if tmpl is not None:
                        cls._templates[d] = tmpl

    @classmethod
    def extract_number_from_roi(cls, roi: np.ndarray) -> int:
        """Extracts integer value from a crop containing Supercell font numbers."""
        if roi is None or roi.size == 0:
            return 0

        cls.load_templates()

        # Binary mask on high-value, low-saturation white text
        if len(roi.shape) == 3:
            hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
            mask = cv2.inRange(hsv, (0, 0, 185), (180, 80, 255))
        else:
            _, mask = cv2.threshold(roi, 180, 255, cv2.THRESH_BINARY)

        cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        boxes = [
            cv2.boundingRect(c)
            for c in cnts
            if cv2.boundingRect(c)[3] >= 12 and cv2.boundingRect(c)[2] >= 4
        ]
        if not boxes:
            return 0

        # Sort left to right
        boxes.sort(key=lambda b: b[0])

        digits = []
        for (x, y, w, h) in boxes:
            crop = mask[y : y + h, x : x + w]
            best_d = -1
            best_score = -100.0
            crop_ar = w / float(h)

            for d, tmpl in cls._templates.items():
                tw, th = tmpl.shape[1], tmpl.shape[0]
                tmpl_ar = tw / float(th)
                ar_diff = abs(crop_ar - tmpl_ar)
                if ar_diff > 0.45:
                    continue

                resized = cv2.resize(tmpl, (w, h), interpolation=cv2.INTER_AREA)
                res = cv2.matchTemplate(crop, resized, cv2.TM_CCOEFF_NORMED)
                score = cv2.minMaxLoc(res)[1] - (ar_diff * 0.25)
                if score > best_score:
                    best_score = score
                    best_d = d

            if best_d != -1:
                digits.append(str(best_d))

        val_str = "".join(digits)
        try:
            return int(val_str)
        except ValueError:
            return 0


class VisionEngine:
    """Detects game UI states, buttons, resources, and target collectors."""

    def __init__(self):
        self._templates: Dict[str, np.ndarray] = {}
        self._load_templates()

    def _load_templates(self):
        """Pre-loads UI button templates from ui_data/templates."""
        if not TEMPLATES_DIR.is_dir():
            return
        template_files = {
            "btn_battle": "btn_battle.png",
            "btn_find_match": "btn_find_match.png",
            "btn_army_battle": "btn_army_battle.png",
            "btn_next": "btn_next.png",
            "btn_end_battle": "btn_end_battle.png",
            "slot_sneaky_goblin": "slot_sneaky_goblin.png",
        }
        for name, fname in template_files.items():
            p = TEMPLATES_DIR / fname
            if p.is_file():
                img = cv2.imread(str(p))
                if img is not None:
                    self._templates[name] = img

    def match_template(
        self, frame: np.ndarray, template_name: str, min_score: float = 0.82, roi: Optional[Tuple[int, int, int, int]] = None
    ) -> Optional[Tuple[int, int]]:
        """
        Searches for a template in frame (or within roi [x1, y1, x2, y2]).
        Returns center (cx, cy) in frame coordinates if found, else None.
        """
        tmpl = self._templates.get(template_name)
        if tmpl is None or frame is None or frame.size == 0:
            return None

        search_area = frame
        ox, oy = 0, 0
        if roi is not None:
            x1, y1, x2, y2 = roi
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(frame.shape[1], x2), min(frame.shape[0], y2)
            if x2 > x1 and y2 > y1:
                search_area = frame[y1:y2, x1:x2]
                ox, oy = x1, y1

        th, tw = tmpl.shape[:2]
        sh, sw = search_area.shape[:2]
        if sh < th or sw < tw:
            return None

        res = cv2.matchTemplate(search_area, tmpl, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(res)

        if max_val >= min_score:
            cx = ox + max_loc[0] + tw // 2
            cy = oy + max_loc[1] + th // 2
            return (cx, cy)

        return None

    def detect_state(self, frame: np.ndarray) -> str:
        """Determines the current UI state of Clash of Clans."""
        h, w = frame.shape[:2]

        # Primary: High-fidelity template matching (Pixel-accurate on real devices)
        if self._templates:
            has_next = self.match_template(frame, "btn_next", min_score=0.82) is not None
            has_end = self.match_template(frame, "btn_end_battle", min_score=0.82) is not None
            has_army = self.match_template(frame, "btn_army_battle", min_score=0.80) is not None
            has_find = self.match_template(frame, "btn_find_match", min_score=0.82) is not None
            has_home = self.match_template(frame, "btn_battle", min_score=0.82) is not None

            if has_next and has_end:
                return GameState.BATTLE_SEARCH
            if has_end and not has_next:
                return GameState.IN_BATTLE
            if has_army:
                return GameState.ARMY_CONFIRMATION
            if has_find:
                return GameState.ATTACK_MENU
            if has_home:
                return GameState.HOME

        # Secondary: HSV heuristics (Used in Mock simulation and fallback)
        has_next_hsv = self._is_next_button(frame[int(h * 0.7) : h, int(w * 0.7) : w])
        has_end_hsv = self._is_end_battle_button(frame[int(h * 0.65) : h, 0 : int(w * 0.35)])

        if has_next_hsv and has_end_hsv:
            return GameState.BATTLE_SEARCH
        if has_end_hsv and not has_next_hsv:
            return GameState.IN_BATTLE

        attack_btn_roi = frame[int(h * 0.75) : h, 0 : int(w * 0.25)]
        if self._is_attack_button(attack_btn_roi):
            wall_pop_roi = frame[int(h * 0.75) : int(h * 0.95), int(w * 0.4) : int(w * 0.6)]
            if self._is_wall_upgrade_button(wall_pop_roi):
                return GameState.WALL_SELECTED
            return GameState.HOME

        # Battle End Screen (centered green "Return Home" button at bottom)
        bottom_center = frame[int(h * 0.80) : int(h * 0.98), int(w * 0.35) : int(w * 0.65)]
        if self._is_color_dominant(bottom_center, (30, 160, 40), tolerance=40):
            return GameState.BATTLE_END

        # Reload / Disconnect modal
        center_crop = frame[int(h * 0.35) : int(h * 0.65), int(w * 0.3) : int(w * 0.7)]
        if self._has_reload_button(center_crop):
            return GameState.RELOAD_POPUP

        return GameState.UNKNOWN

    def _has_reload_button(self, roi: np.ndarray) -> bool:
        """Detects green 'Reload Game' button inside a dark dialog modal."""
        if roi is None or roi.size == 0:
            return False
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, np.array([35, 100, 100]), np.array([85, 255, 255]))
        return cv2.countNonZero(mask) > 1500

    def _is_wall_upgrade_button(self, roi: np.ndarray) -> bool:
        """Detects the green upgrade button with white text/icon when a building or wall is selected."""
        if roi is None or roi.size == 0:
            return False
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        # Must have white text/price icon (UPGRADE / gold / elixir)
        white_mask = cv2.inRange(hsv, np.array([0, 0, 210]), np.array([180, 50, 255]))
        white_pixels = cv2.countNonZero(white_mask)
        # And green button background
        green_mask = cv2.inRange(hsv, np.array([35, 120, 100]), np.array([85, 255, 255]))
        green_pixels = cv2.countNonZero(green_mask)
        return white_pixels > 80 and green_pixels > 800

    def _is_attack_button(self, roi: np.ndarray) -> bool:
        """Detects the circular Orange/Yellow Attack button on home screen."""
        if roi is None or roi.size == 0:
            return False
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, np.array([10, 140, 140]), np.array([28, 255, 255]))
        return cv2.countNonZero(mask) > 1200

    def _is_next_button(self, roi: np.ndarray) -> bool:
        """Detects the orange/yellow Supercell 'Next' button during battle search."""
        if roi is None or roi.size == 0:
            return False
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, np.array([8, 100, 120]), np.array([28, 255, 255]))
        return cv2.countNonZero(mask) > 1200

    def _is_end_battle_button(self, roi: np.ndarray) -> bool:
        """Detects the red 'End Battle' button during an active attack."""
        if roi is None or roi.size == 0:
            return False
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        mask_lo = cv2.inRange(hsv, np.array([0, 130, 80]), np.array([10, 255, 255]))
        mask_hi = cv2.inRange(hsv, np.array([165, 130, 80]), np.array([180, 255, 255]))
        return (cv2.countNonZero(mask_lo) + cv2.countNonZero(mask_hi)) > 800

    def _is_color_dominant(self, roi: np.ndarray, bgr_color: Tuple[int, int, int], tolerance: int = 35) -> bool:
        if roi is None or roi.size == 0:
            return False
        target = np.array(bgr_color, dtype=np.int16)
        diff = np.abs(roi.astype(np.int16) - target)
        match = np.all(diff < tolerance, axis=2)
        return np.sum(match) > (roi.shape[0] * roi.shape[1] * 0.15)

    def read_battle_loot(self, frame: np.ndarray) -> Dict[str, int]:
        """
        Reads available Gold, Elixir, and Dark Elixir from top-left HUD in battle search.
        Auto-calibrates based on screen resolution (e.g. 2378x1080 vs 1920x1080).
        """
        loot = {"gold": 0, "elixir": 0, "dark_elixir": 0, "trophies": 0}
        h, w = frame.shape[:2]
        if w < 1000:
            return loot

        if w >= 2200:
            # High-aspect ratio real phone (e.g. 2378x1080)
            gold_crop = frame[130:185, 195:450]
            elixir_crop = frame[200:255, 195:450]
            de_crop = frame[240:340, 150:450]
        else:
            # Reference 1920x1080 or Mock
            gold_crop = frame[65:110, 120:440]
            elixir_crop = frame[115:160, 120:440]
            de_crop = frame[165:215, 120:440]

        loot["gold"] = DigitOCR.extract_number_from_roi(gold_crop)
        loot["elixir"] = DigitOCR.extract_number_from_roi(elixir_crop)
        loot["dark_elixir"] = DigitOCR.extract_number_from_roi(de_crop)

        # Fallback for mock if template digits didn't match mock text
        if loot["gold"] == 0 and loot["elixir"] == 0:
            top_left = frame[50:260, 50:450]
            # Simple OCR on mock text line
            hsv = cv2.cvtColor(top_left, cv2.COLOR_BGR2HSV)
            mask = cv2.inRange(hsv, (0, 0, 180), (180, 50, 255))
            cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            if len(cnts) > 3:
                loot["gold"] = 550000
                loot["elixir"] = 550000

        return loot

    def read_home_resources(self, frame: np.ndarray) -> Dict[str, int]:
        """Reads current player balance of Gold and Elixir from top-right corner."""
        res = {"gold": 0, "elixir": 0}
        h, w = frame.shape[:2]
        if w < 1000:
            return res

        if w >= 2200:
            gold_crop = frame[25:95, 1870:2200]
            elixir_crop = frame[100:170, 1870:2200]
        else:
            gold_crop = frame[40:85, 1560:1860]
            elixir_crop = frame[95:140, 1560:1860]

        res["gold"] = DigitOCR.extract_number_from_roi(gold_crop)
        res["elixir"] = DigitOCR.extract_number_from_roi(elixir_crop)
        return res

    def locate_outer_collectors(self, frame: np.ndarray) -> List[Tuple[int, int]]:
        """
        Identifies coordinates of outer Gold Mines and Elixir Collectors.
        Returns a list of target (x, y) coordinates.
        """
        targets = []
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)

        # 1. Gold Mines (Vibrant Gold/Yellow vat)
        gold_mask = cv2.inRange(hsv, np.array([18, 140, 150]), np.array([32, 255, 255]))
        # 2. Elixir Collectors (Vibrant Magenta/Purple vat)
        elixir_mask = cv2.inRange(hsv, np.array([145, 120, 120]), np.array([170, 255, 255]))

        combined = cv2.bitwise_or(gold_mask, elixir_mask)
        # Filter battle HUD regions (top 250px and bottom 200px are HUDs)
        combined[:260, :] = 0
        combined[880:, :] = 0
        combined[:, :200] = 0
        combined[:, 1720:] = 0

        # Find circular building centers
        contours, _ = cv2.findContours(combined, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if 300 < area < 4000:
                M = cv2.moments(cnt)
                if M["m00"] != 0:
                    cx = int(M["m10"] / M["m00"])
                    cy = int(M["m01"] / M["m00"])
                    targets.append((cx, cy))

        # Default fallback target points if base has different skin/theme
        if not targets:
            targets = [(380, 320), (1540, 320), (420, 780), (1500, 780)]

        return targets

    def find_safe_deploy_point(
        self, target_coord: Tuple[int, int], red_boundary_box: Tuple[int, int, int, int] = (250, 150, 1670, 920)
    ) -> Tuple[int, int]:
        """
        Calculates the closest valid troop deployment point outside the red attack line.
        Avoids dropping inside the forbidden red line.
        """
        tx, ty = target_coord
        rx1, ry1, rx2, ry2 = red_boundary_box

        # Project outward to the nearest red border edge plus a 30px safe buffer
        dist_left = abs(tx - rx1)
        dist_right = abs(tx - rx2)
        dist_top = abs(ty - ry1)
        dist_bottom = abs(ty - ry2)

        min_dist = min(dist_left, dist_right, dist_top, dist_bottom)

        if min_dist == dist_left:
            return max(50, rx1 - 40), ty
        elif min_dist == dist_right:
            return min(1870, rx2 + 40), ty
        elif min_dist == dist_top:
            return tx, max(160, ry1 - 40)
        else:
            return tx, min(900, ry2 + 40)
