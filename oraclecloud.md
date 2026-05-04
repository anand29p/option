# Oracle Cloud Always Free VM Setup

Use this guide to host the paper-trading bot away from the laptop.

Official links:

- Oracle Cloud Free Tier: https://www.oracle.com/cloud/free/
- Oracle Cloud Free Tier FAQ: https://www.oracle.com/cloud/free/faq/
- Always Free resources: https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm


## Recommended Hosting Plan

Use an Oracle Cloud Always Free VM for the bot runner and dashboard.

Preferred shape:

- Ampere A1 Flex, Always Free eligible
- Start with 1 OCPU and 6 GB RAM

Fallback shape:

- VM.Standard.E2.1.Micro, Always Free eligible, weaker but usually enough for a small paper bot

Important notes:

- Always Free resources are tied to the home region selected at signup.
- Oracle may show "out of host capacity" for Always Free shapes. If this happens, try another availability domain or retry later.
- Keep this paper-only until the bot has passed longer backtests and forward paper observation.


## Create The VM

1. Open https://www.oracle.com/cloud/free/
2. Create an Oracle Cloud Free Tier account.
3. Choose the home region carefully.
4. Add payment card for verification.
5. In Oracle Cloud Console, go to:

   Compute -> Instances -> Create instance

6. Name the instance:

   option-bot-paper

7. Image:

   Ubuntu 22.04 or Ubuntu 24.04

8. Shape:

   Prefer Ampere A1 Flex, Always Free eligible.

9. Networking:

   Use/create the default VCN and assign a public IPv4.

10. SSH key:

   Generate a key pair in Oracle Cloud and download the private key.


## Connect From Windows

From PowerShell:

```powershell
ssh -i C:\path\to\oracle_option_bot.key ubuntu@YOUR_VM_PUBLIC_IP
```

If Windows complains about key permissions, run:

```powershell
icacls C:\path\to\oracle_option_bot.key /inheritance:r
icacls C:\path\to\oracle_option_bot.key /grant:r "$($env:USERNAME):(R)"
```


## Install Runtime On VM

```bash
sudo apt update
sudo apt upgrade -y
sudo apt install -y git python3 python3-venv python3-pip
```

Check Python:

```bash
python3 --version
```


## Upload Or Clone Project

If using GitHub:

```bash
git clone YOUR_REPO_URL option
cd option
```

If copying directly from Windows:

```powershell
scp -i C:\path\to\oracle_option_bot.key -r C:\genai\option ubuntu@YOUR_VM_PUBLIC_IP:/home/ubuntu/option
```


## Create Python Environment

On the VM:

```bash
cd ~/option
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
python -c "import nltk; nltk.download('vader_lexicon')"
```


## Configure Credentials

```bash
cp .env.example .env
nano .env
```

Set:

```env
MODE=paper
PAPER_CAPITAL=100000
MAX_CAPITAL_PER_TRADE=10000
ACTIVE_STRATEGY_ALLOWLIST=FINNIFTY:RSIDivergence
SHADOW_SIGNAL_LOG=true
DHAN_CLIENT_ID=your_client_id
DHAN_ACCESS_TOKEN=your_access_token
```


## Run Dashboard

```bash
cd ~/option
source .venv/bin/activate
python main.py --dashboard
```

Open:

```text
http://YOUR_VM_PUBLIC_IP:5000
```


## Run Paper Bot

```bash
cd ~/option
source .venv/bin/activate
python main.py --mode paper
```

The dashboard remains:

```text
http://YOUR_VM_PUBLIC_IP:5000
```


## Firewall / Security

For a quick test, open TCP port 5000 in the Oracle subnet security list.

Safer options for later:

- Tailscale private network
- Cloudflare Tunnel
- Nginx reverse proxy with basic auth

Avoid exposing the dashboard publicly without protection.


## Keep Bot Running With systemd

Create a service:

```bash
sudo nano /etc/systemd/system/option-bot.service
```

Paste:

```ini
[Unit]
Description=Option Paper Trading Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/option
Environment=PYTHONUNBUFFERED=1
ExecStart=/home/ubuntu/option/.venv/bin/python main.py --mode paper
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable it:

```bash
sudo systemctl daemon-reload
sudo systemctl enable option-bot
sudo systemctl start option-bot
sudo systemctl status option-bot
```

View logs:

```bash
journalctl -u option-bot -f
```


## Stop Bot

```bash
sudo systemctl stop option-bot
```


## Update Bot Code

```bash
cd ~/option
git pull
source .venv/bin/activate
pip install -r requirements.txt
sudo systemctl restart option-bot
```
