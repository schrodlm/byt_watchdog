# Byt Watchdog

Automated monitor for rental flats in Praha 7. Scrapes major Czech real estate sites every few hours and emails you only the new listings.

## Sources

- **Sreality.cz** - REST API (JSON)
- **Bezrealitky.cz** - SSR data extraction
- **RE/MAX Czech** - HTML scraping

## Setup

```bash
# Install dependencies
pip3 install -r requirements.txt

# Create your config
cp config.example.yaml config.yaml
# Edit config.yaml with your email SMTP settings

# Test run
python3 main.py

# Install cron job (default: every 3 hours)
./install.sh

# Or with custom interval (every 6 hours)
./install.sh 6
```

## Config

Edit `config.yaml`:

```yaml
search:
  max_price: 25000          # Max rent in CZK/month

scrapers:
  sreality:
    enabled: true
  bezrealitky:
    enabled: true
  remax:
    enabled: true

email:
  smtp_host: "smtp.gmail.com"
  smtp_port: 587
  smtp_user: "you@gmail.com"
  smtp_password: "your-app-password"  # Gmail: use App Password
  from: "you@gmail.com"
  to: "you@gmail.com"

schedule:
  cron_interval_hours: 3
```

### Gmail App Password

1. Enable 2FA on your Google account
2. Go to https://myaccount.google.com/apppasswords
3. Generate an app password for "Mail"
4. Use that password in `smtp_password`

## How it works

1. Runs each enabled scraper to collect rental listings
2. Compares against `data/seen.json` to find only new ones
3. Sends an HTML email with listing cards (image, price, size, link)
4. Marks listings as seen so you never get duplicates

## Logs

```bash
tail -f data/cron.log
```
