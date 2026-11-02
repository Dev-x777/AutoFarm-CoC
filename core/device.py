"""
Device controller for Clash of Clans automation.
Supports:
1. Real Android devices and Emulators (LDPlayer, MuMu, BlueStacks, Nox) via ADB.
2. Auto-discovery and automatic platform-tools download if ADB is missing.
3. High-fidelity Mock Device for testing without an active emulator.
4. Humanized Bézier curve touch inputs and Gaussian coordinate jitter.
"""

import io
import math
import os
import platform
import random
import shutil
import struct
import subprocess
import threading
import time
import urllib.request
import zipfile
from pathlib import Path
from typing import List, Optional, Tuple, Union

import cv2
import numpy as np
from PIL import Image

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BIN_DIR = PROJECT_ROOT / "bin"


def get_platform_tools_url() -> str:
    system = platform.system().lower()
    if system == "darwin":
        return "https://dl.google.com/android/repository/platform-tools-latest-darwin.zip"
    elif system == "windows":
        return "https://dl.google.com/android/repository/platform-tools-latest-windows.zip"
    else:
        return "https://dl.google.com/android/repository/platform-tools-latest-linux.zip"


def find_or_download_adb(custom_path: str = "auto") -> Optional[str]:
    """Finds ADB in PATH or local directory, or downloads official Google platform-tools."""
    if custom_path and custom_path != "auto":
        # Resolve relative paths against project root
        candidate = Path(custom_path)
        if not candidate.is_absolute():
            candidate = PROJECT_ROOT / candidate
        if candidate.is_file():
            return str(candidate)

    # Check system PATH
    system_adb = shutil.which("adb")
    if system_adb:
        return system_adb

    # Check local bin/platform-tools/adb
    local_adb = BIN_DIR / "platform-tools" / ("adb.exe" if platform.system() == "Windows" else "adb")
    if local_adb.is_file():
        return str(local_adb)

    # Check common Android SDK locations
    home = Path.home()
    candidates = [
        home / "Library/Android/sdk/platform-tools/adb",
        home / "Android/Sdk/platform-tools/adb",
        Path("/opt/homebrew/bin/adb"),
        Path("/usr/local/bin/adb"),
    ]
    for c in candidates:
        if c.is_file():
            return str(c)

    # Auto-download Google platform-tools if not found
    try:
        BIN_DIR.mkdir(parents=True, exist_ok=True)
        url = get_platform_tools_url()
        zip_path = BIN_DIR / "platform-tools.zip"
        print(f"[Device] Downloading official Android platform-tools from {url}...")
        urllib.request.urlretrieve(url, zip_path)
        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            zip_ref.extractall(BIN_DIR)
        if zip_path.exists():
            zip_path.unlink()
        if local_adb.is_file():
            os.chmod(str(local_adb), 0o755)
            print(f"[Device] ADB installed successfully at {local_adb}")
            return str(local_adb)
    except Exception as e:
        print(f"[Device] Failed to auto-download ADB: {e}")

    return None


def find_scrcpy() -> Optional[str]:
    """Finds scrcpy binary in bin directory or system PATH."""
    local_scrcpy = BIN_DIR / "scrcpy" / ("scrcpy.exe" if platform.system() == "Windows" else "scrcpy")
    if local_scrcpy.is_file():
        return str(local_scrcpy)
    system_scrcpy = shutil.which("scrcpy")
    if system_scrcpy:
        return system_scrcpy
    return None


def find_ffmpeg() -> Optional[str]:
    """Finds ffmpeg binary in bin directory or system PATH."""
    local_ffmpeg = BIN_DIR / ("ffmpeg.exe" if platform.system() == "Windows" else "ffmpeg")
    if local_ffmpeg.is_file():
        return str(local_ffmpeg)
    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg:
        return system_ffmpeg
    return None


