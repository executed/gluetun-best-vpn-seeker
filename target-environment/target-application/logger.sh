#!/bin/bash

echo "Starting Target Application minimal IP Logger..."
LAST_IP=""

while true; do
  # Check if DNS and Internet are reachable yet.
  # If Gluetun is still connecting, this silently fails and retries in 5 seconds.
  if ! curl -sSf --max-time 5 http://ip-api.com/json/ > /dev/null 2>&1; then
    sleep 5
    continue
  fi

  # 1. Fetch IP Address Information (-f prevents HTML output on HTTP errors)
  IP_INFO=$(curl -sSf --max-time 10 http://ip-api.com/json/ || echo "{}")
  IP=$(echo "$IP_INFO" | jq -r '.query // empty')

  if [ -n "$IP" ] && [ "$IP" != "null" ] && [ "$IP" != "$LAST_IP" ]; then
    CITY=$(echo "$IP_INFO" | jq -r '.city // "Unknown"')
    COUNTRY=$(echo "$IP_INFO" | jq -r '.country // "Unknown"')
    ISP=$(echo "$IP_INFO" | jq -r '.isp // "Unknown"')

    echo "============================================="
    echo "[$(date -u)] 🌐 VPN CONNECTION ESTABLISHED/CHANGED"
    echo "  📍 Public IP: $IP"
    echo "  📍 Location : $CITY, $COUNTRY"
    echo "  📍 ISP      : $ISP"
    echo "---------------------------------------------"
    echo "  🕵️  DNS LEAK TEST RESULTS:"
    echo ""

    # Run the open-source DNS leak test script and indent the output for readability
    /app/dnsleaktest.sh | sed 's/^/    /'

    echo "============================================="

    LAST_IP=$IP
  fi

  sleep 10
done