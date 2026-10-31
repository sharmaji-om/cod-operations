"""Time installation/training/tests/startup in an isolated copy; preserve source data."""
from datetime import datetime
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen


root = Path(__file__).resolve().parents[1]
started = time.perf_counter()
(root / ".setup-check").mkdir(exist_ok=True)
workspace = Path(tempfile.mkdtemp(prefix="clean-setup-", dir=root / ".setup-check"))
app = workspace / "app"
app.mkdir()
for directory in ["cod_engine", "web", "tests", "artifacts"]:
    shutil.copytree(root / directory, app / directory, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
(app / "data").mkdir()
(app / "reports").mkdir()
shutil.copy2(root / "data/orders_sample.csv", app / "data/orders_sample.csv")
for name in ["config.json", "requirements-lock.txt", "requirements.txt", "README.md"]:
    shutil.copy2(root / name, app / name)
timings = {}
environment = {k: v for k, v in os.environ.items() if k not in {"COD_DB", "COD_CONFIG", "COD_MODEL", "PYTHONPATH", "VIRTUAL_ENV"}}
environment["PYTHONIOENCODING"] = "utf-8"


def step(name, command):
    before = time.perf_counter()
    print(f"START {name}", flush=True)
    result = subprocess.run(command, cwd=app, env=environment, text=True, encoding="utf-8", errors="replace", stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    (workspace / (name + ".log")).write_text(result.stdout, encoding="utf-8")
    timings[name] = round(time.perf_counter()-before, 2)
    print(f"END {name}: exit={result.returncode}, seconds={timings[name]}", flush=True)
    if result.returncode:
        print(result.stdout[-6000:], flush=True)
        raise RuntimeError(f"{name} failed; see {workspace / (name + '.log')}")
    if name in {"tests", "dependency_check"}:
        print(result.stdout.strip(), flush=True)


try:
    step("create_environment", [sys.executable, "-m", "venv", str(workspace / ".venv")])
    python = workspace / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    step("install_no_cache", [str(python), "-m", "pip", "install", "--no-cache-dir", "--disable-pip-version-check", "-r", "requirements-lock.txt"])
    step("dependency_check", [str(python), "-m", "pip", "check"])
    step("train", [str(python), "-m", "cod_engine.train"])
    step("tests", [str(python), "-m", "pytest", "-q"])
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    before = time.perf_counter()
    with (workspace / "server.log").open("w", encoding="utf-8") as log:
        process = subprocess.Popen([str(python), "-m", "cod_engine.launch", "--no-browser", "--port", str(port)], cwd=app, env=environment, stdout=log, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        try:
            for _ in range(150):
                try:
                    with urlopen(f"http://127.0.0.1:{port}/dashboard", timeout=2) as response:
                        dashboard = json.load(response)
                    break
                except OSError:
                    if process.poll() is not None:
                        raise RuntimeError("server exited before readiness")
                    time.sleep(.2)
            else:
                raise RuntimeError("startup timed out")
            with urlopen(f"http://127.0.0.1:{port}/") as response:
                assert response.status == 200
            assert dashboard["eligible_count"] == 16
            assert sum(dashboard["buckets"].values()) == 16
            timings["startup_and_dashboard"] = round(time.perf_counter()-before, 2)
        finally:
            process.terminate()
            process.wait(timeout=10)
    report = {"result": "pass", "tested_at": datetime.now().astimezone().isoformat(), "python": sys.version.split()[0], "platform": sys.platform, "pip_cache_used": False, "timings_seconds": timings, "total_seconds": round(time.perf_counter()-started, 2), "dashboard_orders": 16, "logs_directory": str(workspace), "conditions": "Python already installed; working package-download access. This machine/network only; not a universal setup-time guarantee."}
except Exception as error:
    report = {"result": "fail", "error": str(error), "timings_seconds": timings, "total_seconds": round(time.perf_counter()-started, 2), "logs_directory": str(workspace)}
(root / "reports/clean-setup-result.json").write_text(json.dumps(report, indent=2)+"\n", encoding="utf-8")
print(json.dumps(report, indent=2), flush=True)
sys.exit(0 if report["result"] == "pass" else 1)
