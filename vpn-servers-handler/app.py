import json
import logging
import os
import time
import threading
from datetime import datetime
from collections import deque
import requests
from flask import Flask, request, jsonify

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger()

IP_LOG_FILE_NAME = "data/selected_ips.log"
BLACKLIST_FILE_NAME = "data/ip_blacklist.log"
MANUAL_SERVERS_FILE = "data/servers.json"

SERVER_CONSIDERED_ALREADY_USED_SEC = 36000
LOAD_UPPER_LIMIT_PCT = 95
LOAD_LOWER_LIMIT_PCT = 70
BEST_SERVER_MAX_COUNT = int(os.environ.get("MAX_SERVERS_TESTED", 6))

# DNS Alias pointing to the target environment's Subnet Keeper container
TARGET_ENV_HOST = "http://target-env-network:43988"

app = Flask(__name__)
best_servers_fifo_queue = deque(maxlen=BEST_SERVER_MAX_COUNT)
abort_test_flag = False
testing_lock = threading.Lock()

def get_blacklist_ips():
    if not os.path.exists(BLACKLIST_FILE_NAME): return set()
    with open(BLACKLIST_FILE_NAME, "r") as f:
        return set(line.strip() for line in f if line.strip())

def get_recent_ips():
    recent_ips = {}
    if os.path.exists(IP_LOG_FILE_NAME):
        with open(IP_LOG_FILE_NAME, "r") as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) == 2:
                    ip, timestamp = parts
                    if time.time() - float(timestamp) < SERVER_CONSIDERED_ALREADY_USED_SEC:
                        recent_ips[ip] = float(timestamp)
    return recent_ips

def log_selected_ip(ip):
    os.makedirs(os.path.dirname(IP_LOG_FILE_NAME), exist_ok=True)
    with open(IP_LOG_FILE_NAME, "a") as f:
        f.write(f"{ip} {time.time()}\n")

def shutdown_target_checker():
    try:
        requests.post(f"{TARGET_ENV_HOST}/shutdown", timeout=2)
    except requests.RequestException:
        pass
    logger.info("Sent shutdown/restart signal to Connection Quality Checker.")

def wait_for_endpoint_success(url, method="GET", retry_interval=5, timeout_seconds=120, ignore_abort=False):
    global abort_test_flag
    start_time = time.time()
    while True:
        # Ignore the abort flag if we explicitly bypass it
        if abort_test_flag and not ignore_abort:
            raise InterruptedError("Testing aborted.")

        try:
            resp = requests.request(method, url, timeout=5)
            if resp.status_code == 200:
                return resp.json()
        except requests.RequestException:
            pass

        if time.time() - start_time > timeout_seconds:
            raise TimeoutError(f"Timeout waiting for 200 OK from {url}.")

        time.sleep(retry_interval)

def generate_vpn_config(ip_address: str):
    config = {
        "version": 4,
        "timestamp": int(time.time()),
        "preferred": True,
        "servers": [{
            "vpn": "openvpn",
            "country": "United States",
            "city": "Atlanta",
            "server_name": "US-FREE#CUSTOM",
            "tcp": True,
            "udp": True,
            "free": True,
            "ips": [ip_address]
        }]
    }
    output_path = "data/target-env-gluetun/servers/protonvpn.json"
    temp_path = output_path + ".tmp"
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    # Must write tmp file to the SAME mount to avoid Cross-Device Link errors during os.replace
    with open(temp_path, "w", encoding="utf-8") as file:
        json.dump(config, file, indent=2)
    os.replace(temp_path, output_path)

@app.route('/best-server', methods=['GET'])
def analyze_and_collect_best_servers():
    if not testing_lock.acquire(blocking=False):
        return jsonify({"error": "Testing already in progress"}), 409
    try:
        return _analyze_and_collect_best_servers()
    finally:
        testing_lock.release()

