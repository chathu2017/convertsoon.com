#!/bin/bash

# Services List (Updated for UAT)
SERVICES=("redis-server" "convertsoon.web" "convertsoon-worker-uat" "nginx")

echo "=========================================="
echo "📊 UAT SERVICE STATUS REPORT"
echo "=========================================="
printf "%-30s %-15s\n" "SERVICE NAME" "STATUS"
echo "------------------------------------------"

for service in "${SERVICES[@]}"
do
    # Check status
    STATUS=$(systemctl is-active $service)

    if [ "$STATUS" == "active" ]; then
        # Green for Active
        printf "%-30s \033[0;32m%-15s\033[0m\n" "$service" "RUNNING"
    else
        # Red for Inactive/Failed
        printf "%-30s \033[0;31m%-15s\033[0m\n" "$service" "STOPPED/ERROR"
    fi
done
echo "=========================================="

