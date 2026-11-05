# Automated Gluetun Best VPN Seeker & Speed Tester

This project is a minimal, automated Docker-based environment that dynamically finds the best ProtonVPN server based on load, scores, and real-world download speeds.

It splits the logic into two decoupled components:
1. **VPN Servers Handler (Controller):** Iterates through a hardcoded list of ProtonVPN servers (by default; configurable), injects the selected configuration into a shared Docker volume, and orchestrates the speed test.
2. **Target Environment (Runner):** Houses the VPN tunnel (Gluetun), a dummy network namespace keeper to prevent container link breakage, a network speed tester, and a minimal target application that logs your newly assigned public IP, physical location, and **performs an automated DNS leak test**.

---

## TL;DR:

This project is an automated Docker-based system that dynamically finds the fastest ProtonVPN server (by default; configurable) for your Gluetun setup. It works by iterating through a list of servers, ranking them by load and score, and running real-world download speed tests (≥ 20 Mbps) inside a decoupled target environment. 

A custom Gluetun image watches for config changes and restarts the VPN automatically. The controller exposes two API endpoints: GET /best-server to run the full search and deploy the absolute best server, and POST /prepare-vpn-server to rotate to the next best server from an in-memory queue. Successful servers are kept only in RAM, so restarting the controller clears the queue. 

The system also performs automated DNS leak tests and logs your assigned IP, location, and ISP.

Ultimately, this is basically a template showcase you can adapt to whatever project you want—swap in your own target service, test logic, and deployment flow.

## Architecture Overview

* **Shared Network (`shared_interop_network`):** Allows the Handler to trigger speed tests inside the Target Environment without hardcoded IP addresses.
* **Shared Volume (`shared_vpn_config_vol`):** Used by the Handler to write the `protonvpn.json` config file directly into Gluetun's directory.
* **Custom Gluetun Watcher:** Gluetun natively doesn't restart when its configuration files change. We use a **Custom Gluetun Image** equipped with a file-watcher wrapper script that instantly restarts the VPN connection when the Handler writes a new server config.

---

## Prerequisites

1. **Docker** and **Docker Compose** installed on your host.
2. **Git** installed.
3. ProtonVPN OpenVPN credentials.

---

## Step 1: Build the Custom Gluetun Image

Because we need Gluetun to restart automatically when a new server is selected, you must build a custom version of Gluetun.

