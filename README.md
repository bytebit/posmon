# Uniswap V3 Position Monitor (Arbitrum)

This script checks a Uniswap V3 position on Arbitrum and emails you when the position goes out of range (or re-enters range).

## Setup

1. Install dependencies:

```bash
python -m venv .venv
. .venv/bin/activate  # Windows PowerShell: .\\.venv\\Scripts\\Activate.ps1
pip install -r requirements.txt
```

2. Create a `.env` file (copy from `.env.example`) and fill in:

- `ARB_RPC_URL` (your Alchemy URL)
- `POSITION_ID` for a single position, or `POSITION_IDS` for multiple (comma-separated)
- SMTP settings
- `EMAIL_FROM` / `EMAIL_TO` (comma-separated for multiple recipients)

### Daily pool digest (11:00 & 23:00)

The script can email a filtered pool list twice a day using DefiLlama yields data.

Env vars:

- `ASSET_DIGEST_ENABLED=true`
- `ASSET_DIGEST_TIMES=11:00,23:00`
- `ASSET_DIGEST_TOP_N=10`
- `LOCAL_TZ=Asia/Shanghai`

## Run

```bash
python monitor_position.py
```

Single check (exit after one run):

```bash
python monitor_position.py --once
```

The script writes a `state.json` file with the last observed status and errors.

## Notes

- Range check rule: `tickLower <= currentTick < tickUpper`
- Emails are sent only on status changes unless `ALERT_ON_START=true` (then one email per start).
- Console output includes token symbols, fee tier, current tick, and range.

## WSL systemd service (Ubuntu)

1. Enable systemd in WSL (one-time):

```bash
sudo sh -c 'printf "[boot]\nsystemd=true\n" > /etc/wsl.conf'
```

Then from Windows, restart WSL:

```powershell
wsl --shutdown
```

2. Edit the service file `uniswap-posmon.service`:

- Replace `User=REPLACE_WITH_WSL_USERNAME` with your WSL username.
- If your repo path is different, update `WorkingDirectory`, `EnvironmentFile`, and `ExecStart`.

3. Install and start the service:

```bash
sudo cp /mnt/d/dev_projects/posmon/uniswap-posmon.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now uniswap-posmon.service
```

4. Check status and logs:

```bash
sudo systemctl status uniswap-posmon.service
journalctl -u uniswap-posmon.service -f
```

## Debian systemd service (non-WSL)

1. Copy the service file to your server and edit paths:

- Update `WorkingDirectory`, `EnvironmentFile`, and `ExecStart` to your Linux path.
- Replace `User=REPLACE_WITH_WSL_USERNAME` with your Linux username.

2. Install and start:

```bash
sudo cp /path/to/uniswap-posmon.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now uniswap-posmon.service
```

3. Check status and logs:

```bash
sudo systemctl status uniswap-posmon.service
journalctl -u uniswap-posmon.service -f
```

## Ubuntu systemd service (non-WSL)

1. Copy the service file to your server and edit paths:

- Update `WorkingDirectory`, `EnvironmentFile`, and `ExecStart` to your Linux path.
- Replace `User=REPLACE_WITH_WSL_USERNAME` with your Linux username.

2. Install and start:

```bash
sudo cp /path/to/uniswap-posmon.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now uniswap-posmon.service
```

3. Check status and logs:

```bash
sudo systemctl status uniswap-posmon.service
journalctl -u uniswap-posmon.service -f
```
