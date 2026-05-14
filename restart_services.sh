#!/bin/bash

# Define Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${RED}🛑 STOPPING UAT Services...${NC}"

# 1. Stop Traffic First
echo -n "   Stopping Nginx... "
sudo systemctl stop nginx
echo "Done."

# 2. Stop UAT Worker (Name from your file list)
echo -n "   Stopping UAT Worker... "
sudo systemctl stop convertsoon-worker-uat
echo "Done."

# 3. Stop Web App (Name from your file list)
echo -n "   Stopping Web App... "
sudo systemctl stop convertsoon.web
echo "Done."

# 4. Stop Database
echo -n "   Stopping Redis... "
sudo systemctl stop redis-server
echo "Done."

echo "----------------------------------------"
echo "⏳ Waiting 2 seconds..."
sleep 2
echo "----------------------------------------"

echo -e "${GREEN}🚀 STARTING UAT Services...${NC}"

# 1. Start Redis
echo -n "   1. Starting Redis... "
sudo systemctl start redis-server
sleep 1
echo -e "${GREEN}OK${NC}"

# 2. Start Web App
echo -n "   2. Starting Web App (convertsoon.web)... "
sudo systemctl start convertsoon.web
sleep 2
echo -e "${GREEN}OK${NC}"

# 3. Start UAT Worker
echo -n "   3. Starting UAT Worker... "
sudo systemctl start convertsoon-worker-uat
sleep 1
echo -e "${GREEN}OK${NC}"

# 4. Start Nginx
echo -n "   4. Starting Nginx... "
sudo systemctl start nginx
echo -e "${GREEN}OK${NC}"

echo "----------------------------------------"
echo -e "${GREEN}✅ UAT Restart Complete!${NC}"
echo "----------------------------------------"

# Optional: Check Status
# sudo systemctl status convertsoon.web --no-pager