> ⚠️ **DISCLAIMER: TEMPORARY WORKAROUND**  
> The `Dockerfile` tweak required below is a temporary workaround. Natively, Gluetun does not yet support hot-reloading when custom configuration files change. Given the uncertainty in timelines of when this will be officially implemented, we are using this custom file-watcher wrapper script.  
> You can track the official feature request here: [passteque/gluetun#3417](https://github.com/passteque/gluetun/issues/3417)

Run the following commands in your terminal to clone the latest official Gluetun, append our custom file-watcher to its `Dockerfile`, and build the image:

```bash
# 1. Clone the official Gluetun repository
git clone https://github.com/passteque/gluetun.git
cd gluetun

# 2. Append the custom Config-Watcher wrapper to the Dockerfile
cat <<'EOF' >> Dockerfile

RUN cat <<'INNER_EOF' > /wrapper_temp.sh
#!/bin/sh

CONFIG_FILE="/gluetun/servers/protonvpn.json"
CHECKSUM_FILE="/tmp/protonvpn-servers.checksum"

checksum() {
    md5sum "\$1" | awk '{print \$1}'
}

# Record the initial state before starting Gluetun.
if [ -f "\$CONFIG_FILE" ]; then
    checksum "\$CONFIG_FILE" > "\$CHECKSUM_FILE"
else
    : > "\$CHECKSUM_FILE"
fi

(
    while true; do
        sleep 10

        PREVIOUS_CHECKSUM=\$(cat "\$CHECKSUM_FILE" 2>/dev/null || true)

        if [ ! -f "\$CONFIG_FILE" ]; then
            # Handle removal of an existing custom configuration.
            if [ -n "\$PREVIOUS_CHECKSUM" ]; then
                : > "\$CHECKSUM_FILE"
                echo "[Config-Watcher] ProtonVPN server file removed. Restarting..."
                kill -TERM 1
                exit 0
            fi
            continue
        fi

        CURRENT_CHECKSUM=\$(checksum "\$CONFIG_FILE" 2>/dev/null) || continue

        # Ignore Gluetun's ordinary built-in provider file.
        # We only react to your explicitly preferred configuration.
        if ! grep -Eq '"preferred"[[:space:]]*:[[:space:]]*true' "\$CONFIG_FILE"; then
            echo "\$CURRENT_CHECKSUM" > "\$CHECKSUM_FILE"
            continue
        fi

        if [ "\$CURRENT_CHECKSUM" != "\$PREVIOUS_CHECKSUM" ]; then
            echo "\$CURRENT_CHECKSUM" > "\$CHECKSUM_FILE"
            echo "[Config-Watcher] Preferred ProtonVPN configuration changed!"
            echo "[Config-Watcher] Restarting Gluetun..."
            # Gracefully terminate Gluetun. Docker's restart policy brings it back.
            kill -TERM 1
            exit 0
        fi
    done
) &

# Execute the original Gluetun entrypoint
exec /gluetun-entrypoint "\$@"
INNER_EOF

# Strip any Windows carriage returns, save as the final script, and make executable
RUN tr -d '\r' < /wrapper_temp.sh > /wrapper.sh && \
    chmod +x /wrapper.sh && \
    rm /wrapper_temp.sh

# Change entrypoint to our new wrapper
ENTRYPOINT ["/wrapper.sh"]
EOF

# 3. Build the custom image (replace 'yourusername' with your Docker Hub username if pushing remotely)
docker build -t yourusername/custom-gluetun:latest .

# 4. (Optional) If deploying to a remote server, push the image to a registry
docker push yourusername/custom-gluetun:latest
```

Once built, open `target-environment/docker-compose.yml` and update the `gluetun` service to use your new image:
```yaml
  gluetun:
    image: yourusername/custom-gluetun:latest  # <--- Update this line!
```

---

## Step 2: Configuration

Before bringing the environments up, you need to provide your data and credentials.

1. **VPN Server List:** (Optional)
   Place your `servers.json` file inside `vpn-servers-handler/data/servers.json`. (This should contain the hardcoded list of ProtonVPN servers). By default, there is already a scraped list of US free servers included, but it is not automatically updated so it's your responsibility to keep it up-to-date. Based on experience, this setup can work for a long time with the provided server list because the system rigorously tests each server anyway.
2. **ProtonVPN Credentials:**
   Open `target-environment/docker-compose.yml` and replace the placeholder OpenVPN credentials under the `gluetun` service environment variables:
   ```yaml
      - OPENVPN_USER=your_protonvpn_username
      - OPENVPN_PASSWORD=your_protonvpn_password
   ```

### Environment Variables
In the `vpn-servers-handler/docker-compose.yml`, you can optionally configure:
* `MAX_SERVERS_TESTED`: (Default: `6`). The maximum number of successful servers the system will test and keep in memory before finalizing the search.

---

## Step 3: Deployment

**⚠️ CRITICAL: Strict Deployment Order**
The `vpn-servers-handler` acts as the master creator of the shared Docker volume and Docker network. It **MUST** be started first.

### 1. Start the Controller (VPN Servers Handler)
```bash
cd vpn-servers-handler
docker compose up -d
```
*Wait a few seconds for it to initialize.*

### 2. Start the Runner (Target Environment)
```bash
cd ../target-environment
docker compose up -d
```

---

## Step 4: Testing & Usage

To trigger the server search and speed test, make a `GET` request to the controller's API. You can do this from your browser or via `curl`:

```bash
curl http://localhost:43999/best-server
```
## How the Testing Engine Works

When you trigger the testing process, the Controller performs the following sequence:

1. **Sorting:** It reads the `servers.json` file and sorts all available ProtonVPN servers from best to worst based on their `Score` and `Load`.
2. **Iteration & Testing:** It connects to the servers one by one. For each server, it writes a config file, waits for the VPN to restart, and commands the Target Environment to run a 25MB download speed test.
3. **Queueing:** If the server passes the speed test (≥ 20 Mbps), it is added to the back of the queue (kept in memory).
4. **Finalization (The Best Server):** The final server tested to reach the `MAX_SERVERS_TESTED` limit is technically the *worst* of the best (because they were sorted best-to-worst initially). Therefore, once testing finishes, **the engine automatically reverts and deploys the FIRST server in the queue (the absolute best one)** so your final state is optimal.

> ⚠️ **IMPORTANT: In-Memory Storage Only**
> The list of successful servers is strictly kept in RAM. If the `vpn-servers-handler` container is restarted, the saved configurations are lost, and you must run the `/best-server` endpoint again to repopulate the queue.

---

## API Endpoints

All requests should be made to the Controller at `http://localhost:43999`.

### `GET /best-server`
**Starts the testing process.**
* Iterates through servers, filters out blacklisted/recent IPs, and runs speed tests.
* Runs until it successfully collects `MAX_SERVERS_TESTED` servers.
* Automatically deploys the highest-rated server upon completion.
* Returns a JSON array of all successful servers.

### `POST /prepare-vpn-server`
**Moves to the next best server.**
* If you are unhappy with the current VPN server (or it drops), call this endpoint.
* It pops the *next best server* off the front of the in-memory queue.
* It injects the new configuration, forcing the VPN to restart.
* Returns the server details and how many servers remain in the queue.
* *Note: Returns a 404 if the queue is empty (meaning you need to run `/best-server` again).*

### Monitoring the Process

You can watch the magic happen in real-time by viewing the container logs.

**Watch the Handler (Controller) logs:**
```bash
docker compose -f vpn-servers-handler/docker-compose.yml logs -f vpn-servers-handler
```

**Watch the Target Application log your newly assigned IPs & Leak Tests:**
```bash
docker compose -f target-environment/docker-compose.yml logs -f target-application
```
*(You will see beautiful console output displaying your new Public IP, City, Country, assigned ISP, and the results of the automated DNS leak test whenever Gluetun rotates to a new server).*

---

## Troubleshooting

* **Container `gluetun` is crash-looping:**
  Verify that your OpenVPN credentials in `target-environment/docker-compose.yml` are strictly correct for ProtonVPN.
* **Network `shared_interop_network` not found error:**
  You likely started the `target-environment` first. Bring it down (`docker compose down`), start the `vpn-servers-handler` first, then bring the target environment back up.
* **Speed tests failing instantly / Connection Quality Checker timeouts:**
  Ensure the Gluetun container has actually established a connection. You can view its logs via `docker compose -f target-environment/docker-compose.yml logs -f gluetun`.

---

## 💎 Donation
Hopefully I managed to help you out!

[![Crypto donation button by NOWPayments](https://nowpayments.io/images/embeds/donation-button-black.svg)](https://nowpayments.io/donation?api_key=11ab7c41-d1f1-4309-8167-30b2a7aa0ddd)

## Credits & Acknowledgements

This automation pipeline stands on the shoulders of giants. A massive thank you to the developers and maintainers of the following free and open-source projects that made this possible:

- [Gluetun](https://github.com/passteque/gluetun) by [qdm12](https://github.com/qdm12) — The absolute best, most robust VPN client container out there.
- [ProtonVPN](https://protonvpn.com/) — For providing a rock-solid, privacy-respecting VPN service.
- [macvk/dnsleaktest](https://github.com/macvk/dnsleaktest) — The brilliant bash script used to reliably verify zero DNS leaks in our container.
- [ip-api.com](https://ip-api.com/) — For their incredibly fast and free IP/ISP geolocation API.
- [Flask](https://github.com/pallets/flask) — The lightweight Python framework powering our Controller and Checking APIs.
- [Cloudflare](https://www.cloudflare.com/) — For providing the stable, high-bandwidth payload endpoints used to measure our connection speeds.

## License

Maximum Freedom — This project is released under The Unlicense (Public Domain).

You are completely free to use, modify, distribute, and compile this work for personal, private, or commercial purposes without any restrictions whatsoever. Do whatever you want with it!
