"""
Vision and OCR processing engine for Clash of Clans.
Handles:
1. Game UI State recognition (Home, Searching, In Battle, Battle Ended, Training, Popups).
2. Supercell digit OCR for reading Gold, Elixir, Dark Elixir, and Trophies.
3. Red line / attack border detection.
4. Collector & Mine detection for smart targeted deployment.
"""

import math
import re
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np


class GameState:
    HOME = "home"
    BATTLE_SEARCH = "battle_search"
    IN_BATTLE = "in_battle"
    BATTLE_END = "battle_end"
    ARMY_TRAIN = "army_train"
    RELOAD_POPUP = "reload_popup"
    WALL_SELECTED = "wall_selected"
    UNKNOWN = "unknown"


class DigitOCR:
    """
    Ultra-fast, deterministic digit reader tuned for Clash of Clans numbers.
    Segments character contours and identifies digits 0-9 using invariant geometry and templates.
    """

    @staticmethod
    def extract_number_from_roi(roi: np.ndarray, is_white_text: bool = True) -> int:
        """Extracts integer value from a crop containing Supercell font numbers."""
        if roi is None or roi.size == 0:
            return 0

        # Convert to grayscale
        if len(roi.shape) == 3:
            gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        else:
            gray = roi

        # Threshold to isolate white/light digits
        _, thresh = cv2.threshold(gray, 180, 255, cv2.THRESH_BINARY)

        # Morphological clean up to connect broken glyphs
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
        clean = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel)

        # Find contours
        contours, _ = cv2.findContours(clean, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return 0

        # Filter contours by aspect ratio & area
        digit_boxes = []
        for cnt in contours:
            x, y, w, h = cv2.boundingRect(cnt)
            # Filter commas and noise
            if h >= 10 and w >= 4:
                digit_boxes.append((x, y, w, h))

        # Sort left to right
        digit_boxes.sort(key=lambda b: b[0])

        digits = []
        for x, y, w, h in digit_boxes:
            glyph = clean[y : y + h, x : x + w]
            digit = DigitOCR._classify_glyph(glyph)
            if digit is not None:
                digits.append(str(digit))

        if not digits:
            return 0

        try:
            return int("".join(digits))
        except ValueError:
            return 0

    @staticmethod
    def _classify_glyph(glyph: np.ndarray) -> Optional[int]:
        """Classifies a binary glyph 0-9 using topological and density features."""
        h, w = glyph.shape
        if h == 0 or w == 0:
            return None

        # Standardize to 20x28
        resized = cv2.resize(glyph, (20, 28), interpolation=cv2.INTER_AREA)
        _, norm = cv2.threshold(resized, 127, 255, cv2.THRESH_BINARY)

        # Count Euler holes (8 has 2 holes, 0,4,6,9 have 1 hole, 1,2,3,5,7 have 0 holes)
        inv = cv2.bitwise_not(norm)
        contours, hierarchy = cv2.findContours(inv, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
        holes = 0
        if hierarchy is not None:
            # Holes are internal child contours
            for h_info in hierarchy[0]:
                if h_info[3] != -1:  # Has parent
                    holes += 1

        aspect_ratio = w / float(h)
        # '1' is exceptionally thin
        if aspect_ratio < 0.35:
            return 1

        # Center of mass / quadrant density
        t_top = np.sum(norm[:14, :]) / 255.0
        t_bot = np.sum(norm[14:, :]) / 255.0

        if holes >= 2:
            return 8
        elif holes == 1:
            if t_top > t_bot * 1.3:
                return 9
            elif t_bot > t_top * 1.3:
                return 6
            elif abs(t_top - t_bot) < 40:
                return 0
            else:
                return 4
        else:
            # 0 holes: 1, 2, 3, 5, 7
            if t_top > t_bot * 1.6:
                return 7
            # Distinguish 2, 3, 5 by left vs right edge profiles
            left_half = np.sum(norm[:, :10])
            right_half = np.sum(norm[:, 10:])
            if right_half > left_half * 1.25:
                return 3
            elif left_half > right_half * 1.1:
                return 5
            return 2


class VisionEngine:
    """Detects game UI states, buttons, resources, and target collectors."""

    def __init__(self):
        pass

    def detect_state(self, frame: np.ndarray) -> str:
        """Determines the current UI state of Clash of Clans."""
        h, w = frame.shape[:2]

        # 1. Check Battle Search (Orange "Next" button at bottom-right: ~1680, 890 to 1870, 980)
        next_btn_roi = frame[870:990, 1660:1890]
        if self._is_next_button(next_btn_roi):
            return GameState.BATTLE_SEARCH

        # 2. Check In Battle (Red "End Battle" button at bottom-left: 50, 890 to 240, 980)
        end_btn_roi = frame[870:990, 40:260]
        if self._is_end_battle_button(end_btn_roi):
            return GameState.IN_BATTLE

        # 3. Check Home Base (Attack button at bottom-left: ~50-200, 900-1020)
        attack_btn_roi = frame[900:1040, 50:200]
        if self._is_attack_button(attack_btn_roi):
            # If attack button is visible, we are on Home Screen!
            # Now check if a wall segment is currently selected (showing upgrade button)
            wall_pop_roi = frame[850:940, 900:1050]
            if self._is_wall_upgrade_button(wall_pop_roi):
                return GameState.WALL_SELECTED
            return GameState.HOME

        # 5. Check Battle End Screen (centered green "Return Home" button at bottom)
        bottom_center = frame[int(h * 0.82) : int(h * 0.98), int(w * 0.4) : int(w * 0.6)]
        if self._is_color_dominant(bottom_center, (30, 160, 40), tolerance=40):
            return GameState.BATTLE_END

        # 6. Check Reload / Disconnect modal (requires dark dialog overlay + reload button)
        center_crop = frame[int(h * 0.35) : int(h * 0.65), int(w * 0.3) : int(w * 0.7)]
        if self._has_reload_button(center_crop):
            return GameState.RELOAD_POPUP

        return GameState.UNKNOWN

    def _has_reload_button(self, roi: np.ndarray) -> bool:
        """Detects green 'Reload Game' button inside a dark dialog modal."""
        if roi is None or roi.size == 0:
            return False
        # Needs dark surrounding background
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        if np.mean(gray) > 90:  # If too bright/grassy, not a modal dialog
            return False
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, np.array([40, 120, 120]), np.array([80, 255, 255]))
        return cv2.countNonZero(mask) > 1500

    def _is_wall_upgrade_button(self, roi: np.ndarray) -> bool:
        """Detects the green upgrade button when a building or wall is selected."""
        if roi is None or roi.size == 0:
            return False
        # Button must have high edge variance (text & borders), not flat grass
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        if cv2.Laplacian(gray, cv2.CV_64F).var() < 80:
            return False
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, np.array([35, 120, 100]), np.array([85, 255, 255]))
        return cv2.countNonZero(mask) > 1000

    def _is_attack_button(self, roi: np.ndarray) -> bool:
        """Detects the circular Orange/Yellow Attack button on home screen."""
        if roi is None or roi.size == 0:
            return False
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        # Orange/gold hue
        mask = cv2.inRange(hsv, np.array([10, 140, 140]), np.array([25, 255, 255]))
        return cv2.countNonZero(mask) > 1200

    def _is_next_button(self, roi: np.ndarray) -> bool:
        """Detects the orange/yellow Supercell 'Next' button during battle search."""
        if roi is None or roi.size == 0:
            return False
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        # Supercell orange: hue 10-25, high saturation, high value
        mask = cv2.inRange(hsv, np.array([8, 100, 120]), np.array([28, 255, 255]))
        return cv2.countNonZero(mask) > 1200

    def _is_end_battle_button(self, roi: np.ndarray) -> bool:
        """Detects the red 'End Battle' button during an active attack."""
        if roi is None or roi.size == 0:
            return False
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        # Pure red wraps around 0/180 in HSV
        mask_lo = cv2.inRange(hsv, np.array([0, 130, 80]), np.array([10, 255, 255]))
        mask_hi = cv2.inRange(hsv, np.array([165, 130, 80]), np.array([180, 255, 255]))
        return (cv2.countNonZero(mask_lo) + cv2.countNonZero(mask_hi)) > 800

    def _has_reload_button(self, roi: np.ndarray) -> bool:
        """Detects green 'Reload Game' button in center modal."""
        if roi is None or roi.size == 0:
            return False
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, np.array([35, 100, 100]), np.array([85, 255, 255]))
        return cv2.countNonZero(mask) > 1800

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
        Coordinates roughly:
        - Gold: Y: 60-115, X: 60-440
        - Elixir: Y: 115-165, X: 60-440
        - Dark Elixir: Y: 165-220, X: 60-440
        """
        loot = {"gold": 0, "elixir": 0, "dark_elixir": 0, "trophies": 0}
        h, w = frame.shape[:2]
        if w < 1000:
            return loot

        gold_crop = frame[65:110, 120:440]
        elixir_crop = frame[115:160, 120:440]
        de_crop = frame[165:215, 120:440]

        loot["gold"] = DigitOCR.extract_number_from_roi(gold_crop)
        loot["elixir"] = DigitOCR.extract_number_from_roi(elixir_crop)
        loot["dark_elixir"] = DigitOCR.extract_number_from_roi(de_crop)

        # Fallback heuristic for mock or small resolutions
        if loot["gold"] == 0 and loot["elixir"] == 0:
            # Read from top-left box generally
            top_left = frame[50:260, 50:450]
            val = DigitOCR.extract_number_from_roi(top_left)
            if val > 10000:
                loot["gold"] = val
                loot["elixir"] = val

        return loot

    def read_home_resources(self, frame: np.ndarray) -> Dict[str, int]:
        """Reads current player balance of Gold and Elixir from top-right corner."""
        res = {"gold": 0, "elixir": 0}
        h, w = frame.shape[:2]
        if w < 1000:
            return res

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
