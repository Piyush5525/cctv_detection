"""System telemetry helper for the Phase 1c follow-up 2 FPS investigation
(thermal-throttling/confound check). Reports whatever this machine/OS
actually exposes -- explicitly says "not available" rather than
guessing or omitting silently when a metric can't be read.
"""
from __future__ import annotations

import os

import psutil


def get_power_status() -> dict:
    try:
        battery = psutil.sensors_battery()
    except Exception:
        battery = None
    if battery is None:
        return {"on_ac_power": "not available (no battery sensor -- desktop or not exposed)", "power_plan": _get_power_plan()}
    return {"on_ac_power": bool(battery.power_plugged), "power_plan": _get_power_plan()}


def _get_power_plan() -> str:
    try:
        import subprocess
        result = subprocess.run(["powercfg", "/getactivescheme"], capture_output=True, text=True, timeout=5)
        return result.stdout.strip() if result.returncode == 0 else "not available"
    except Exception:
        return "not available"


def get_cpu_clock_mhz() -> str:
    try:
        freq = psutil.cpu_freq()
        if freq is None:
            return "not available"
        return f"{freq.current:.0f} MHz (min={freq.min:.0f}, max={freq.max:.0f})"
    except Exception:
        return "not available"


def get_cpu_temperature_c() -> str:
    # psutil.sensors_temperatures() is Linux-only; not available on Windows.
    try:
        temps = psutil.sensors_temperatures()
        if not temps:
            return "not available (no sensor exposed)"
        for name, entries in temps.items():
            for e in entries:
                if e.current:
                    return f"{e.current:.1f}C ({name})"
        return "not available (sensor present but no reading)"
    except AttributeError:
        return "not available (psutil.sensors_temperatures not supported on this OS)"
    except Exception:
        return "not available"


def get_process_telemetry(pid: int = None) -> dict:
    """RSS memory, thread count for the given pid (default: this process)."""
    p = psutil.Process(pid or os.getpid())
    mem = p.memory_info()
    return {
        "rss_mb": round(mem.rss / 1024 / 1024, 1),
        "num_threads": p.num_threads(),
    }


def telemetry_snapshot(pid: int = None) -> dict:
    proc = get_process_telemetry(pid)
    return {
        "rss_mb": proc["rss_mb"],
        "num_threads": proc["num_threads"],
        "cpu_clock": get_cpu_clock_mhz(),
        "cpu_temp": get_cpu_temperature_c(),
    }


if __name__ == "__main__":
    print("Power status:", get_power_status())
    print("CPU clock:", get_cpu_clock_mhz())
    print("CPU temp:", get_cpu_temperature_c())
    print("Process telemetry (self):", get_process_telemetry())
