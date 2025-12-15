#!/bin/bash
# Deployment script for Kaiten Bot on Beget server
# Run this script from your local machine after SSH connection

set -e

echo "=== Kaiten Bot Deployment Script ==="
echo ""

# Configuration
SERVER_IP="155.212.222.89"
SERVER_USER="root"
DEPLOY_DIR="/root/kaiten-bot"
APP_NAME="kaiten-bot"

echo "Step 1: Checking Python installation on server..."
ssh ${SERVER_USER}@${SERVER_IP} << 'ENDSSH'
    # Check Python version
    if command -v python3 &> /dev/null; then
        PYTHON_VERSION=$(python3 --version)
        echo "✓ Found: $PYTHON_VERSION"
    else
        echo "✗ Python3 not found. Installing..."
        # For Debian/Ubuntu
        if command -v apt-get &> /dev/null; then
            apt-get update
            apt-get install -y python3 python3-pip python3-venv
        # For CentOS/RHEL
        elif command -v yum &> /dev/null; then
            yum install -y python3 python3-pip
        fi
    fi

    # Check pip
    if command -v pip3 &> /dev/null; then
        echo "✓ pip3 is installed"
    else
        echo "Installing pip3..."
        python3 -m ensurepip --upgrade
    fi
ENDSSH

echo ""
echo "Step 2: Creating deployment directory..."
ssh ${SERVER_USER}@${SERVER_IP} "mkdir -p ${DEPLOY_DIR}"

echo ""
echo "Step 3: Transferring files to server..."
scp main.py requirements.txt ${SERVER_USER}@${SERVER_IP}:${DEPLOY_DIR}/

echo ""
echo "Step 4: Creating .env file on server..."
echo ""
echo "NOTE: You need to manually create .env file on server with your API keys:"
echo "ssh ${SERVER_USER}@${SERVER_IP}"
echo "cat > ${DEPLOY_DIR}/.env << 'EOF'"
echo "TELEGRAM_BOT_TOKEN=your_token_here"
echo "OPENAI_API_KEY=your_api_key_here"
echo "KAITEN_API_KEY=your_kaiten_key_here"
echo "EOF"
echo "chmod 600 ${DEPLOY_DIR}/.env"
echo ""
echo "Press Enter when .env file has been created on server..."
read

echo ""
echo "Step 5: Installing Python dependencies..."
ssh ${SERVER_USER}@${SERVER_IP} << 'ENDSSH'
    cd /root/kaiten-bot

    # Create virtual environment
    python3 -m venv venv
    source venv/bin/activate

    # Upgrade pip
    pip install --upgrade pip

    # Install dependencies
    pip install -r requirements.txt

    echo "✓ Dependencies installed"
ENDSSH

echo ""
echo "Step 6: Creating systemd service..."
ssh ${SERVER_USER}@${SERVER_IP} << 'ENDSSH'
    cat > /etc/systemd/system/kaiten-bot.service << 'EOF'
[Unit]
Description=Kaiten Telegram Bot
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/root/kaiten-bot
Environment="PATH=/root/kaiten-bot/venv/bin"
ExecStart=/root/kaiten-bot/venv/bin/python3 /root/kaiten-bot/main.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

    # Reload systemd
    systemctl daemon-reload
    systemctl enable kaiten-bot.service

    echo "✓ Systemd service created"
ENDSSH

echo ""
echo "Step 7: Starting the bot..."
ssh ${SERVER_USER}@${SERVER_IP} << 'ENDSSH'
    # Stop if already running
    systemctl stop kaiten-bot.service 2>/dev/null || true

    # Start the service
    systemctl start kaiten-bot.service

    # Check status
    sleep 2
    systemctl status kaiten-bot.service --no-pager

    echo ""
    echo "✓ Bot service started"
ENDSSH

echo ""
echo "=== Deployment Complete ==="
echo ""
echo "Useful commands:"
echo "  Check status:  ssh ${SERVER_USER}@${SERVER_IP} 'systemctl status kaiten-bot'"
echo "  View logs:     ssh ${SERVER_USER}@${SERVER_IP} 'journalctl -u kaiten-bot -f'"
echo "  Restart bot:   ssh ${SERVER_USER}@${SERVER_IP} 'systemctl restart kaiten-bot'"
echo "  Stop bot:      ssh ${SERVER_USER}@${SERVER_IP} 'systemctl stop kaiten-bot'"
echo ""