class Humanizer:
    """Generates human-like touch inputs using Bézier curves and Gaussian distributions."""

    @staticmethod
    def jitter_point(x: int, y: int, max_radius: int = 8) -> Tuple[int, int]:
        """Adds natural hand tremor / finger placement variance using 2D Gaussian distribution."""
        radius = abs(random.gauss(0, max_radius / 2.0))
        angle = random.uniform(0, 2 * math.pi)
        jx = int(round(x + radius * math.cos(angle)))
        jy = int(round(y + radius * math.sin(angle)))
        return max(0, jx), max(0, jy)

    @staticmethod
    def bezier_curve(
        start: Tuple[int, int], end: Tuple[int, int], num_points: int = 15
    ) -> List[Tuple[int, int]]:
        """Generates a natural curved swipe path using a quadratic/cubic Bézier curve."""
        x0, y0 = start
        x3, y3 = end

        # Introduce a randomized midpoint offset for natural arch
        dx = x3 - x0
        dy = y3 - y0
        dist = math.hypot(dx, dy)
        curvature = dist * random.uniform(0.05, 0.18)

        # Perpendicular normal vector
        nx = -dy / (dist + 1e-6)
        ny = dx / (dist + 1e-6)
        sign = random.choice([-1, 1])

        cx = (x0 + x3) / 2.0 + nx * curvature * sign
        cy = (y0 + y3) / 2.0 + ny * curvature * sign

        points = []
        for i in range(num_points):
            t = i / float(num_points - 1)
            # Quadratic bezier formula: (1-t)^2 * P0 + 2(1-t)t * P1 + t^2 * P2
            bx = (1 - t) ** 2 * x0 + 2 * (1 - t) * t * cx + (t**2) * x3
            by = (1 - t) ** 2 * y0 + 2 * (1 - t) * t * cy + (t**2) * y3
            # Add slight micro-tremor
            mx, my = Humanizer.jitter_point(int(bx), int(by), max_radius=2)
            points.append((mx, my))
        return points

    @staticmethod
    def random_sleep(min_sec: float = 0.35, max_sec: float = 0.95):
        """Simulates human reaction time."""
        delay = random.uniform(min_sec, max_sec)
        time.sleep(delay)

    @staticmethod
    def reaction_delay(min_sec: float = 0.30, max_sec: float = 0.75):
        """Simulates human reaction time using log-normal distribution with micro-pauses."""
        base = random.lognormvariate(-0.8, 0.3)
        delay = max(min_sec, min(max_sec, base))
        # 8% chance of natural human micro-distraction pause
        if random.random() < 0.08:
            delay += random.uniform(1.0, 2.2)
        time.sleep(delay)


