#!/usr/bin/env python3
"""
Incident Command Dashboard - Complete System Runner

This script starts both the FastAPI backend and the detection pipeline.
The frontend is served by the FastAPI backend (after building).
"""

import os
import sys
import subprocess
import signal
import time
import threading
from pathlib import Path


def run_fastapi():
    """Run the FastAPI backend server."""
    os.chdir(Path(__file__).parent)
    sys.path.insert(0, str(Path(__file__).parent))
    
    import uvicorn
    from api.main import app
    
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")


def run_detection():
    """Run the detection pipeline in headless mode (no cv2 window)."""
    os.chdir(Path(__file__).parent)
    sys.path.insert(0, str(Path(__file__).parent))
    
    from main import main
    main(headless=True)


def build_frontend():
    """Build the React frontend."""
    frontend_dir = Path(__file__).parent / "frontend"
    if not frontend_dir.exists():
        print("Frontend directory not found")
        return False
    
    print("Building frontend...")
    try:
        # On Windows, npm is a .cmd file - need shell=True
        use_shell = sys.platform == "win32"
        
        # Install dependencies if node_modules doesn't exist
        if not (frontend_dir / "node_modules").exists():
            print("Installing frontend dependencies...")
            subprocess.run(["npm", "install"], cwd=frontend_dir, check=True, shell=use_shell)
        
        # Build the frontend
        subprocess.run(["npm", "run", "build"], cwd=frontend_dir, check=True, shell=use_shell)
        print("Frontend built successfully")
        return True
    except subprocess.CalledProcessError as e:
        print(f"Frontend build failed: {e}")
        return False


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Incident Command Dashboard Runner")
    parser.add_argument("--mode", choices=["all", "api", "detection", "build"], default="all",
                        help="Run mode: all (api+detection), api only, detection only, or build frontend")
    parser.add_argument("--no-build", action="store_true", help="Skip frontend build")
    args = parser.parse_args()
    
    # Build frontend if needed
    if args.mode in ["all", "api"] and not args.no_build:
        if not build_frontend():
            print("Warning: Frontend build failed, continuing anyway...")
    
    processes = []
    
    def signal_handler(sig, frame):
        print("\nShutting down...")
        for p in processes:
            if p.is_alive():
                p.terminate()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    if args.mode in ["all", "api"]:
        print("Starting FastAPI backend on http://localhost:8000")
        api_thread = threading.Thread(target=run_fastapi, daemon=True)
        api_thread.start()
        processes.append(api_thread)
        time.sleep(2)  # Give API time to start
    
    if args.mode in ["all", "detection"]:
        print("Starting detection pipeline...")
        detection_thread = threading.Thread(target=run_detection, daemon=True)
        detection_thread.start()
        processes.append(detection_thread)
    
    if args.mode == "build":
        return
    
    print("\nSystem running. Press Ctrl+C to stop.")
    print("- Dashboard: http://localhost:8000")
    print("- API Docs: http://localhost:8000/api/docs")
    
    try:
        while True:
            time.sleep(1)
            # Check if threads are still alive
            alive = [p for p in processes if p.is_alive()]
            if not alive and args.mode != "build":
                print("All processes stopped")
                break
    except KeyboardInterrupt:
        print("\nShutting down...")


if __name__ == "__main__":
    main()