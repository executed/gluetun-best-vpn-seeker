#!/bin/sh

echo "Starting Target Application minimal IP Logger..."
LAST_IP=""

while true; do
  # 1. Fetch IP Address Information (Using ip-api, generous rate limits and free)
  IP_INFO=$(curl -s --max-time 10 http://ip-api.com/json/ || echo "{}")
  IP=$(echo "$IP_INFO" | jq -r '.query // empty')

  if [ -n "$IP" ] && [ "$IP" != "null" ] && [ "$IP" != "$LAST_IP" ]; then
    CITY=$(echo "$IP_INFO" | jq -r '.city // "Unknown"')
    COUNTRY=$(echo "$IP_INFO" | jq -r '.country // "Unknown"')
    ISP=$(echo "$IP_INFO" | jq -r '.isp // "Unknown"')

    echo "============================================="
    echo "[$(date -u)] 🌐 VPN CONNECTION ACTIVE OR CHANGED"
    echo "  -> New Public IP: $IP"
    echo "  -> Location: $CITY, $COUNTRY"
    echo "  -> Assigned ISP: $ISP"
    echo "============================================="

    LAST_IP=$IP
  fi

  sleep 10
done