class MockDevice:
    """
    High-fidelity simulation device for testing, unit tests, and development.
    Generates realistic Clash of Clans UI frames (Home Base, Battle Search, In-Battle, Wall Selection).
    """

    def __init__(self, width: int = 1920, height: int = 1080):
        self.width = width
        self.height = height
        self.current_state = "home"
        self.gold = 3_250_000
        self.elixir = 3_180_000
        self.dark_elixir = 42_500
        self.trophies = 2350
        self.battle_gold = 680_000
        self.battle_elixir = 720_000
        self.battle_de = 5400
        self.loot_remaining_pct = 1.0
        self.walls_upgraded_count = 0
        self.attack_wave = 0
        self._generate_canvas()

    def _generate_canvas(self):
        # Create base grass canvas
        canvas = np.zeros((self.height, self.width, 3), dtype=np.uint8)
        canvas[:] = (35, 120, 45)  # CoC grass green in BGR
        self.canvas = canvas

    def capture_frame(self) -> np.ndarray:
        """Renders the simulated Clash of Clans frame with realistic HUD, text, and buildings."""
        frame = self.canvas.copy()

        # Render Top-Right Resource Bars (Home state)
        if self.current_state in ("home", "wall_inspect"):
            # Gold bar
            cv2.rectangle(frame, (1550, 40), (1880, 80), (30, 30, 30), -1)
            cv2.rectangle(frame, (1550, 40), (1550 + int(330 * (self.gold / 8000000)), 80), (0, 180, 240), -1)
            cv2.putText(frame, f"{self.gold:,}", (1580, 70), cv2.FONT_HERSHEY_DUPLEX, 0.8, (255, 255, 255), 2)
            cv2.putText(frame, "GOLD", (1820, 70), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 215, 255), 1)

            # Elixir bar
            cv2.rectangle(frame, (1550, 95), (1880, 135), (30, 30, 30), -1)
            cv2.rectangle(frame, (1550, 95), (1550 + int(330 * (self.elixir / 8000000)), 135), (200, 30, 180), -1)
            cv2.putText(frame, f"{self.elixir:,}", (1580, 125), cv2.FONT_HERSHEY_DUPLEX, 0.8, (255, 255, 255), 2)

            # Attack button (Bottom-Left)
            cv2.circle(frame, (120, 960), 65, (0, 140, 255), -1)
            cv2.putText(frame, "ATTACK", (75, 965), cv2.FONT_HERSHEY_DUPLEX, 0.8, (255, 255, 255), 2)

            # Army Train button
            cv2.rectangle(frame, (50, 780), (140, 870), (50, 50, 50), -1)
            cv2.putText(frame, "ARMY", (65, 835), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)

            # Village buildings & Walls
            for wx in range(750, 1170, 40):
                cv2.rectangle(frame, (wx, 520), (wx + 30, 550), (120, 120, 120), -1)
                cv2.rectangle(frame, (wx, 520), (wx + 30, 550), (220, 220, 220), 1)

            if self.current_state == "wall_inspect":
                # Show Upgrade Wall Popover
                cv2.rectangle(frame, (900, 850), (1050, 940), (20, 160, 20), -1)
                cv2.putText(frame, "UPGRADE", (915, 890), cv2.FONT_HERSHEY_DUPLEX, 0.7, (255, 255, 255), 2)
                cv2.putText(frame, "200,000", (925, 925), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)

        elif self.current_state == "battle_search":
            # Red Attack Boundary Lines
            cv2.rectangle(frame, (250, 150), (1670, 920), (30, 30, 200), 3)

            # Top-Left Available Loot Info Box (dark background)
            cv2.rectangle(frame, (50, 50), (450, 260), (20, 20, 20), -1)
            current_g = int(self.battle_gold * self.loot_remaining_pct)
            current_e = int(self.battle_elixir * self.loot_remaining_pct)
            current_de = int(self.battle_de * self.loot_remaining_pct)

            cv2.putText(frame, f"Gold: {current_g:,}", (70, 95), cv2.FONT_HERSHEY_DUPLEX, 0.9, (0, 215, 255), 2)
            cv2.putText(frame, f"Elixir: {current_e:,}", (70, 145), cv2.FONT_HERSHEY_DUPLEX, 0.9, (220, 50, 220), 2)
            cv2.putText(frame, f"Dark: {current_de:,}", (70, 195), cv2.FONT_HERSHEY_DUPLEX, 0.9, (180, 180, 180), 2)
            cv2.putText(frame, f"Trophies: {self.trophies}", (70, 240), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 1)

            # Next Button (Bottom-Right) - Supercell orange BGR = (0, 130, 220)
            cv2.rectangle(frame, (1660, 875), (1890, 995), (0, 130, 220), -1)
            cv2.putText(frame, "NEXT", (1710, 945), cv2.FONT_HERSHEY_DUPLEX, 1.0, (255, 255, 255), 2)

            # Outer Gold Mines & Collectors along the red line
            collectors = [(350, 280), (1550, 300), (400, 800), (1500, 780)]
            for cx, cy in collectors:
                cv2.circle(frame, (cx, cy), 32, (0, 200, 255), -1)
                cv2.circle(frame, (cx, cy), 34, (20, 20, 20), 2)

            # Bottom Troop Bar
            cv2.rectangle(frame, (350, 940), (1550, 1070), (40, 40, 40), -1)
            cv2.rectangle(frame, (370, 955), (460, 1055), (60, 180, 60), -1)
            cv2.putText(frame, "Goblins", (380, 1000), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
            cv2.putText(frame, "x85", (395, 1040), cv2.FONT_HERSHEY_DUPLEX, 0.6, (255, 255, 255), 2)

        elif self.current_state == "in_battle":
            # Red Attack Boundary Lines
            cv2.rectangle(frame, (250, 150), (1670, 920), (30, 30, 200), 3)

            # Top-Left Available Loot Info Box
            cv2.rectangle(frame, (50, 50), (450, 260), (20, 20, 20), -1)
            current_g = int(self.battle_gold * self.loot_remaining_pct)
            current_e = int(self.battle_elixir * self.loot_remaining_pct)
            current_de = int(self.battle_de * self.loot_remaining_pct)

            cv2.putText(frame, f"Gold: {current_g:,}", (70, 95), cv2.FONT_HERSHEY_DUPLEX, 0.9, (0, 215, 255), 2)
            cv2.putText(frame, f"Elixir: {current_e:,}", (70, 145), cv2.FONT_HERSHEY_DUPLEX, 0.9, (220, 50, 220), 2)
            cv2.putText(frame, f"Dark: {current_de:,}", (70, 195), cv2.FONT_HERSHEY_DUPLEX, 0.9, (180, 180, 180), 2)

            # End Battle Button: pure BGR red (0, 0, 200)
            cv2.rectangle(frame, (40, 875), (260, 995), (0, 0, 200), -1)
            cv2.putText(frame, "END", (65, 930), cv2.FONT_HERSHEY_DUPLEX, 0.8, (255, 255, 255), 2)
            cv2.putText(frame, "BATTLE", (55, 975), cv2.FONT_HERSHEY_DUPLEX, 0.7, (255, 255, 255), 2)

            # Collectors visible mid-battle
            collectors = [(350, 280), (1550, 300), (400, 800), (1500, 780)]
            for cx, cy in collectors:
                cv2.circle(frame, (cx, cy), 32, (0, 200, 255), -1)

            # Bottom Troop Bar (fewer troops now)
            cv2.rectangle(frame, (350, 940), (1550, 1070), (40, 40, 40), -1)
            cv2.rectangle(frame, (370, 955), (460, 1055), (60, 180, 60), -1)
            cv2.putText(frame, "Goblins", (380, 1000), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

        return frame

    def tap(self, x: int, y: int):
        jx, jy = x, y
        # Simulate button clicks based on coordinates
        if self.current_state == "home":
            # Attack button (bottom-left)
            if math.hypot(jx - 120, jy - 960) < 80:
                self.current_state = "battle_search"
                self.loot_remaining_pct = 1.0
                self.battle_gold = random.choice([150000, 680000, 850000, 320000])
                self.battle_elixir = random.choice([120000, 720000, 890000, 290000])
                self.battle_de = random.choice([800, 5400, 6800, 1200])
            # Wall click
            elif 750 <= jx <= 1170 and 500 <= jy <= 570:
                self.current_state = "wall_inspect"

        elif self.current_state == "wall_inspect":
            if 900 <= jx <= 1050 and 850 <= jy <= 940:
                # Upgrade clicked
                if self.gold >= 200000:
                    self.gold -= 200000
                    self.walls_upgraded_count += 1
                self.current_state = "home"
            else:
                self.current_state = "home"

        elif self.current_state == "battle_search":
            # Next button
            if 1680 <= jx <= 1870 and 890 <= jy <= 980:
                self.battle_gold = random.choice([210000, 750000, 920000, 180000])
                self.battle_elixir = random.choice([190000, 690000, 910000, 140000])
                self.battle_de = random.choice([1100, 5800, 7200, 900])
                self.loot_remaining_pct = 1.0
            # Troop drop (starts battle)
            elif jy < 850:
                self.current_state = "in_battle"
                self.loot_remaining_pct = max(0.05, self.loot_remaining_pct - 0.25)
            # End battle button
            elif 50 <= jx <= 240 and 890 <= jy <= 980:
                self.current_state = "home"

        elif self.current_state == "in_battle":
            # Dropping more troops
            if jy < 850:
                self.loot_remaining_pct = max(0.05, self.loot_remaining_pct - 0.28)
            # End battle
            elif 50 <= jx <= 240 and 890 <= jy <= 980:
                # Add looted resources
                looted_g = int(self.battle_gold * (1.0 - self.loot_remaining_pct))
                looted_e = int(self.battle_elixir * (1.0 - self.loot_remaining_pct))
                self.gold += looted_g
                self.elixir += looted_e
                self.current_state = "home"

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300):
        # Swiping on village view moves camera
        pass


class DeviceController:
    """
    Main hardware/emulator interface. Handles ADB communication,
    screencap piping, and Bézier touch execution.
    """

    def __init__(
        self,
        mode: str = "auto",
        serial: str = "",
        adb_path: str = "auto",
        target_resolution: Tuple[int, int] = (1920, 1080),
    ):
        self.mode = mode
        self.serial = serial
        self.target_width, self.target_height = target_resolution
        self.adb_bin = None
        self.mock = None
        self.scrcpy_bin = find_scrcpy()
        self.ffmpeg_bin = find_ffmpeg()
        self.device_width = 1920
        self.device_height = 1080
        self.touch_enabled: bool = False  # SAFETY DEFAULT: Touch inputs disabled for inspection mode
        self._current_frame: Optional[np.ndarray] = None
        self._latest_jpeg_bytes: Optional[bytes] = None
        self._frame_lock = threading.Lock()
        self._stream_running = False
        self._stream_thread: Optional[threading.Thread] = None
        self._scrcpy_proc: Optional[subprocess.Popen] = None
        self._ffmpeg_proc: Optional[subprocess.Popen] = None
        self._fifo_path: Optional[str] = None

        self.initialize()
        self.start_streamer()

    def start_streamer(self):
        """Starts real-time background video capture thread for 0ms latency frames."""
        if self._stream_running:
            return
        self._stream_running = True
        self._stream_thread = threading.Thread(target=self._stream_worker, daemon=True, name="RealTimeFrameStreamer")
        self._stream_thread.start()

    def stop_streamer(self):
        """Gracefully terminates background video streaming thread and subprocesses."""
        self._stream_running = False
        self._cleanup_scrcpy()
        if self._stream_thread and self._stream_thread.is_alive():
            self._stream_thread.join(timeout=2.0)

    def _cleanup_scrcpy(self):
        """Kills active scrcpy and ffmpeg subprocesses and removes named pipe FIFO."""
        if self._ffmpeg_proc:
            try:
                self._ffmpeg_proc.terminate()
                self._ffmpeg_proc.wait(timeout=0.8)
            except Exception:
                try:
                    self._ffmpeg_proc.kill()
                except Exception:
                    pass
            self._ffmpeg_proc = None

        if self._scrcpy_proc:
            try:
                self._scrcpy_proc.terminate()
                self._scrcpy_proc.wait(timeout=0.8)
            except Exception:
                try:
                    self._scrcpy_proc.kill()
                except Exception:
                    pass
            self._scrcpy_proc = None

        if self._fifo_path and os.path.exists(self._fifo_path):
            try:
                os.remove(self._fifo_path)
            except Exception:
                pass
            self._fifo_path = None

    def _stream_worker(self):
        """Continuous high-speed loop keeping in-memory frame buffer and JPEG stream updated in real time."""
        while self._stream_running:
            try:
                if self.mode == "adb" and self.scrcpy_bin and self.ffmpeg_bin and self.serial:
                    self._run_scrcpy_stream()
                else:
                    self._run_screencap_stream_step()
            except Exception:
                time.sleep(0.5)

    def _run_scrcpy_stream(self):
        """Streams hardware H.264 video at 30+ FPS via scrcpy and ffmpeg into MJPEG."""
        pid = os.getpid()
        safe_serial = self.serial.replace(":", "_").replace(".", "_")
        self._fifo_path = f"/tmp/scrcpy_{safe_serial}_{pid}.mkv"
        if os.path.exists(self._fifo_path):
            try:
                os.remove(self._fifo_path)
            except Exception:
                pass
        try:
            os.mkfifo(self._fifo_path)
        except Exception as e:
            print(f"[Device] Could not create FIFO {self._fifo_path}: {e}")
            self._run_screencap_stream_step()
            return

        env = os.environ.copy()
        if self.adb_bin:
            adb_dir = str(Path(self.adb_bin).parent)
            env["PATH"] = f"{adb_dir}:{env.get('PATH', '')}"
            env["ADB"] = str(self.adb_bin)

        cmd_scrcpy = [
            self.scrcpy_bin,
            "-s", self.serial,
            "--no-window",
            "--no-audio",
            "--max-size", "1440",
            "--video-bit-rate", "2M",
            "--max-fps", "30",
            f"--record={self._fifo_path}"
        ]

        cmd_ffmpeg = [
            self.ffmpeg_bin,
            "-loglevel", "error",
            "-fflags", "nobuffer",
            "-flags", "low_delay",
            "-probesize", "32",
            "-analyzeduration", "0",
            "-f", "matroska",
            "-i", self._fifo_path,
            "-f", "image2pipe",
            "-vcodec", "mjpeg",
            "-q:v", "5",
            "pipe:1"
        ]

        try:
            self._scrcpy_proc = subprocess.Popen(
                cmd_scrcpy, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            self._ffmpeg_proc = subprocess.Popen(
                cmd_ffmpeg, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=65536
            )

            buf = bytearray()
            while self._stream_running:
                chunk = self._ffmpeg_proc.stdout.read(16384)
                if not chunk:
                    break
                buf.extend(chunk)

                # Skip to latest complete JPEG in buffer to guarantee ZERO queue latency
                latest_jpg = None
                while True:
                    s = buf.find(b"\xff\xd8")
                    if s == -1:
                        buf.clear()
                        break
                    e = buf.find(b"\xff\xd9", s + 2)
                    if e == -1:
                        if s > 0:
                            del buf[:s]
                        break
                    latest_jpg = bytes(buf[s : e + 2])
                    del buf[: e + 2]

                if latest_jpg is not None:
                    # Decode JPEG into OpenCV numpy array
                    arr = np.frombuffer(latest_jpg, dtype=np.uint8)
                    frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                    if frame is not None:
                        h, w = frame.shape[:2]
                        if h > w:
                            frame = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
                            h, w = frame.shape[:2]
                            ok, buf_rot = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
                            if ok:
                                latest_jpg = buf_rot.tobytes()
                        with self._frame_lock:
                            self._current_frame = frame
                            self._latest_jpeg_bytes = latest_jpg
                            self.device_width = w
                            self.device_height = h
                            self.target_width = w
                            self.target_height = h
        finally:
            self._cleanup_scrcpy()

    def _run_screencap_stream_step(self):
        frame = self._fetch_frame_now()
        if frame is not None:
            h, w = frame.shape[:2]
            if h > w:
                frame = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
                h, w = frame.shape[:2]
            ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 72])
            with self._frame_lock:
                self._current_frame = frame
                if ok:
                    self._latest_jpeg_bytes = buf.tobytes()
                self.device_width = w
                self.device_height = h
                self.target_width = w
                self.target_height = h
            time.sleep(0.04)
        else:
            time.sleep(0.25)

    def initialize(self):
        """Discovers or starts the device connection."""
        if self.mode == "mock":
            self.mock = MockDevice(self.target_width, self.target_height)
            print("[Device] Running in high-fidelity MOCK simulation mode.")
            return

        self.adb_bin = find_or_download_adb()
        if not self.adb_bin:
            print("[Device] ADB unavailable. Falling back to MOCK mode.")
            self.mode = "mock"
            self.mock = MockDevice(self.target_width, self.target_height)
            return

        devices = self.get_connected_devices()
        if not devices:
            # Try connecting to standard emulator ports
            ports = [5555, 16384, 62001, 5554]
            for p in ports:
                self._run_adb(["connect", f"127.0.0.1:{p}"])
            devices = self.get_connected_devices()

        if devices:
            if not self.serial:
                self.serial = devices[0]
            print(f"[Device] Connected to ADB device: {self.serial}")
            self.detect_screen_size()
            self.target_width = self.device_width
            self.target_height = self.device_height
            self.mode = "adb"
        else:
            if self.mode == "auto":
                print("[Device] No physical/emulator ADB device detected. Defaulting to MOCK mode for instant preview.")
                self.mode = "mock"
                self.mock = MockDevice(self.target_width, self.target_height)
            else:
                raise ConnectionError("No ADB device found and mode is set to 'adb'.")

    def _run_adb(self, args: List[str], timeout: int = 10) -> subprocess.CompletedProcess:
        cmd = [self.adb_bin]
        if self.serial:
            cmd.extend(["-s", self.serial])
        cmd.extend(args)
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)

    def get_connected_devices(self) -> List[str]:
        if not self.adb_bin:
            return []
        try:
            res = self._run_adb(["devices"])
            lines = res.stdout.strip().splitlines()[1:]
            devices = []
            for line in lines:
                parts = line.split()
                if len(parts) >= 2 and parts[1] == "device":
                    devices.append(parts[0])
            return devices
        except Exception:
            return []

    def detect_screen_size(self):
        """Reads native device screen resolution."""
        if self.mode == "mock":
            return
        try:
            res = self._run_adb(["shell", "wm", "size"])
            # Format: Physical size: 1272x2800, Override size: 1080x2378
            chosen = None
            for line in res.stdout.splitlines():
                if "override size:" in line.lower():
                    chosen = line.split(":")[-1].strip()
                    break
                elif "size:" in line.lower() and not chosen:
                    chosen = line.split(":")[-1].strip()

            if chosen:
                w, h = map(int, chosen.split("x"))
                self.device_width = max(w, h)
                self.device_height = min(w, h)
                print(f"[Device] Detected device resolution: {self.device_width}x{self.device_height}")
        except Exception as e:
            print(f"[Device] Could not detect screen size: {e}")

    def capture_frame(self) -> np.ndarray:
        """Returns the latest screen frame instantly in real time (0ms latency, not screenshot-blocking)."""
        with self._frame_lock:
            if self._current_frame is not None:
                return self._current_frame.copy()
            if self._latest_jpeg_bytes is not None:
                arr = np.frombuffer(self._latest_jpeg_bytes, dtype=np.uint8)
                frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                if frame is not None:
                    self._current_frame = frame
                    return frame.copy()

        # Immediate single fetch if background streamer has not yet populated buffer
        frame = self._fetch_frame_now()
        if frame is not None:
            with self._frame_lock:
                self._current_frame = frame
            return frame.copy()

        if not self.mock:
            self.mock = MockDevice(self.target_width, self.target_height)
        return self.mock.capture_frame()

    def capture_frame_jpeg(self) -> Optional[bytes]:
        """Returns the latest screen frame as encoded JPEG bytes directly (zero-reencode overhead)."""
        with self._frame_lock:
            if self._latest_jpeg_bytes is not None:
                return self._latest_jpeg_bytes

        frame = self.capture_frame()
        if frame is not None:
            ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
            if ok:
                b = buf.tobytes()
                with self._frame_lock:
                    self._latest_jpeg_bytes = b
                return b
        return None

    def ensure_game_running(self):
        """Checks if Clash of Clans is in the foreground without forcefully stealing focus."""
        if self.mode != "adb" or not self.adb_bin:
            return
        if self.is_game_foreground():
            print("[Device] Clash of Clans is verified in foreground.")
        else:
            print("[Device Safety Shield] Clash of Clans is NOT in foreground. AutoFarm is holding touch actions safely.")

    def _fetch_frame_now(self) -> Optional[np.ndarray]:
        """Low-level hardware screencap with fast raw-framebuffer acceleration."""
        if self.mode == "mock":
            if not self.mock:
                self.mock = MockDevice(self.target_width, self.target_height)
            return self.mock.capture_frame()

        if not self.adb_bin:
            return None

        # 1. Fast path: Raw uncompressed framebuffer DMA dump (No PNG compression lag)
        try:
            cmd = [self.adb_bin]
            if self.serial:
                cmd.extend(["-s", self.serial])
            cmd.extend(["exec-out", "screencap"])
            proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=8)
            if proc.returncode == 0 and len(proc.stdout) > 16:
                raw = proc.stdout
                w, h = struct.unpack("<II", raw[:8])
                if 200 < w < 4000 and 200 < h < 4000:
                    expected = 16 + (w * h * 4)
                    if len(raw) >= expected:
                        arr = np.frombuffer(raw[16:expected], dtype=np.uint8).reshape((h, w, 4))
                        frame = cv2.cvtColor(arr, cv2.COLOR_RGBA2BGR)
                        if h > w:
                            frame = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
                        self.device_width = frame.shape[1]
                        self.device_height = frame.shape[0]
                        self.target_width = self.device_width
                        self.target_height = self.device_height
                        return frame
        except Exception:
            pass

        # 2. Reliable fallback: Standard screencap -p
        try:
            cmd = [self.adb_bin]
            if self.serial:
                cmd.extend(["-s", self.serial])
            cmd.extend(["exec-out", "screencap", "-p"])
            proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=8)
            if proc.returncode == 0 and len(proc.stdout) > 1000:
                img_arr = np.frombuffer(proc.stdout, dtype=np.uint8)
                frame = cv2.imdecode(img_arr, cv2.IMREAD_COLOR)
                if frame is not None:
                    h, w = frame.shape[:2]
                    if h > w:
                        frame = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
                    self.device_width = frame.shape[1]
                    self.device_height = frame.shape[0]
                    self.target_width = self.device_width
                    self.target_height = self.device_height
                    return frame
        except Exception:
            pass

        return None

    def is_game_foreground(self) -> bool:
        """Strict safety check: returns True ONLY if Clash of Clans is actively focused in foreground."""
        if self.mode == "mock":
            return True
        if not self.adb_bin or not self.serial:
            return False
        now = time.time()
        if hasattr(self, "_last_fg_check") and (now - self._last_fg_check) < 0.8:
            return getattr(self, "_last_fg_result", False)
        try:
            res = self._run_adb(["shell", "dumpsys window | grep mCurrentFocus"], timeout=1.5)
            is_fg = bool(res.returncode == 0 and res.stdout and "com.supercell.clashofclans" in res.stdout)
            self._last_fg_check = now
            self._last_fg_result = is_fg
            return is_fg
        except Exception:
            return False

    def set_touch_enabled(self, enabled: bool):
        """Toggles hardware touch injection on/off."""
        self.touch_enabled = enabled
        status_str = "ENABLED" if enabled else "DISABLED (Inspection Mode)"
        print(f"[Device Safety Guard] Touch inputs {status_str}.")

    def is_game_foreground(self) -> bool:
        """Strict safety check: returns True ONLY if Clash of Clans is actively focused in foreground."""
        if self.mode == "mock":
            return True
        if not self.adb_bin or not self.serial:
            return False
        now = time.time()
        if hasattr(self, "_last_fg_check") and (now - self._last_fg_check) < 0.8:
            return getattr(self, "_last_fg_result", False)
        try:
            res = self._run_adb(["shell", "dumpsys window | grep mCurrentFocus"], timeout=1.5)
            is_fg = bool(res.returncode == 0 and res.stdout and "com.supercell.clashofclans" in res.stdout)
            self._last_fg_check = now
            self._last_fg_result = is_fg
            return is_fg
        except Exception:
            return False

    def set_touch_enabled(self, enabled: bool):
        """Toggles hardware touch injection on/off."""
        self.touch_enabled = enabled
        status_str = "ENABLED" if enabled else "DISABLED (Inspection Mode)"
        print(f"[Device Safety Guard] Touch inputs {status_str}.")

    def _scale_coords(self, x: int, y: int) -> Tuple[int, int]:
        """Translates virtual coordinate to native device screen coordinate."""
        if self.mode == "mock":
            return x, y
        if self.device_width == self.target_width and self.device_height == self.target_height:
            return x, y
        if x > self.target_width or y > self.target_height:
            return x, y
        sx = int(x * (self.device_width / float(self.target_width)))
        sy = int(y * (self.device_height / float(self.target_height)))
        return sx, sy

    def tap(self, x: int, y: int, press_duration_ms: Optional[int] = None):
        """Sends a humanized jittered tap with realistic touch duration."""
        if self.mode != "mock":
            if not self.touch_enabled:
                print(f"[Device Safety Guard] Touch inputs disabled. Tap at ({x}, {y}) skipped.")
                return

            if not self.is_game_foreground():
                print(f"[Device Safety Guard] CRITICAL: Tap at ({x}, {y}) BLOCKED! Clash of Clans is NOT in foreground.")
                return

        if self.mode != "mock":
            if not self.touch_enabled:
                print(f"[Device Safety Guard] Touch inputs disabled. Tap at ({x}, {y}) skipped.")
                return

            if not self.is_game_foreground():
                print(f"[Device Safety Guard] CRITICAL: Tap at ({x}, {y}) BLOCKED! Clash of Clans is NOT in foreground.")
                return

        jx, jy = Humanizer.jitter_point(x, y, max_radius=8)
        if self.mode == "mock":
            self.mock.tap(jx, jy)
            with self._frame_lock:
                self._current_frame = None
                self._latest_jpeg_bytes = None
            Humanizer.random_sleep(0.01, 0.05)
            return

        rx, ry = self._scale_coords(jx, jy)
        # Real human finger contact lasts 65ms to 125ms
        dur = press_duration_ms or random.randint(65, 125)
        self._run_adb(["shell", "input", "swipe", str(rx), str(ry), str(rx), str(ry), str(dur)])
        Humanizer.reaction_delay(0.15, 0.35)

    def tap_hold(self, x: int, y: int, duration_ms: int = 500):
        """Holds a position (useful for continuous troop deployment)."""
        if self.mode != "mock":
            if not self.touch_enabled:
                print(f"[Device Safety Guard] Touch inputs disabled. Hold at ({x}, {y}) skipped.")
                return

            if not self.is_game_foreground():
                print(f"[Device Safety Guard] CRITICAL: Hold at ({x}, {y}) BLOCKED! Clash of Clans is NOT in foreground.")
                return

        if self.mode != "mock":
            if not self.touch_enabled:
                print(f"[Device Safety Guard] Touch inputs disabled. Hold at ({x}, {y}) skipped.")
                return

            if not self.is_game_foreground():
                print(f"[Device Safety Guard] CRITICAL: Hold at ({x}, {y}) BLOCKED! Clash of Clans is NOT in foreground.")
                return

        jx, jy = Humanizer.jitter_point(x, y)
        if self.mode == "mock":
            self.mock.tap(jx, jy)
            return
        rx, ry = self._scale_coords(jx, jy)
        self._run_adb(["shell", "input", "swipe", str(rx), str(ry), str(rx), str(ry), str(duration_ms)])

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 400):
        """Executes a curved Bézier swipe mimicking human hand motion."""
        if self.mode != "mock":
            if not self.touch_enabled:
                print(f"[Device Safety Guard] Touch inputs disabled. Swipe skipped.")
                return

            if not self.is_game_foreground():
                print(f"[Device Safety Guard] CRITICAL: Swipe BLOCKED! Clash of Clans is NOT in foreground.")
                return

        if self.mode != "mock":
            if not self.touch_enabled:
                print(f"[Device Safety Guard] Touch inputs disabled. Swipe skipped.")
                return

            if not self.is_game_foreground():
                print(f"[Device Safety Guard] CRITICAL: Swipe BLOCKED! Clash of Clans is NOT in foreground.")
                return

        if self.mode == "mock":
            self.mock.swipe(x1, y1, x2, y2, duration_ms)
            return

        curve = Humanizer.bezier_curve((x1, y1), (x2, y2), num_points=12)
        sx1, sy1 = self._scale_coords(curve[0][0], curve[0][1])
        sx2, sy2 = self._scale_coords(curve[-1][0], curve[-1][1])
        self._run_adb(["shell", "input", "swipe", str(sx1), str(sy1), str(sx2), str(sy2), str(duration_ms)])
        Humanizer.random_sleep(0.2, 0.4)
