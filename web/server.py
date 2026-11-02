"""
FastAPI Web Dashboard Server for AutoFarm.
Provides real-time REST endpoints, MJPEG/JPEG video streaming, and configuration management.
"""

import io
from pathlib import Path
from typing import Dict, Optional

import cv2
from fastapi import FastAPI, HTTPException, Response, WebSocket, WebSocketDisconnect
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

    @app.get("/api/detections")
    def get_detections():
        """Returns the cached list of recognized entities and HUD bounding boxes instantly."""
        entities, state = bot_engine.vision.get_cached_detections()
        if not entities:
            frame = bot_engine.device.capture_frame()
            if frame is not None:
                entities = bot_engine.vision.detect_all_entities(frame)
                state = bot_engine.vision.detect_state(frame)
                bot_engine.vision.update_cached_detections(entities, state)
        return {"state": state, "entities": entities, "count": len(entities)}

    @app.post("/api/overlay/toggle")
    def toggle_detection_overlay():
        """Toggles real-time visual bounding box overlay on/off."""
        bot_engine.detection_overlay = not getattr(bot_engine, "detection_overlay", True)
        return {"detection_overlay": bot_engine.detection_overlay}

    @app.post("/api/automation/toggle")
    def toggle_automation():
        """Toggles autonomous touch inputs & attacking on/off."""
        bot_engine.automation_enabled = not getattr(bot_engine, "automation_enabled", False)
        if hasattr(bot_engine.device, "set_touch_enabled"):
            bot_engine.device.set_touch_enabled(bot_engine.automation_enabled)
        return {
            "automation_enabled": bot_engine.automation_enabled,
            "touch_enabled": getattr(bot_engine.device, "touch_enabled", False),
        }

    @app.post("/api/device/force_landscape")
    def force_landscape():
        """Forces the connected Android phone into Landscape orientation via ADB WindowManager."""
        if hasattr(bot_engine.device, "force_landscape_orientation"):
            success = bot_engine.device.force_landscape_orientation()
            return {"success": success}
        return {"success": False, "error": "Not supported on current device"}

    @app.post("/api/device/reset_orientation")
    def reset_orientation():
        """Unlocks screen orientation back to normal system auto-rotation."""
        if hasattr(bot_engine.device, "reset_orientation"):
            success = bot_engine.device.reset_orientation()
            return {"success": success}
        return {"success": False, "error": "Not supported on current device"}

    @app.get("/api/frame")
    def get_frame():
        """Returns the current screen with or without HUD bounding box overlay."""
        try:
            if getattr(bot_engine, "detection_overlay", True):
                frame = bot_engine.device.capture_frame()
                if frame is not None:
                    annotated = bot_engine.vision.draw_detection_overlay(
                        frame, inspection_mode=not getattr(bot_engine, "automation_enabled", False)
                    )
                    success, buffer = cv2.imencode(".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, 80])
                    if success:
                        return Response(content=buffer.tobytes(), media_type="image/jpeg")

            if hasattr(bot_engine.device, "capture_frame_jpeg"):
                jpeg = bot_engine.device.capture_frame_jpeg()
                if jpeg:
                    return Response(content=jpeg, media_type="image/jpeg")
            frame = bot_engine.device.capture_frame()
            success, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
            if not success:
                raise HTTPException(status_code=500, detail="Failed to encode frame")
            return Response(content=buffer.tobytes(), media_type="image/jpeg")
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/api/stream")
    def stream_live_video():
        """
        True real-time continuous video feed using MJPEG (multipart/x-mixed-replace).
        Includes real-time visual bounding box overlay when inspection mode is active.
        """
        import time

        def iter_stream():
            while True:
                try:
                    jpeg_bytes = None
                    if getattr(bot_engine, "detection_overlay", True):
                        frame = bot_engine.device.capture_frame()
                        if frame is not None:
                            annotated = bot_engine.vision.draw_detection_overlay(
                                frame, inspection_mode=not getattr(bot_engine, "automation_enabled", False)
                            )
                            ok, buffer = cv2.imencode(".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, 72])
                            if ok:
                                jpeg_bytes = buffer.tobytes()

                    if not jpeg_bytes:
                        if hasattr(bot_engine.device, "capture_frame_jpeg"):
                            jpeg_bytes = bot_engine.device.capture_frame_jpeg()
                        if not jpeg_bytes:
                            frame = bot_engine.device.capture_frame()
                            if frame is not None:
                                ok, buffer = cv2.imencode(
                                    ".jpg",
                                    frame,
                                    [cv2.IMWRITE_JPEG_QUALITY, 72]
                                )
                                if ok:
                                    jpeg_bytes = buffer.tobytes()

                    if jpeg_bytes:
                        yield (
                            b"--frame\r\n"
                            b"Content-Type: image/jpeg\r\n"
                            b"Content-Length: " + str(len(jpeg_bytes)).encode() + b"\r\n\r\n"
                            + jpeg_bytes
                            + b"\r\n"
                        )
                    time.sleep(0.04)  # ~25 FPS real-time broadcast with overlay
                except Exception:
                    time.sleep(0.05)

        return StreamingResponse(
            iter_stream(),
            media_type="multipart/x-mixed-replace; boundary=frame",
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0",
                "Connection": "close",
            },
        )

    @app.websocket("/ws/stream")
    async def websocket_video_stream(websocket: WebSocket):
        """Ultra-low latency WebSocket binary JPEG stream for instant 30 FPS video with boxes."""
        import asyncio
        await websocket.accept()
        try:
            while True:
                jpeg_bytes = None
                if getattr(bot_engine, "detection_overlay", True):
                    frame = bot_engine.device.capture_frame()
                    if frame is not None:
                        annotated = bot_engine.vision.draw_detection_overlay(
                            frame, inspection_mode=not getattr(bot_engine, "automation_enabled", False)
                        )
                        ok, buffer = cv2.imencode(".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, 72])
                        if ok:
                            jpeg_bytes = buffer.tobytes()

                if not jpeg_bytes:
                    if hasattr(bot_engine.device, "capture_frame_jpeg"):
                        jpeg_bytes = bot_engine.device.capture_frame_jpeg()
                    if not jpeg_bytes:
                        frame = bot_engine.device.capture_frame()
                        if frame is not None:
                            ok, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 72])
                            if ok:
                                jpeg_bytes = buffer.tobytes()

                if jpeg_bytes:
                    await websocket.send_bytes(jpeg_bytes)
                await asyncio.sleep(0.04)  # ~25 FPS
        except (WebSocketDisconnect, asyncio.CancelledError):
            pass
        except Exception:
            pass

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