@app.route('/prepare-vpn-server', methods=['GET', 'POST'])
def prepare_vpn_server():
    global best_servers_fifo_queue, abort_test_flag

    if len(best_servers_fifo_queue) == 0:
        return jsonify({"error": "No servers in memory. Run /best-server first."}), 404

    abort_test_flag = True  # Stop any ongoing testing
    time.sleep(1) # Allow testing loop to cleanly abort

    # Pop from the left (the best one) to move to the next best
    server = best_servers_fifo_queue.popleft()
    ip_address = server.get("ip")

    logger.info(f"🚀 Moving to next best server in queue: {server['name']} ({ip_address})")
    generate_vpn_config(ip_address)

    try:
        logger.info("⏳ Waiting for healthcheck on the new VPN server...")
        # Add ignore_abort=True here!
        wait_for_endpoint_success(f"{TARGET_ENV_HOST}/healthcheck", timeout_seconds=120, ignore_abort=True)

        return jsonify({
            "message": "VPN server prepared successfully",
            "servers_left_in_queue": len(best_servers_fifo_queue),
            "server": server
        }), 200
    except Exception as e:
        logger.error(f"Failed to prepare VPN server: {e}")
        return jsonify({"error": str(e)}), 500


def _analyze_and_collect_best_servers():
    global abort_test_flag, best_servers_fifo_queue
    abort_test_flag = False

    try:
        with open(MANUAL_SERVERS_FILE, "r") as f:
            all_logical_servers = json.load(f).get("LogicalServers", [])

        recent_ips = get_recent_ips()
        blacklist_ips = get_blacklist_ips()

        sorted_servers = sorted(
            all_logical_servers,
            key=lambda s: (s.get("Score", 100), s.get("Load", 100))
        )

        for server in sorted_servers:
            if abort_test_flag: break
            if not server.get("Servers"): continue

            entry_ip = server["Servers"][0]["EntryIP"]
            if server["Load"] > LOAD_UPPER_LIMIT_PCT or server["Load"] < LOAD_LOWER_LIMIT_PCT: continue
            if entry_ip in blacklist_ips or entry_ip in recent_ips: continue

            logger.info(f"Testing server: {server['Name']} (IP: {entry_ip})")

            # This write triggers the Custom Gluetun restart watcher over in the target env
            generate_vpn_config(entry_ip)

            is_sufficient = False
            test_details = {}
            try:
                logger.info("⏳ Waiting for Target Environment healthcheck...")
                wait_for_endpoint_success(f"{TARGET_ENV_HOST}/healthcheck", timeout_seconds=120)

                logger.info("🔵 Executing Connection Speed Test...")
                test_details = wait_for_endpoint_success(f"{TARGET_ENV_HOST}/speed-test", method="POST")

                logger.info(f"Speed Test Results: {json.dumps(test_details)}")
                is_sufficient = test_details.get("sufficient", False)

            except Exception as e:
                logger.error(f"Test failed for {entry_ip}: {e}")
            finally:
                if not abort_test_flag and not (is_sufficient and len(best_servers_fifo_queue) >= BEST_SERVER_MAX_COUNT - 1):
                    shutdown_target_checker()

            if not is_sufficient:
                logger.info("🔴 Connection too slow. Retrying another server in 30s...")
                time.sleep(30)
                continue

            log_selected_ip(entry_ip)
            logger.info(f"🟢 Selected server {server['Name']} ({entry_ip})")

            new_best_server = {
                "ip": entry_ip, "name": server['Name'],
                "loadPct": server['Load'], "city": server['City'],
                "score": server['Score'], "date_update": datetime.now()
            }
            new_best_server.update(test_details)
            best_servers_fifo_queue.append(new_best_server)

            logger.info("Artificial 60s delay between testing new VPNs to avoid rate-limiting.")
            time.sleep(60)

            if len(best_servers_fifo_queue) >= BEST_SERVER_MAX_COUNT:
                # We reached max capacity. The last tested server is the worst of the best.
                # Let's deploy the FIRST one in the queue (the absolute best) before returning.
                best_server = best_servers_fifo_queue[0]
                logger.info(f"✅ Testing complete. Deploying the absolute BEST server: {best_server['name']} ({best_server['ip']})")

                generate_vpn_config(best_server['ip'])

                logger.info("⏳ Waiting for Target Environment healthcheck to stabilize on the best server...")
                wait_for_endpoint_success(f"{TARGET_ENV_HOST}/healthcheck", timeout_seconds=120)

                return jsonify(list(best_servers_fifo_queue))

        if len(best_servers_fifo_queue) > 0:
            return jsonify(list(best_servers_fifo_queue))

        return jsonify({"error": "No suitable servers found."}), 500

    except Exception as e:
        logger.error(f"Error: {e}")
        return jsonify({"error": str(e)}), 500

# Include other endpoints here... (e.g. /best-server/last, /blacklist-ip, etc.)

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=43999)