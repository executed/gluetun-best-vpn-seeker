import logging
import os
import signal
import time
import requests
from flask import Flask, jsonify

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("ConnectionQualityChecker")

app = Flask(__name__)

@app.route('/healthcheck', methods=['GET'])
def healthcheck():
    try:
        # Validate that the VPN tunnel is up and internet is reachable
        requests.get("https://1.1.1.1", timeout=3)
        return jsonify(status="ok"), 200
    except Exception:
        return jsonify(status="unavailable"), 503

@app.route('/shutdown', methods=['POST'])
def shutdown():
    logger.warning("Shutdown triggered by Controller. Restarting Python process...")
    try:
        os.killpg(os.getpgid(0), signal.SIGTERM)
    except Exception:
        os._exit(0)
    return '', 204

@app.route('/speed-test', methods=['POST'])
def speed_test():
    # 25MB test file download to verify network stability and speed
    test_file_url = "https://speed.cloudflare.com/__down?bytes=25000000"

    try:
        logger.info(f"Starting Speed Test...")
        start_time = time.time()

        resp = requests.get(test_file_url, stream=True, timeout=15)
        resp.raise_for_status()

        total_bytes = 0
        for chunk in resp.iter_content(chunk_size=8192):
            if chunk: total_bytes += len(chunk)

        duration_sec = max(time.time() - start_time, 0.1) # Prevent DivisionByZero

        # Calculate speed
        mbps = (total_bytes * 8) / (duration_sec * 1_000_000)

        # Check against target speed requirement (20 Mbps)
        is_sufficient = mbps >= 20.0

        logger.info(f"Speed Result: {mbps:.2f} Mbps | Sufficient: {is_sufficient}")

        return jsonify({
            "measured_speed_mbps": mbps,
            "sufficient": is_sufficient,
            "message": f"Measured speed is {mbps:.2f} Mbps"
        }), 200

    except Exception as e:
        logger.error(f"Speed test failed: {e}")
        return jsonify({"error": "Speed test failed", "details": str(e)}), 400

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=43988)