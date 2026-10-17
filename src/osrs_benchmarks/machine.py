"""What the machine looked like during a run, and waiting for it to be quiet."""
import os
import platform
import socket
import time
from pathlib import Path

CPU = Path("/sys/devices/system/cpu")


def read(path, default="unknown"):
    try:
        return Path(path).read_text().strip()
    except OSError:
        return default


def cpu_model():
    for line in read("/proc/cpuinfo", "").splitlines():
        if line.startswith("model name"):
            return line.split(":", 1)[1].strip()
    return platform.processor() or "unknown"


def memory_bytes():
    for line in read("/proc/meminfo", "").splitlines():
        if line.startswith("MemTotal:"):
            return int(line.split()[1]) * 1024
    return 0


def os_release():
    for line in read("/etc/os-release", "").splitlines():
        if line.startswith("PRETTY_NAME="):
            return line.split("=", 1)[1].strip('"')
    return "unknown"


def describe():
    """The fields of a run row that describe the machine, plus machine_json's extras."""
    governors = sorted({read(p) for p in CPU.glob("cpu[0-9]*/cpufreq/scaling_governor")})
    boost = read(CPU / "cpufreq/boost")
    if boost == "unknown":
        no_turbo = read(CPU / "intel_pstate/no_turbo")
        boost = {"0": "1", "1": "0"}.get(no_turbo, "unknown")
    return {
        "hostname": socket.gethostname(),
        "kernel": platform.release(),
        "cpu_model": cpu_model(),
        "cpu_count": os.cpu_count() or 0,
        "cpu_governor": ",".join(governors) or "unknown",
        "cpu_boost": boost,
        "clock_source": read(CPU.parent / "clocksource/clocksource0/current_clocksource"),
        "memory_bytes": memory_bytes(),
        "load_1m": os.getloadavg()[0],
        "extra": {
            "os": os_release(),
            "scaling_driver": read(CPU / "cpu0/cpufreq/scaling_driver"),
            "energy_performance_preference": read(CPU / "cpu0/cpufreq/energy_performance_preference"),
            "amd_pstate": read(CPU / "amd_pstate/status"),
            "smt": read(CPU / "smt/active"),
            "load_avg": list(os.getloadavg()),
        },
    }


def cpu_times():
    """(busy, total) jiffies over all CPUs."""
    fields = [int(x) for x in read("/proc/stat", "cpu 0 0 0 0").splitlines()[0].split()[1:]]
    idle = fields[3] + (fields[4] if len(fields) > 4 else 0)
    total = sum(fields[:8])
    return total - idle, total


def busy_cores(seconds, sleep=time.sleep):
    """How many cores' worth of CPU were in use over the next `seconds`."""
    busy0, total0 = cpu_times()
    sleep(seconds)
    busy1, total1 = cpu_times()
    if total1 == total0:
        return 0.0
    return (busy1 - busy0) / (total1 - total0) * (os.cpu_count() or 1)


class Busy(Exception):
    pass


def wait_quiet(max_cores, quiet_minutes, deadline_minutes, sample=busy_cores, log=print):
    """Wait until fewer than max_cores were busy for quiet_minutes straight, or raise Busy.

    Benchmarks share caches, memory bandwidth and boost headroom with whatever else runs, so a
    run only starts once the machine has been quiet for a while.
    """
    quiet = 0
    worst = 0.0
    for _ in range(deadline_minutes):
        used = sample(60)
        if used < max_cores:
            quiet += 1
            if quiet >= quiet_minutes:
                return
        else:
            quiet = 0
            worst = max(worst, used)
            log(f"busy: {used:.1f} cores in use")
    raise Busy(f"not quiet for {quiet_minutes} minutes within {deadline_minutes} "
               f"(up to {worst:.1f} cores in use, limit {max_cores})")
