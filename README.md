# Byt Watchdog

Automated monitor for rental flats in Praha 7. Scrapes major Czech real estate sites every few hours and emails you only the new listings, ranked by a smart score.

## Features

- **3 sources**: Sreality.cz (API), Bezrealitky.cz (SSR), RE/MAX Czech (HTML)
- **Smart scoring**: Ranks listings 0-100 based on price/m2, disposition preference, size, and neighborhood
- **Price drop alerts**: Detects when a listing's price decreases
- **Disappeared listings**: Tracks when flats are removed (rented out)
- **Cross-source dedup**: Detects same flat listed on multiple sites
- **Metro distance**: Shows nearest metro station and walking distance
- **Price/m2**: Calculated and shown in every listing card
- **Google Maps links**: One-click map view for each listing
- **Filters**: By disposition (2+kk, 2+1, etc.), min/max price, min size
- **HTML emails**: Sorted by score with image cards, sent to multiple recipients

## Setup

```bash
# Install dependencies
pip3 install -r requirements.txt

# Create your config
cp config.example.yaml config.yaml
# Edit config.yaml with your email SMTP settings and preferences

# Test run (no email, no DB changes)
python3 main.py --dry-run

# Real run
python3 main.py

# Install cron job (default: every 3 hours)
./install.sh

# Custom interval (every 6 hours)
./install.sh 6
```

## Config

```yaml
search:
  min_price: 0
  max_price: 25000
  dispositions: []            # e.g. ["2+kk", "2+1"] - empty means all
  min_size_m2: 0              # 0 means no minimum

scoring:
  price_per_m2_weight: 40
  disposition_weight: 30
  preferred_dispositions:
    - "2+kk"
    - "2+1"
    - "3+kk"
  size_weight: 15
  ideal_size_m2: 55
  neighborhood_weight: 15
  preferred_neighborhoods:
    - "Holešovice"
    - "Letná"
    - "Bubeneč"

email:
  smtp_host: "smtp.gmail.com"
  smtp_port: 587
  smtp_user: "you@gmail.com"
  smtp_password: "your-app-password"
  from: "you@gmail.com"
  to:
    - "you@gmail.com"
    - "friend@example.com"

schedule:
  cron_interval_hours: 3
```

### Gmail App Password

1. Enable 2FA on your Google account
2. Go to https://myaccount.google.com/apppasswords
3. Generate an app password for "Mail"
4. Use that 16-char password in `smtp_password`

## How it works

1. Scrapes all enabled sources for Praha 7 rentals
2. Applies filters (disposition, size, price range)
3. Enriches with metro distances (GPS-based)
4. Deduplicates across sources (same flat on Sreality + Bezrealitky)
5. Computes smart score for each listing
6. Detects price drops vs. previous runs
7. Detects disappeared listings (no longer on any site)
8. Sends HTML email sorted by score (best first)
9. Stores full listing data in `data/seen.json`

## Logs

```bash
tail -f data/cron.log
```
