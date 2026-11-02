"""
AutoFarm Clash of Clans - Main Entry Point.
Runs the autonomous bot engine alongside the Web Dashboard or in headless CLI mode.
"""

import argparse
import sys
import webbrowser

import uvicorn

from config.settings import load_config
from core.state_machine import BotEngine
from web.server import create_app


def main():
    parser = argparse.ArgumentParser(description="AutoFarm CoC - Personal Autonomous Bot")
    parser.add_argument("--cli", action="store_true", help="Run directly in headless CLI mode without web dashboard")
    parser.add_argument("--mock", action="store_true", help="Force high-fidelity mock simulation mode")
    parser.add_argument("--host", default=None, help="Dashboard host IP")
    parser.add_argument("--port", type=int, default=None, help="Dashboard port")
    parser.add_argument("--no-browser", action="store_true", help="Do not auto-open web browser")
    parser.add_argument("--autostart", action="store_true", help="Automatically start farming cycle immediately")
    args = parser.parse_args()

    cfg = load_config()

    if args.mock:
        cfg.device.mode = "mock"

    host = args.host or cfg.dashboard.host
    port = args.port or cfg.dashboard.port

    print("=" * 60)
    print(" ⚔️  AutoFarm Clash of Clans - Personal Automation Engine")
    print(f" Mode: {cfg.device.mode.upper()}")
    print(f" Min Loot Targets: Gold={cfg.farming.min_gold:,} | Elixir={cfg.farming.min_elixir:,}")
    print(f" Wall Reserve: Gold={cfg.walls.reserve_gold:,} | Elixir={cfg.walls.reserve_elixir:,}")
    print("=" * 60)

    bot = BotEngine(cfg)

    if args.cli:
        print("\n[AutoFarm] Running in headless CLI mode. Press Ctrl+C to stop.")
        bot.start()
        try:
            while True:
                import time
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n[AutoFarm] Stopping bot gracefully...")
            bot.stop()
            sys.exit(0)
    else:
        app = create_app(bot)
        dashboard_url = f"http://{host}:{port}"
        print(f"\n🚀 Web Dashboard running at: {dashboard_url}")

        if args.autostart:
            print("\n[AutoFarm] Auto-starting farming cycle on connected device...")
            bot.start()

        if cfg.dashboard.open_browser and not args.no_browser:
            try:
                webbrowser.open(dashboard_url)
            except Exception:
                pass

        uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    main()
