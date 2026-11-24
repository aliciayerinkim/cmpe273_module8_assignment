import os
import sys

import requests

PRIMARY_URL = os.environ.get("PRIMARY_URL", "http://127.0.0.1:8001")
SECONDARY_URL = os.environ.get("SECONDARY_URL", "http://127.0.0.1:8002")
TIMEOUT = 2

USAGE = """usage:
  python client.py read primary|secondary|both
  python client.py write <stock>
  python client.py pause | resume | status"""


def call(method, url, body=None):
    try:
        r = requests.request(method, url, json=body, timeout=TIMEOUT)
        return r.json()
    except requests.RequestException as e:
        print(f"ERROR: could not reach {url} ({type(e).__name__})")
        return None


def read(name):
    url = PRIMARY_URL if name == "primary" else SECONDARY_URL
    return call("GET", f"{url}/stock")


def main():
    if len(sys.argv) < 2:
        print(USAGE)
        return
    cmd = sys.argv[1]

    if cmd == "read" and len(sys.argv) == 3 and sys.argv[2] in ("primary", "secondary"):
        data = read(sys.argv[2])
        if data:
            print(f"{data['replica']}: stock={data['stock']} version={data['version']}")

    elif cmd == "read" and len(sys.argv) == 3 and sys.argv[2] == "both":
        p = read("primary")
        s = read("secondary")
        if p is None or s is None:
            return
        print(f"primary:   stock={p['stock']} version={p['version']}")
        print(f"secondary: stock={s['stock']} version={s['version']}")
        if p["stock"] == s["stock"] and p["version"] == s["version"]:
            print("Result: SAME")
        else:
            print("Result: DIFFERENT (stale read)")

    elif cmd == "write" and len(sys.argv) == 3:
        try:
            value = int(sys.argv[2])
        except ValueError:
            print("ERROR: stock must be a whole number")
            return
        data = call("PUT", f"{PRIMARY_URL}/stock", {"stock": value})
        if data:
            print(f"write ok: {data}")

    elif cmd in ("pause", "resume"):
        data = call("POST", f"{PRIMARY_URL}/admin/{cmd}-replication")
        if data:
            print(f"{cmd} ok: {data}")

    elif cmd == "status":
        data = call("GET", f"{PRIMARY_URL}/admin/status")
        if data:
            print(f"status: paused={data['paused']} pending_updates={data['pending_updates']}")

    else:
        print(USAGE)


if __name__ == "__main__":
    main()
