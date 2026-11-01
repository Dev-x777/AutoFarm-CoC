"""
FastAPI Web Dashboard Server for AutoFarm.
Provides real-time REST endpoints, MJPEG/JPEG video streaming, and configuration management.
"""

import io
from pathlib import Path
from typing import Dict, Optional

import cv2
from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from config.settings import AppConfig, load_config, save_config
from core.state_machine import BotEngine

STATIC_DIR = Path(__file__).parent / "static"


def create_app(bot_engine: BotEngine) -> FastAPI:
    app = FastAPI(title="AutoFarm Clash of Clans Dashboard", version="2.0.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Mount static files
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/")
    def index():
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/api/status")
    def get_status() -> Dict:
        return bot_engine.get_summary()

    @app.get("/api/logs")
    def get_logs():
        return {"logs": bot_engine.logs[-60:]}

    @app.post("/api/start")
    def start_bot():
        bot_engine.start()
        return {"status": "started"}

    @app.post("/api/pause")
    def pause_bot():
        bot_engine.pause()
        return {"status": "paused"}

    @app.post("/api/resume")
    def resume_bot():
        bot_engine.resume()
        return {"status": "resumed"}

    @app.post("/api/stop")
    def stop_bot():
        bot_engine.stop()
        return {"status": "stopped"}

    @app.post("/api/action/walls")
    def force_upgrade_walls():
        count = bot_engine.wall_upgrader.run_upgrade_cycle()
        return {"upgraded": count}

    @app.post("/api/action/train")
    def force_train_army():
        res = bot_engine.trainer.train_army()
        return {"success": res}

    @app.get("/api/frame")
    def get_frame():
        """Returns the current screen as a JPEG image."""
        try:
            frame = bot_engine.device.capture_frame()
            # Encode as JPEG
            success, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
            if not success:
                raise HTTPException(status_code=500, detail="Failed to encode frame")
            return Response(content=buffer.tobytes(), media_type="image/jpeg")
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/api/config")
    def get_configuration():
        return bot_engine.config.model_dump()

    class ConfigUpdateRequest(BaseModel):
        min_gold: Optional[int] = None
        min_elixir: Optional[int] = None
        min_dark_elixir: Optional[int] = None
        early_surrender: Optional[bool] = None
        reserve_gold: Optional[int] = None
        reserve_elixir: Optional[int] = None
        preferred_strategy: Optional[str] = None

    @app.post("/api/config")
    def update_configuration(req: ConfigUpdateRequest):
        cfg = bot_engine.config
        if req.min_gold is not None:
            cfg.farming.min_gold = req.min_gold
        if req.min_elixir is not None:
            cfg.farming.min_elixir = req.min_elixir
        if req.min_dark_elixir is not None:
            cfg.farming.min_dark_elixir = req.min_dark_elixir
        if req.early_surrender is not None:
            cfg.attack.early_surrender = req.early_surrender
        if req.reserve_gold is not None:
            cfg.walls.reserve_gold = req.reserve_gold
        if req.reserve_elixir is not None:
            cfg.walls.reserve_elixir = req.reserve_elixir
        if req.preferred_strategy is not None:
            cfg.attack.strategy = req.preferred_strategy

        save_config(cfg)
        return {"status": "updated", "config": cfg.model_dump()}

    return app
