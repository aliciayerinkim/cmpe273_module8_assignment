import argparse
import logging
import threading
import time

import requests
from flask import Flask, jsonify, request

parser = argparse.ArgumentParser()
parser.add_argument("--role", choices=["primary", "secondary"], required=True)
parser.add_argument("--port", type=int, required=True)
parser.add_argument("--secondary-url", default="http://127.0.0.1:8002")
args = parser.parse_args()

ROLE = args.role
SECONDARY_URL = args.secondary_url

app = Flask(__name__)
logging.getLogger("werkzeug").setLevel(logging.ERROR)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")

state = {"stock": 10, "version": 1}
repl_queue = []
paused = False
lock = threading.Lock()


def log(event):
    logging.info("[%s] %s | stock=%s version=%s", ROLE, event, state["stock"], state["version"])


@app.after_request
def log_request(response):
    log(f"{request.method} {request.path} -> {response.status_code}")
    return response


@app.get("/health")
def health():
    return jsonify({"status": "ok", "replica": ROLE}), 200


@app.get("/stock")
def get_stock():
    with lock:
        return jsonify({"replica": ROLE, "stock": state["stock"], "version": state["version"]})


@app.put("/stock")
def put_stock():
    if ROLE != "primary":
        return jsonify({"error": "secondary is read-only, write to the primary"}), 403
    data = request.get_json(silent=True) or {}
    if not isinstance(data.get("stock"), int):
        return jsonify({"error": "send JSON like {\"stock\": 9}"}), 400
    with lock:
        state["stock"] = data["stock"]
        state["version"] += 1
        repl_queue.append({"stock": state["stock"], "version": state["version"]})
        log(f"write saved, queued for replication (queue={len(repl_queue)})")
        return jsonify({"replica": ROLE, "stock": state["stock"], "version": state["version"]})


@app.post("/replicate")
def replicate():
    if ROLE != "secondary":
        return jsonify({"error": "only the secondary accepts /replicate"}), 403
    data = request.get_json(silent=True) or {}
    with lock:
        if data.get("version", 0) > state["version"]:
            state["stock"] = data["stock"]
            state["version"] = data["version"]
            log("replication applied")
            return jsonify({"applied": True})
        log(f"replication ignored (old or duplicate version {data.get('version')})")
        return jsonify({"applied": False})


@app.post("/admin/pause-replication")
def pause():
    global paused
    if ROLE != "primary":
        return jsonify({"error": "admin endpoints are on the primary"}), 403
    paused = True
    log("replication paused")
    return jsonify({"paused": True})


@app.post("/admin/resume-replication")
def resume():
    global paused
    if ROLE != "primary":
        return jsonify({"error": "admin endpoints are on the primary"}), 403
    paused = False
    log("replication resumed")
    return jsonify({"paused": False})


@app.get("/admin/status")
def status():
    if ROLE != "primary":
        return jsonify({"error": "admin endpoints are on the primary"}), 403
    with lock:
        return jsonify({"paused": paused, "pending_updates": len(repl_queue)})


def replication_loop():
    # Sends queued updates to the secondary, oldest first.
    while True:
        time.sleep(0.5)
        if paused:
            continue
        with lock:
            if not repl_queue:
                continue
            update = repl_queue[0]
        try:
            r = requests.post(f"{SECONDARY_URL}/replicate", json=update, timeout=2)
            r.raise_for_status()
            with lock:
                repl_queue.pop(0)
                log(f"replicated version {update['version']} to secondary (queue={len(repl_queue)})")
        except requests.RequestException as e:
            log(f"replication of version {update['version']} failed, will retry ({type(e).__name__})")
            time.sleep(1)


if __name__ == "__main__":
    if ROLE == "primary":
        threading.Thread(target=replication_loop, daemon=True).start()
    log(f"starting on port {args.port}")
    app.run(host="127.0.0.1", port=args.port, threaded=True)
