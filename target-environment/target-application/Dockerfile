FROM alpine:3.24.3

# Install curl, jq, bash, and iputils (needed for the DNS leak test ping)
RUN apk add --no-cache curl jq bash iputils

WORKDIR /app

# Download the popular macvk/dnsleaktest script
RUN curl -sS https://raw.githubusercontent.com/macvk/dnsleaktest/master/dnsleaktest.sh -o /app/dnsleaktest.sh && \
    chmod +x /app/dnsleaktest.sh

COPY logger.sh /app/logger.sh
RUN chmod +x /app/logger.sh

CMD ["/app/logger.sh"]