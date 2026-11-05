FROM alpine:3.19

# Install curl and jq for minimal footprint API calls
RUN apk add --no-cache curl jq

COPY logger.sh /app/logger.sh
RUN chmod +x /app/logger.sh

CMD ["/app/logger.sh"]