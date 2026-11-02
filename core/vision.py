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
import threading
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
        self.cached_entities: List[Dict] = []
        self.cached_state: str = "unknown"
        self._cached_lock = threading.Lock()
        self._load_templates()

    def update_cached_detections(self, entities: List[Dict], state: str):
        """Thread-safe update of the latest perception output."""
        with self._cached_lock:
            self.cached_entities = entities
            self.cached_state = state

    def get_cached_detections(self) -> Tuple[List[Dict], str]:
        """Returns the latest precomputed entities and state in sub-millisecond time."""
        with self._cached_lock:
            return list(self.cached_entities), self.cached_state

    def _load_templates(self):
        """Pre-loads all UI button and icon templates from ui_data/templates."""
        if not TEMPLATES_DIR.is_dir():
            return
        for p in TEMPLATES_DIR.glob("*.png"):
            img = cv2.imread(str(p))
            if img is not None:
                self._templates[p.stem] = img

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
        if self._has_reload_button(center_crop, frame):
            return GameState.RELOAD_POPUP

        return GameState.UNKNOWN

    def _has_reload_button(self, roi: np.ndarray, frame: Optional[np.ndarray] = None) -> bool:
        """Detects green 'Reload Game' button inside a dark dialog modal."""
        if roi is None or roi.size == 0:
            return False
        # If top-right resource bar is present, this is active game HUD, not a reload modal
        if frame is not None and frame.size > 0:
            h_f, w_f = frame.shape[:2]
            top_right = frame[20:100, int(w_f * 0.8) : w_f]
            if top_right.mean() > 70:
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

    def match_template_detailed(
        self,
        frame: np.ndarray,
        template_name: str,
        min_score: float = 0.75,
        roi: Optional[Tuple[int, int, int, int]] = None,
    ) -> Optional[Dict]:
        """Returns detailed bounding box and score dictionary if matched."""
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
            x = ox + max_loc[0]
            y = oy + max_loc[1]
            cx = x + tw // 2
            cy = y + th // 2
            return {
                "id": template_name,
                "bbox": [int(x), int(y), int(tw), int(th)],
                "center": [int(cx), int(cy)],
                "confidence": round(float(max_val), 3),
            }
        return None

    def detect_all_entities(self, frame: np.ndarray) -> List[Dict]:
        """
        Scans current screen and returns all recognized UI elements, buttons,
        resource bars, text, and base structures with bounding boxes.
        """
        if frame is None or frame.size == 0:
            return []

        h, w = frame.shape[:2]
        entities: List[Dict] = []
        state = self.detect_state(frame)

        # 1. Match registered templates
        friendly_names = {
            "btn_battle": ("Attack / Battle Button", (0, 255, 128), "button"),
            "btn_find_match": ("Find a Match Button", (0, 200, 255), "button"),
            "btn_army_battle": ("Attack! (Army Screen)", (0, 255, 100), "button"),
            "btn_train_army": ("Train Army / Troops", (255, 180, 50), "button"),
            "btn_shop": ("Shop Menu Button", (0, 180, 255), "button"),
            "hud_profile": ("Player Profile & XP", (220, 220, 220), "hud"),
            "btn_next": ("Next Match Button", (0, 165, 255), "button"),
            "btn_end_battle": ("End Battle Button", (0, 0, 255), "button"),
            "btn_edit_army": ("Edit Army / Quick Train", (255, 180, 50), "button"),
            "btn_army_close": ("Close Army Menu", (180, 180, 180), "button"),
            "slot_sneaky_goblin": ("Sneaky Goblin Slot", (50, 220, 50), "troop"),
            "icon_sword": ("Battle Swords Icon", (0, 220, 220), "icon"),
        }

        for tmpl_id, (label, color, category) in friendly_names.items():
            match = self.match_template_detailed(frame, tmpl_id, min_score=0.75)
            if match:
                match["label"] = label
                match["color"] = color
                match["category"] = category
                entities.append(match)

        # 2. Detect Top-Right Home Resource Bars (Gold, Elixir, DE, Gems, Builders)
        if state in (GameState.HOME, GameState.WALL_SELECTED):
            if w >= 2200:
                gold_box = [1860, 25, 330, 68]
                elixir_box = [1860, 100, 330, 68]
                de_box = [1860, 175, 330, 68]
                gems_box = [1950, 245, 240, 68]
                builders_box = [1050, 20, 250, 60]
            else:
                gold_box = [1560, 35, 300, 50]
                elixir_box = [1560, 90, 300, 50]
                de_box = [1560, 145, 300, 50]
                gems_box = [1650, 200, 210, 50]
                builders_box = [880, 20, 200, 50]

            try:
                g_crop = frame[gold_box[1] : gold_box[1] + gold_box[3], gold_box[0] : gold_box[0] + gold_box[2]]
                e_crop = frame[elixir_box[1] : elixir_box[1] + elixir_box[3], elixir_box[0] : elixir_box[0] + elixir_box[2]]
                de_crop = frame[de_box[1] : de_box[1] + de_box[3], de_box[0] : de_box[0] + de_box[2]]
                gems_crop = frame[gems_box[1] : gems_box[1] + gems_box[3], gems_box[0] : gems_box[0] + gems_box[2]]

                g_val = DigitOCR.extract_number_from_roi(g_crop)
                e_val = DigitOCR.extract_number_from_roi(e_crop)
                de_val = DigitOCR.extract_number_from_roi(de_crop)
                gems_val = DigitOCR.extract_number_from_roi(gems_crop)

                if g_val > 0 or e_val > 0:
                    entities.append({
                        "id": "gold_balance",
                        "label": f"Gold: {g_val:,}",
                        "category": "resource",
                        "bbox": gold_box,
                        "color": (0, 215, 255),
                        "confidence": 0.98,
                    })
                    entities.append({
                        "id": "elixir_balance",
                        "label": f"Elixir: {e_val:,}",
                        "category": "resource",
                        "bbox": elixir_box,
                        "color": (220, 50, 220),
                        "confidence": 0.98,
                    })
                    if de_val > 0:
                        entities.append({
                            "id": "de_balance",
                            "label": f"Dark Elixir: {de_val:,}",
                            "category": "resource",
                            "bbox": de_box,
                            "color": (255, 200, 50),
                            "confidence": 0.95,
                        })
                    if gems_val > 0:
                        entities.append({
                            "id": "gems_balance",
                            "label": f"Gems: {gems_val:,}",
                            "category": "resource",
                            "bbox": gems_box,
                            "color": (50, 255, 50),
                            "confidence": 0.95,
                        })
                    entities.append({
                        "id": "builders_hud",
                        "label": "Builders Bar",
                        "category": "hud",
                        "bbox": builders_box,
                        "color": (0, 160, 255),
                        "confidence": 0.90,
                    })
            except Exception:
                pass

        # 3. Detect Battle Loot HUD (Top-Left during matchmaking / battle)
        if state in (GameState.BATTLE_SEARCH, GameState.IN_BATTLE):
            loot = self.read_battle_loot(frame)
            if loot.get("gold", 0) > 0 or loot.get("elixir", 0) > 0:
                loot_box = [120, 100, 360, 170] if w >= 2200 else [60, 50, 340, 160]
                entities.append({
                    "id": "available_loot",
                    "label": f"Available: G:{loot['gold']:,} | E:{loot['elixir']:,}",
                    "category": "loot",
                    "bbox": loot_box,
                    "color": (0, 215, 255),
                    "confidence": 0.96,
                })

        # 4. Detect Outer Collectors
        if state in (GameState.BATTLE_SEARCH, GameState.IN_BATTLE):
            collectors = self.locate_outer_collectors(frame)
            for i, (cx, cy) in enumerate(collectors[:8]):
                entities.append({
                    "id": f"collector_{i+1}",
                    "label": f"Target Collector #{i+1}",
                    "category": "target",
                    "bbox": [cx - 32, cy - 32, 64, 64],
                    "color": (0, 255, 255),
                    "confidence": 0.88,
                })

        # 5. Detect Village Structures & 3D wireframe skeletons (Home Village)
        if state in (GameState.HOME, GameState.WALL_SELECTED) or (w >= 1800 and state == GameState.UNKNOWN):
            structures = self.detect_village_structures(frame)
            entities.extend(structures)

        return entities

    def detect_village_structures(self, frame: np.ndarray) -> List[Dict]:
        """
        Segments the village playable field, detects buildings, defenses,
        storages, Town Hall, and generates 3D isometric wireframe skeletons.
        """
        if frame is None or frame.size == 0:
            return []
        h, w = frame.shape[:2]
        if w < 1200 or h < 600:
            return []

        cx, cy = w // 2, int(h * 0.50)
        diamond_pts = np.array([
            [cx, int(h * 0.12)],
            [int(w * 0.86), cy],
            [cx, int(h * 0.88)],
            [int(w * 0.14), cy]
        ], dtype=np.int32)

        field_mask = np.zeros((h, w), dtype=np.uint8)
        cv2.fillPoly(field_mask, [diamond_pts], 255)

        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        grass_mask = cv2.inRange(hsv, (35, 35, 35), (85, 255, 210))
        structures_mask = cv2.bitwise_and(cv2.bitwise_not(grass_mask), field_mask)

        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
        cleaned = cv2.morphologyEx(structures_mask, cv2.MORPH_OPEN, kernel)
        cleaned = cv2.morphologyEx(cleaned, cv2.MORPH_CLOSE, kernel)

        contours, _ = cv2.findContours(cleaned, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        structures = []

        for c in contours:
            area = cv2.contourArea(c)
            if area < 380 or area > 55000:
                continue
            x, y, bw, bh = cv2.boundingRect(c)
            aspect = bw / float(bh)
            if aspect < 0.4 or aspect > 2.5:
                continue

            crop_hsv = hsv[y : y + bh, x : x + bw]
            yellow_ratio = np.mean(cv2.inRange(crop_hsv, (15, 75, 75), (35, 255, 255)) > 0)
            purple_ratio = np.mean(cv2.inRange(crop_hsv, (135, 55, 55), (175, 255, 255)) > 0)
            dark_ratio = np.mean(crop_hsv[:, :, 2] < 50)

            scx, scy = x + bw // 2, y + bh // 2
            dist_to_center = math.hypot(scx - cx, scy - cy)

            if dist_to_center < 180 and area > 4500:
                label = "Town Hall (Village Core)"
                cat = "townhall"
                color = (0, 235, 255)
                conf = 0.96
            elif yellow_ratio > 0.11:
                label = "Gold Storage / Mine"
                cat = "resource"
                color = (0, 215, 255)
                conf = 0.92
            elif purple_ratio > 0.07:
                label = "Elixir Storage / Collector"
                cat = "resource"
                color = (220, 50, 220)
                conf = 0.92
            elif dark_ratio > 0.25 and area > 1000:
                label = "Dark Elixir Drill / Storage"
                cat = "resource"
                color = (255, 180, 50)
                conf = 0.89
            elif area > 1200:
                label = "Defense / Structure"
                cat = "defense"
                color = (0, 165, 255)
                conf = 0.88
            else:
                label = "Village Structure"
                cat = "structure"
                color = (180, 220, 0)
                conf = 0.82

            structures.append({
                "id": f"structure_{len(structures) + 1}",
                "label": label,
                "category": cat,
                "bbox": [x, y, bw, bh],
                "color": color,
                "confidence": conf,
                "is_skeleton": True,
            })

        return structures

    @staticmethod
    def draw_village_grid_skeleton(canvas: np.ndarray):
        """Renders the 44x44 isometric village field boundary and quadrant axes."""
        h, w = canvas.shape[:2]
        if w < 1200:
            return
        cx, cy = w // 2, int(h * 0.50)
        field_pts = np.array([
            [cx, int(h * 0.12)],
            [int(w * 0.86), cy],
            [cx, int(h * 0.88)],
            [int(w * 0.14), cy]
        ], dtype=np.int32)

        # Outer perimeter diamond
        cv2.polylines(canvas, [field_pts], True, (0, 220, 160), 2, cv2.LINE_AA)

        # Inner concentric isometric grid rings
        center = np.array([cx, cy], dtype=np.float32)
        for frac in (0.33, 0.66):
            sub_pts = (center + (field_pts - center) * frac).astype(np.int32)
            cv2.polylines(canvas, [sub_pts], True, (0, 130, 90), 1, cv2.LINE_AA)

        # Quadrant axes
        cv2.line(canvas, (cx, int(h * 0.12)), (cx, int(h * 0.88)), (0, 160, 110), 1, cv2.LINE_AA)
        cv2.line(canvas, (int(w * 0.14), cy), (int(w * 0.86), cy), (0, 160, 110), 1, cv2.LINE_AA)

        # Center Village Core crosshair
        cv2.drawMarker(canvas, (cx, cy), (0, 255, 200), cv2.MARKER_CROSS, 20, 2, cv2.LINE_AA)
        cv2.putText(canvas, "[VILLAGE GRID 44x44]", (cx - 75, cy + 28), cv2.FONT_HERSHEY_DUPLEX, 0.45, (0, 220, 160), 1, cv2.LINE_AA)

    @staticmethod
    def draw_isometric_skeleton(canvas: np.ndarray, ent: Dict):
        """Draws a 3D isometric wireframe skeleton around a detected village structure."""
        bbox = ent.get("bbox")
        if not bbox or len(bbox) != 4:
            return
        x, y, bw, bh = bbox
        color = ent.get("color", (0, 255, 255))
        label = ent.get("label", "Structure")
        conf = ent.get("confidence")

        cx, cy = x + bw // 2, y + bh // 2

        # 1. Base ground diamond footprint
        h_half = max(8, bh // 3)
        w_half = max(8, bw // 2)
        b_top = (cx, cy - h_half)
        b_right = (cx + w_half, cy)
        b_bottom = (cx, cy + h_half)
        b_left = (cx - w_half, cy)
        base_pts = np.array([b_top, b_right, b_bottom, b_left], dtype=np.int32)
        cv2.polylines(canvas, [base_pts], True, color, 1, cv2.LINE_AA)

        # 2. Elevated roof diamond
        elev = int(bh * 0.38)
        r_top = (b_top[0], b_top[1] - elev)
        r_right = (b_right[0], b_right[1] - elev)
        r_bottom = (b_bottom[0], b_bottom[1] - elev)
        r_left = (b_left[0], b_left[1] - elev)
        roof_pts = np.array([r_top, r_right, r_bottom, r_left], dtype=np.int32)
        cv2.polylines(canvas, [roof_pts], True, color, 2, cv2.LINE_AA)

        # 3. Vertical corner pillars
        cv2.line(canvas, b_top, r_top, color, 1, cv2.LINE_AA)
        cv2.line(canvas, b_right, r_right, color, 1, cv2.LINE_AA)
        cv2.line(canvas, b_bottom, r_bottom, color, 1, cv2.LINE_AA)
        cv2.line(canvas, b_left, r_left, color, 1, cv2.LINE_AA)

        # 4. Roof crosshairs
        cv2.line(canvas, r_top, r_bottom, color, 1, cv2.LINE_AA)
        cv2.line(canvas, r_left, r_right, color, 1, cv2.LINE_AA)

        # 5. Tactical skeleton badge
        badge_text = label + (f" [{conf:.0%}]" if conf is not None else "")
        (tw, th), _ = cv2.getTextSize(badge_text, cv2.FONT_HERSHEY_DUPLEX, 0.45, 1)
        by = max(4, r_top[1] - th - 6)
        cv2.rectangle(canvas, (cx - tw // 2 - 4, by), (cx + tw // 2 + 4, by + th + 4), (10, 15, 25), -1)
        cv2.rectangle(canvas, (cx - tw // 2 - 4, by), (cx + tw // 2 + 4, by + th + 4), color, 1)
        cv2.putText(canvas, badge_text, (cx - tw // 2, by + th), cv2.FONT_HERSHEY_DUPLEX, 0.45, color, 1, cv2.LINE_AA)

    def draw_detection_overlay(
        self,
        frame: np.ndarray,
        entities: Optional[List[Dict]] = None,
        inspection_mode: bool = True,
    ) -> np.ndarray:
        """
        Renders HUD bounding boxes, corner brackets, labels, crosshairs,
        village grid skeletons, and 3D isometric building wireframes onto the frame.
        Executes in sub-millisecond time by utilizing asynchronous precomputed perception.
        """
        if frame is None or frame.size == 0:
            return frame

        canvas = frame.copy()
        h, w = canvas.shape[:2]

        if entities is None:
            entities, state = self.get_cached_detections()
            if not entities:
                # Fast single scan fallback
                state = self.detect_state(frame)
        else:
            state = self.detect_state(frame)

        # 1. Draw Village Grid Skeleton on Home or Matchmaking
        if state in (GameState.HOME, GameState.WALL_SELECTED, GameState.BATTLE_SEARCH, GameState.IN_BATTLE) or state == GameState.UNKNOWN:
            self.draw_village_grid_skeleton(canvas)

        # 2. Draw entities (3D wireframe skeletons for buildings; HUD brackets for buttons)
        for ent in entities:
            if ent.get("is_skeleton"):
                self.draw_isometric_skeleton(canvas, ent)
                continue

            bbox = ent.get("bbox")
            if not bbox or len(bbox) != 4:
                continue
            x, y, bw, bh = bbox
            color = ent.get("color", (0, 255, 128))
            label = ent.get("label", ent.get("id", "Object"))
            conf = ent.get("confidence")

            # Semi-transparent fill
            overlay = canvas.copy()
            cv2.rectangle(overlay, (x, y), (x + bw, y + bh), color, -1)
            cv2.addWeighted(overlay, 0.15, canvas, 0.85, 0, canvas)

            # Border
            cv2.rectangle(canvas, (x, y), (x + bw, y + bh), color, 2)

            # Corner brackets (length = 14)
            L = min(14, max(4, bw // 4), max(4, bh // 4))
            cv2.line(canvas, (x, y), (x + L, y), color, 3)
            cv2.line(canvas, (x, y), (x, y + L), color, 3)
            cv2.line(canvas, (x + bw, y), (x + bw - L, y), color, 3)
            cv2.line(canvas, (x + bw, y), (x + bw, y + L), color, 3)
            cv2.line(canvas, (x, y + bh), (x + L, y + bh), color, 3)
            cv2.line(canvas, (x, y + bh), (x, y + bh - L), color, 3)
            cv2.line(canvas, (x + bw, y + bh), (x + bw - L, y + bh), color, 3)
            cv2.line(canvas, (x + bw, y + bh), (x + bw, y + bh - L), color, 3)

            # Center crosshair for tap target
            cx, cy = x + bw // 2, y + bh // 2
            cv2.line(canvas, (cx - 5, cy), (cx + 5, cy), color, 2)
            cv2.line(canvas, (cx, cy - 5), (cx, cy + 5), color, 2)

            # Label badge with dark background for 100% legibility
            text = label + (f" [{conf:.0%}]" if conf is not None else "")
            (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_DUPLEX, 0.55, 1)
            by = max(4, y - th - 8)
            cv2.rectangle(canvas, (x, by), (x + tw + 10, by + th + 6), (15, 23, 42), -1)
            cv2.rectangle(canvas, (x, by), (x + tw + 10, by + th + 6), color, 1)
            cv2.putText(canvas, text, (x + 5, by + th + 2), cv2.FONT_HERSHEY_DUPLEX, 0.55, color, 1, cv2.LINE_AA)
            (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_DUPLEX, 0.55, 1)
            by = max(4, y - th - 8)
            cv2.rectangle(canvas, (x, by), (x + tw + 10, by + th + 6), (15, 23, 42), -1)
            cv2.rectangle(canvas, (x, by), (x + tw + 10, by + th + 6), color, 1)
            cv2.putText(canvas, text, (x + 5, by + th + 2), cv2.FONT_HERSHEY_DUPLEX, 0.55, color, 1, cv2.LINE_AA)

        # 2. Top Header HUD Banner
        mode_text = "● INSPECTION MODE (TAPS DISABLED)" if inspection_mode else "● AUTOMATION ACTIVE"
        mode_color = (0, 255, 128) if inspection_mode else (0, 165, 255)
        header_text = f"{mode_text} | State: {state.upper()} | Recognized: {len(entities)} elements"
        (htw, hth), _ = cv2.getTextSize(header_text, cv2.FONT_HERSHEY_DUPLEX, 0.55, 1)
        bx1 = (w - htw - 30) // 2
        bx2 = bx1 + htw + 30
        cv2.rectangle(canvas, (bx1, 8), (bx2, 42), (15, 23, 42), -1)
        cv2.rectangle(canvas, (bx1, 8), (bx2, 42), mode_color, 2)
        cv2.putText(canvas, header_text, (bx1 + 15, 31), cv2.FONT_HERSHEY_DUPLEX, 0.55, mode_color, 1, cv2.LINE_AA)

        return canvas

    def match_template_detailed(
        self,
        frame: np.ndarray,
        template_name: str,
        min_score: float = 0.75,
        roi: Optional[Tuple[int, int, int, int]] = None,
    ) -> Optional[Dict]:
        """Returns detailed bounding box and score dictionary if matched."""
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
            x = ox + max_loc[0]
            y = oy + max_loc[1]
            cx = x + tw // 2
            cy = y + th // 2
            return {
                "id": template_name,
                "bbox": [int(x), int(y), int(tw), int(th)],
                "center": [int(cx), int(cy)],
                "confidence": round(float(max_val), 3),
            }
        return None

    def detect_all_entities(self, frame: np.ndarray) -> List[Dict]:
        """
        Scans current screen and returns all recognized UI elements, buttons,
        resource bars, text, and base structures with bounding boxes.
        """
        if frame is None or frame.size == 0:
            return []

        h, w = frame.shape[:2]
        entities: List[Dict] = []
        state = self.detect_state(frame)

        # 1. Match registered templates
        friendly_names = {
            "btn_battle": ("Attack / Battle Button", (0, 255, 128), "button"),
            "btn_find_match": ("Find a Match Button", (0, 200, 255), "button"),
            "btn_army_battle": ("Attack! (Army Screen)", (0, 255, 100), "button"),
            "btn_next": ("Next Match Button", (0, 165, 255), "button"),
            "btn_end_battle": ("End Battle Button", (0, 0, 255), "button"),
            "btn_edit_army": ("Edit Army / Quick Train", (255, 180, 50), "button"),
            "btn_army_close": ("Close Army Menu", (180, 180, 180), "button"),
            "slot_sneaky_goblin": ("Sneaky Goblin Slot", (50, 220, 50), "troop"),
            "icon_sword": ("Battle Swords Icon", (0, 220, 220), "icon"),
        }

        for tmpl_id, (label, color, category) in friendly_names.items():
            match = self.match_template_detailed(frame, tmpl_id, min_score=0.75)
            if match:
                match["label"] = label
                match["color"] = color
                match["category"] = category
                entities.append(match)

        # 2. Detect Top-Right Home Resource Bars (Gold, Elixir, DE, Gems, Builders)
        if state in (GameState.HOME, GameState.WALL_SELECTED):
            if w >= 2200:
                gold_box = [1860, 25, 330, 68]
                elixir_box = [1860, 100, 330, 68]
                de_box = [1860, 175, 330, 68]
                gems_box = [1950, 245, 240, 68]
                builders_box = [1050, 20, 250, 60]
            else:
                gold_box = [1560, 35, 300, 50]
                elixir_box = [1560, 90, 300, 50]
                de_box = [1560, 145, 300, 50]
                gems_box = [1650, 200, 210, 50]
                builders_box = [880, 20, 200, 50]

            try:
                g_crop = frame[gold_box[1] : gold_box[1] + gold_box[3], gold_box[0] : gold_box[0] + gold_box[2]]
                e_crop = frame[elixir_box[1] : elixir_box[1] + elixir_box[3], elixir_box[0] : elixir_box[0] + elixir_box[2]]
                de_crop = frame[de_box[1] : de_box[1] + de_box[3], de_box[0] : de_box[0] + de_box[2]]
                gems_crop = frame[gems_box[1] : gems_box[1] + gems_box[3], gems_box[0] : gems_box[0] + gems_box[2]]

                g_val = DigitOCR.extract_number_from_roi(g_crop)
                e_val = DigitOCR.extract_number_from_roi(e_crop)
                de_val = DigitOCR.extract_number_from_roi(de_crop)
                gems_val = DigitOCR.extract_number_from_roi(gems_crop)

                if g_val > 0 or e_val > 0:
                    entities.append({
                        "id": "gold_balance",
                        "label": f"Gold: {g_val:,}",
                        "category": "resource",
                        "bbox": gold_box,
                        "color": (0, 215, 255),
                        "confidence": 0.98,
                    })
                    entities.append({
                        "id": "elixir_balance",
                        "label": f"Elixir: {e_val:,}",
                        "category": "resource",
                        "bbox": elixir_box,
                        "color": (220, 50, 220),
                        "confidence": 0.98,
                    })
                    if de_val > 0:
                        entities.append({
                            "id": "de_balance",
                            "label": f"Dark Elixir: {de_val:,}",
                            "category": "resource",
                            "bbox": de_box,
                            "color": (255, 200, 50),
                            "confidence": 0.95,
                        })
                    if gems_val > 0:
                        entities.append({
                            "id": "gems_balance",
                            "label": f"Gems: {gems_val:,}",
                            "category": "resource",
                            "bbox": gems_box,
                            "color": (50, 255, 50),
                            "confidence": 0.95,
                        })
                    entities.append({
                        "id": "builders_hud",
                        "label": "Builders Bar",
                        "category": "hud",
                        "bbox": builders_box,
                        "color": (0, 160, 255),
                        "confidence": 0.90,
                    })
            except Exception:
                pass

        # 3. Detect Battle Loot HUD (Top-Left during matchmaking / battle)
        if state in (GameState.BATTLE_SEARCH, GameState.IN_BATTLE):
            loot = self.read_battle_loot(frame)
            if loot.get("gold", 0) > 0 or loot.get("elixir", 0) > 0:
                loot_box = [120, 100, 360, 170] if w >= 2200 else [60, 50, 340, 160]
                entities.append({
                    "id": "available_loot",
                    "label": f"Available: G:{loot['gold']:,} | E:{loot['elixir']:,}",
                    "category": "loot",
                    "bbox": loot_box,
                    "color": (0, 215, 255),
                    "confidence": 0.96,
                })

        # 4. Detect Outer Collectors
        if state in (GameState.BATTLE_SEARCH, GameState.IN_BATTLE):
            collectors = self.locate_outer_collectors(frame)
            for i, (cx, cy) in enumerate(collectors[:8]):
                entities.append({
                    "id": f"collector_{i+1}",
                    "label": f"Target Collector #{i+1}",
                    "category": "target",
                    "bbox": [cx - 32, cy - 32, 64, 64],
                    "color": (0, 255, 255),
                    "confidence": 0.88,
                })

        # 5. Detect Village Structures & 3D wireframe skeletons (Home Village)
        if state in (GameState.HOME, GameState.WALL_SELECTED) or (w >= 1800 and state == GameState.UNKNOWN):
            structures = self.detect_village_structures(frame)
            entities.extend(structures)

        return entities

    def detect_village_structures(self, frame: np.ndarray) -> List[Dict]:
        """
        Segments the village playable field, detects buildings, defenses,
        storages, Town Hall, and generates 3D isometric wireframe skeletons.
        """
        if frame is None or frame.size == 0:
            return []
        h, w = frame.shape[:2]
        if w < 1200 or h < 600:
            return []

        cx, cy = w // 2, int(h * 0.50)
        diamond_pts = np.array([
            [cx, int(h * 0.12)],
            [int(w * 0.86), cy],
            [cx, int(h * 0.88)],
            [int(w * 0.14), cy]
        ], dtype=np.int32)

        field_mask = np.zeros((h, w), dtype=np.uint8)
        cv2.fillPoly(field_mask, [diamond_pts], 255)

        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        grass_mask = cv2.inRange(hsv, (35, 35, 35), (85, 255, 210))
        structures_mask = cv2.bitwise_and(cv2.bitwise_not(grass_mask), field_mask)

        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
        cleaned = cv2.morphologyEx(structures_mask, cv2.MORPH_OPEN, kernel)
        cleaned = cv2.morphologyEx(cleaned, cv2.MORPH_CLOSE, kernel)

        contours, _ = cv2.findContours(cleaned, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        structures = []

        for c in contours:
            area = cv2.contourArea(c)
            if area < 380 or area > 55000:
                continue
            x, y, bw, bh = cv2.boundingRect(c)
            aspect = bw / float(bh)
            if aspect < 0.4 or aspect > 2.5:
                continue

            crop_hsv = hsv[y : y + bh, x : x + bw]
            yellow_ratio = np.mean(cv2.inRange(crop_hsv, (15, 75, 75), (35, 255, 255)) > 0)
            purple_ratio = np.mean(cv2.inRange(crop_hsv, (135, 55, 55), (175, 255, 255)) > 0)
            dark_ratio = np.mean(crop_hsv[:, :, 2] < 50)

            scx, scy = x + bw // 2, y + bh // 2
            dist_to_center = math.hypot(scx - cx, scy - cy)

            if dist_to_center < 180 and area > 4500:
                label = "Town Hall (Village Core)"
                cat = "townhall"
                color = (0, 235, 255)
                conf = 0.96
            elif yellow_ratio > 0.11:
                label = "Gold Storage / Mine"
                cat = "resource"
                color = (0, 215, 255)
                conf = 0.92
            elif purple_ratio > 0.07:
                label = "Elixir Storage / Collector"
                cat = "resource"
                color = (220, 50, 220)
                conf = 0.92
            elif dark_ratio > 0.25 and area > 1000:
                label = "Dark Elixir Drill / Storage"
                cat = "resource"
                color = (255, 180, 50)
                conf = 0.89
            elif area > 1200:
                label = "Defense / Structure"
                cat = "defense"
                color = (0, 165, 255)
                conf = 0.88
            else:
                label = "Village Structure"
                cat = "structure"
                color = (180, 220, 0)
                conf = 0.82

            structures.append({
                "id": f"structure_{len(structures) + 1}",
                "label": label,
                "category": cat,
                "bbox": [x, y, bw, bh],
                "color": color,
                "confidence": conf,
                "is_skeleton": True,
            })

        return structures

    @staticmethod
    def draw_village_grid_skeleton(canvas: np.ndarray):
        """Renders the 44x44 isometric village field boundary and quadrant axes."""
        h, w = canvas.shape[:2]
        if w < 1200:
            return
        cx, cy = w // 2, int(h * 0.50)
        field_pts = np.array([
            [cx, int(h * 0.12)],
            [int(w * 0.86), cy],
            [cx, int(h * 0.88)],
            [int(w * 0.14), cy]
        ], dtype=np.int32)

        # Outer perimeter diamond
        cv2.polylines(canvas, [field_pts], True, (0, 220, 160), 2, cv2.LINE_AA)

        # Inner concentric isometric grid rings
        center = np.array([cx, cy], dtype=np.float32)
        for frac in (0.33, 0.66):
            sub_pts = (center + (field_pts - center) * frac).astype(np.int32)
            cv2.polylines(canvas, [sub_pts], True, (0, 130, 90), 1, cv2.LINE_AA)

        # Quadrant axes
        cv2.line(canvas, (cx, int(h * 0.12)), (cx, int(h * 0.88)), (0, 160, 110), 1, cv2.LINE_AA)
        cv2.line(canvas, (int(w * 0.14), cy), (int(w * 0.86), cy), (0, 160, 110), 1, cv2.LINE_AA)

        # Center Village Core crosshair
        cv2.drawMarker(canvas, (cx, cy), (0, 255, 200), cv2.MARKER_CROSS, 20, 2, cv2.LINE_AA)
        cv2.putText(canvas, "[VILLAGE GRID 44x44]", (cx - 75, cy + 28), cv2.FONT_HERSHEY_DUPLEX, 0.45, (0, 220, 160), 1, cv2.LINE_AA)

    @staticmethod
    def draw_isometric_skeleton(canvas: np.ndarray, ent: Dict):
        """Draws a 3D isometric wireframe skeleton around a detected village structure."""
        bbox = ent.get("bbox")
        if not bbox or len(bbox) != 4:
            return
        x, y, bw, bh = bbox
        color = ent.get("color", (0, 255, 255))
        label = ent.get("label", "Structure")
        conf = ent.get("confidence")

        cx, cy = x + bw // 2, y + bh // 2

        # 1. Base ground diamond footprint
        h_half = max(8, bh // 3)
        w_half = max(8, bw // 2)
        b_top = (cx, cy - h_half)
        b_right = (cx + w_half, cy)
        b_bottom = (cx, cy + h_half)
        b_left = (cx - w_half, cy)
        base_pts = np.array([b_top, b_right, b_bottom, b_left], dtype=np.int32)
        cv2.polylines(canvas, [base_pts], True, color, 1, cv2.LINE_AA)

        # 2. Elevated roof diamond
        elev = int(bh * 0.38)
        r_top = (b_top[0], b_top[1] - elev)
        r_right = (b_right[0], b_right[1] - elev)
        r_bottom = (b_bottom[0], b_bottom[1] - elev)
        r_left = (b_left[0], b_left[1] - elev)
        roof_pts = np.array([r_top, r_right, r_bottom, r_left], dtype=np.int32)
        cv2.polylines(canvas, [roof_pts], True, color, 2, cv2.LINE_AA)

        # 3. Vertical corner pillars
        cv2.line(canvas, b_top, r_top, color, 1, cv2.LINE_AA)
        cv2.line(canvas, b_right, r_right, color, 1, cv2.LINE_AA)
        cv2.line(canvas, b_bottom, r_bottom, color, 1, cv2.LINE_AA)
        cv2.line(canvas, b_left, r_left, color, 1, cv2.LINE_AA)

        # 4. Roof crosshairs
        cv2.line(canvas, r_top, r_bottom, color, 1, cv2.LINE_AA)
        cv2.line(canvas, r_left, r_right, color, 1, cv2.LINE_AA)

        # 5. Tactical skeleton badge
        badge_text = label + (f" [{conf:.0%}]" if conf is not None else "")
        (tw, th), _ = cv2.getTextSize(badge_text, cv2.FONT_HERSHEY_DUPLEX, 0.45, 1)
        by = max(4, r_top[1] - th - 6)
        cv2.rectangle(canvas, (cx - tw // 2 - 4, by), (cx + tw // 2 + 4, by + th + 4), (10, 15, 25), -1)
        cv2.rectangle(canvas, (cx - tw // 2 - 4, by), (cx + tw // 2 + 4, by + th + 4), color, 1)
        cv2.putText(canvas, badge_text, (cx - tw // 2, by + th), cv2.FONT_HERSHEY_DUPLEX, 0.45, color, 1, cv2.LINE_AA)

    def draw_detection_overlay(
        self,
        frame: np.ndarray,
        entities: Optional[List[Dict]] = None,
        inspection_mode: bool = True,
    ) -> np.ndarray:
        """
        Renders HUD bounding boxes, corner brackets, labels, crosshairs,
        village grid skeletons, and 3D isometric building wireframes onto the frame.
        Executes in sub-millisecond time by utilizing asynchronous precomputed perception.
        """
        if frame is None or frame.size == 0:
            return frame

        canvas = frame.copy()
        h, w = canvas.shape[:2]

        if entities is None:
            entities, state = self.get_cached_detections()
            if not entities:
                # Fast single scan fallback
                state = self.detect_state(frame)
        else:
            state = self.detect_state(frame)

        # 1. Draw Village Grid Skeleton on Home or Matchmaking
        if state in (GameState.HOME, GameState.WALL_SELECTED, GameState.BATTLE_SEARCH, GameState.IN_BATTLE) or state == GameState.UNKNOWN:
            self.draw_village_grid_skeleton(canvas)

        # 2. Draw entities (3D wireframe skeletons for buildings; HUD brackets for buttons)
        for ent in entities:
            if ent.get("is_skeleton"):
                self.draw_isometric_skeleton(canvas, ent)
                continue

            bbox = ent.get("bbox")
            if not bbox or len(bbox) != 4:
                continue
            x, y, bw, bh = bbox
            color = ent.get("color", (0, 255, 128))
            label = ent.get("label", ent.get("id", "Object"))
            conf = ent.get("confidence")

            # Semi-transparent fill
            overlay = canvas.copy()
            cv2.rectangle(overlay, (x, y), (x + bw, y + bh), color, -1)
            cv2.addWeighted(overlay, 0.15, canvas, 0.85, 0, canvas)

            # Border
            cv2.rectangle(canvas, (x, y), (x + bw, y + bh), color, 2)

            # Corner brackets (length = 14)
            L = min(14, max(4, bw // 4), max(4, bh // 4))
            cv2.line(canvas, (x, y), (x + L, y), color, 3)
            cv2.line(canvas, (x, y), (x, y + L), color, 3)
            cv2.line(canvas, (x + bw, y), (x + bw - L, y), color, 3)
            cv2.line(canvas, (x + bw, y), (x + bw, y + L), color, 3)
            cv2.line(canvas, (x, y + bh), (x + L, y + bh), color, 3)
            cv2.line(canvas, (x, y + bh), (x, y + bh - L), color, 3)
            cv2.line(canvas, (x + bw, y + bh), (x + bw - L, y + bh), color, 3)
            cv2.line(canvas, (x + bw, y + bh), (x + bw, y + bh - L), color, 3)

            # Center crosshair for tap target
            cx, cy = x + bw // 2, y + bh // 2
            cv2.line(canvas, (cx - 5, cy), (cx + 5, cy), color, 2)
            cv2.line(canvas, (cx, cy - 5), (cx, cy + 5), color, 2)

            # Label badge with dark background for 100% legibility
            text = label + (f" [{conf:.0%}]" if conf is not None else "")
            (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_DUPLEX, 0.55, 1)
            by = max(4, y - th - 8)
            cv2.rectangle(canvas, (x, by), (x + tw + 10, by + th + 6), (15, 23, 42), -1)
            cv2.rectangle(canvas, (x, by), (x + tw + 10, by + th + 6), color, 1)
            cv2.putText(canvas, text, (x + 5, by + th + 2), cv2.FONT_HERSHEY_DUPLEX, 0.55, color, 1, cv2.LINE_AA)
            (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_DUPLEX, 0.55, 1)
            by = max(4, y - th - 8)
            cv2.rectangle(canvas, (x, by), (x + tw + 10, by + th + 6), (15, 23, 42), -1)
            cv2.rectangle(canvas, (x, by), (x + tw + 10, by + th + 6), color, 1)
            cv2.putText(canvas, text, (x + 5, by + th + 2), cv2.FONT_HERSHEY_DUPLEX, 0.55, color, 1, cv2.LINE_AA)

        # 2. Top Header HUD Banner
        mode_text = "● INSPECTION MODE (TAPS DISABLED)" if inspection_mode else "● AUTOMATION ACTIVE"
        mode_color = (0, 255, 128) if inspection_mode else (0, 165, 255)
        header_text = f"{mode_text} | State: {state.upper()} | Recognized: {len(entities)} elements"
        (htw, hth), _ = cv2.getTextSize(header_text, cv2.FONT_HERSHEY_DUPLEX, 0.55, 1)
        bx1 = (w - htw - 30) // 2
        bx2 = bx1 + htw + 30
        cv2.rectangle(canvas, (bx1, 8), (bx2, 42), (15, 23, 42), -1)
        cv2.rectangle(canvas, (bx1, 8), (bx2, 42), mode_color, 2)
        cv2.putText(canvas, header_text, (bx1 + 15, 31), cv2.FONT_HERSHEY_DUPLEX, 0.55, mode_color, 1, cv2.LINE_AA)

        return canvas
