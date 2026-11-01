"""
Configuration management for AutoFarm.
Supports YAML loading, saving, and typed Pydantic validation.
"""

from pathlib import Path
from typing import List, Literal, Optional, Tuple
import yaml
from pydantic import BaseModel, Field

CONFIG_PATH = Path(__file__).parent / "config.yaml"


class DeviceConfig(BaseModel):
    mode: Literal["auto", "adb", "mock"] = "auto"
    adb_path: str = "auto"
    serial: str = ""
    resolution: dict = Field(default_factory=lambda: {"width": 1920, "height": 1080})


class FarmingConfig(BaseModel):
    min_gold: int = 450000
    min_elixir: int = 450000
    min_dark_elixir: int = 3500
    max_skips: int = 120
    next_delay_min: float = 1.8
    next_delay_max: float = 3.5
    trophy_min: int = 1800
    trophy_max: int = 2700


class AttackConfig(BaseModel):
    strategy: Literal["collector_snipe", "barch_wave", "full_assault"] = "collector_snipe"
    preferred_troop: Literal["sneaky_goblin", "barch", "baby_dragon"] = "sneaky_goblin"
    troops_per_collector: int = 3
    early_surrender: bool = True
    loot_depletion_threshold: float = 0.85
    stagnant_seconds: int = 7
    max_attack_duration_seconds: int = 120


class WallsConfig(BaseModel):
    enabled: bool = True
    reserve_gold: int = 1500000
    reserve_elixir: int = 1500000
    preferred_resource: Literal["gold", "elixir", "both"] = "both"
    max_upgrades_per_cycle: int = 10
    wall_sample_points: List[List[int]] = Field(
        default_factory=lambda: [[960, 540], [900, 500], [1020, 580], [840, 460]]
    )


class TrainingConfig(BaseModel):
    auto_train: bool = True
    quick_train_slot: int = 1
    min_army_capacity_pct: int = 85


class HomeConfig(BaseModel):
    auto_collect_resources: bool = True
    collect_interval_seconds: int = 300


class HumanizerConfig(BaseModel):
    bezier_curves: bool = True
    touch_jitter_px: int = 6
    reaction_delay_min: float = 0.35
    reaction_delay_max: float = 0.95
    session_break_every_attacks: int = 8
    break_duration_minutes_min: int = 8
    break_duration_minutes_max: int = 18


class DashboardConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8080
    open_browser: bool = True


class AppConfig(BaseModel):
    device: DeviceConfig = Field(default_factory=DeviceConfig)
    farming: FarmingConfig = Field(default_factory=FarmingConfig)
    attack: AttackConfig = Field(default_factory=AttackConfig)
    walls: WallsConfig = Field(default_factory=WallsConfig)
    training: TrainingConfig = Field(default_factory=TrainingConfig)
    home: HomeConfig = Field(default_factory=HomeConfig)
    humanizer: HumanizerConfig = Field(default_factory=HumanizerConfig)
    dashboard: DashboardConfig = Field(default_factory=DashboardConfig)


def load_config(path: Optional[Path] = None) -> AppConfig:
    p = path or CONFIG_PATH
    if not p.exists():
        cfg = AppConfig()
        save_config(cfg, p)
        return cfg
    with open(p, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return AppConfig(**data)


def save_config(cfg: AppConfig, path: Optional[Path] = None) -> None:
    p = path or CONFIG_PATH
    data = cfg.model_dump()
    with open(p, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=False, default_flow_style=False)
