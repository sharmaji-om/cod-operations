"""Local app launcher: opens a browser only after this server is responding."""
import argparse
from pathlib import Path
import threading
import time
import urllib.request
import webbrowser

import uvicorn


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    url = f"http://127.0.0.1:{args.port}"
    if not args.no_browser:
        def open_when_ready():
            for _ in range(50):
                try:
                    with urllib.request.urlopen(url, timeout=.3) as response:
                        if response.status == 200:
                            webbrowser.open(url)
                            return
                except OSError:
                    time.sleep(.2)
        threading.Thread(target=open_when_ready, daemon=True).start()
    print(f"COD Operations: {url}\nKeep this window open. Press Ctrl+C to stop.")
    uvicorn.run("cod_engine.api:app", host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
