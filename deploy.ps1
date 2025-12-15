# PowerShell Deployment Script for Kaiten Bot
# Run with: powershell -ExecutionPolicy Bypass -File deploy.ps1

$server = "155.212.222.89"
$username = "root"
$password = "XvUA8!1nuIV"
$deployDir = "/root/kaiten-bot"

Write-Host "=== Kaiten Bot Deployment ===" -ForegroundColor Cyan
Write-Host ""

# Function to run SSH commands using plink
function Invoke-SSHCommand {
    param(
        [string]$Command,
        [string]$Description = ""
    )

    if ($Description) {
        Write-Host "`n>>> $Description" -ForegroundColor Yellow
    }

    $output = echo y | plink -ssh -batch -pw $password "${username}@${server}" $Command 2>&1
    Write-Host $output
    return $output
}

# Function to transfer files using pscp
function Copy-FileToServer {
    param(
        [string]$LocalFile,
        [string]$RemotePath
    )

    Write-Host "Uploading $LocalFile..." -ForegroundColor Yellow
    $output = echo y | pscp -pw $password $LocalFile "${username}@${server}:${RemotePath}" 2>&1
    Write-Host $output
}

try {
    # Step 1: Check environment
    Write-Host "[1/7] Checking server environment..." -ForegroundColor Green
    Invoke-SSHCommand "python3 --version; pip3 --version; uname -a"

    # Step 2: Create directory
    Write-Host "`n[2/7] Creating deployment directory..." -ForegroundColor Green
    Invoke-SSHCommand "mkdir -p $deployDir" "Creating directory"

    # Step 3: Transfer files
    Write-Host "`n[3/7] Transferring files..." -ForegroundColor Green
    Copy-FileToServer "main.py" "$deployDir/main.py"
    Copy-FileToServer "requirements.txt" "$deployDir/requirements.txt"

    # Step 4: Create .env file
    Write-Host "`n[4/7] Creating .env file..." -ForegroundColor Green
    Write-Host "NOTE: Create .env file manually with your API keys:" -ForegroundColor Yellow
    Write-Host "ssh ${username}@${server}"
    Write-Host "cat > $deployDir/.env << 'EOF'"
    Write-Host "TELEGRAM_BOT_TOKEN=your_token_here"
    Write-Host "OPENAI_API_KEY=your_api_key_here"
    Write-Host "KAITEN_API_KEY=your_kaiten_key_here"
    Write-Host "EOF"
    Write-Host "chmod 600 $deployDir/.env"
    Read-Host "Press Enter when .env file has been created on server"

    # Step 5: Install dependencies
    Write-Host "`n[5/7] Installing Python dependencies..." -ForegroundColor Green
    Write-Host "This may take a few minutes..." -ForegroundColor Yellow
    $installCmd = "cd $deployDir && python3 -m venv venv && source venv/bin/activate && pip install --upgrade pip && pip install -r requirements.txt && echo 'Dependencies installed successfully'"
    Invoke-SSHCommand $installCmd "Installing dependencies"

    # Step 6: Create systemd service
    Write-Host "`n[6/7] Creating systemd service..." -ForegroundColor Green
    $serviceCmd = @"
cat > /etc/systemd/system/kaiten-bot.service << 'SERVICEEOF'
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
SERVICEEOF
systemctl daemon-reload
systemctl enable kaiten-bot.service
"@
    Invoke-SSHCommand $serviceCmd "Creating service"

    # Step 7: Start the bot
    Write-Host "`n[7/7] Starting the bot..." -ForegroundColor Green
    Invoke-SSHCommand "systemctl stop kaiten-bot.service 2>/dev/null || true"
    Start-Sleep -Seconds 2
    Invoke-SSHCommand "systemctl start kaiten-bot.service"
    Start-Sleep -Seconds 3

    # Check status
    Write-Host "`n=== Checking bot status ===" -ForegroundColor Cyan
    $status = Invoke-SSHCommand "systemctl status kaiten-bot.service --no-pager -l"

    if ($status -match "active \(running\)") {
        Write-Host "`n SUCCESS! Bot is running on the server." -ForegroundColor Green
    } else {
        Write-Host "`n WARNING: Bot may not be running. Check logs." -ForegroundColor Yellow
    }

    Write-Host "`n=== Useful Commands ===" -ForegroundColor Cyan
    Write-Host "View logs:    plink -ssh -pw $password ${username}@${server} 'journalctl -u kaiten-bot -f'"
    Write-Host "Restart bot:  plink -ssh -pw $password ${username}@${server} 'systemctl restart kaiten-bot'"
    Write-Host "Stop bot:     plink -ssh -pw $password ${username}@${server} 'systemctl stop kaiten-bot'"
    Write-Host "Check status: plink -ssh -pw $password ${username}@${server} 'systemctl status kaiten-bot'"

} catch {
    Write-Host "`n DEPLOYMENT FAILED!" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}
