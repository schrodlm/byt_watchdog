# Byt Watchdog - Flat Rental Monitor for Praha 7

## Goal

Automated tool that periodically scrapes major Czech real estate sites for rental flats in Praha 7, deduplicates results against a local database, and emails only new listings.

## Search Criteria

- **Location:** Praha 7 (and nearby neighborhoods)
- **Type:** Flats/apartments for rent (pronajem)
- **Max price:** 25 000 CZK/month
- **Schedule:** Every 3 hours (configurable via cron)

---

## Target Sites & Scraping Strategy

### 1. Sreality.cz (Seznam Realitky)

- **Method:** Public REST API (JSON), no auth required
- **Endpoint:** `https://www.sreality.cz/api/cs/v2/estates?category_main_cb=1&category_type_cb=2&locality_district_id=5007&per_page=60&czk_price_summary_order2=0|25000`
- **Pagination:** `&page=N` (up to 60 per page)
- **Key fields:** `hash_id`, `name`, `price`, `locality`, `gps`, `_links.images`, `seo`
- **Listing URL:** `https://www.sreality.cz/detail/pronajem/byt/{seo.category_sub_cb}/{seo.locality}/{hash_id}`
- **Notes:** Best source. ~78 results. Clean JSON. No anti-scraping.

### 2. Bezrealitky.cz

- **Method:** HTTP GET + parse `<script id="__NEXT_DATA__">` JSON from HTML
- **Search URL:** `https://www.bezrealitky.cz/vyhledat?currency=CZK&estateType=BYT&offerType=PRONAJEM&osm_value=Praha+7%2C+obvod+Praha+7%2C+Hlavn%C3%AD+m%C4%9Bsto+Praha%2C+Praha%2C+%C4%8Cesko&priceTo=25000&regionOsmIds=R20000064250&location=exact`
- **Pagination:** `&page=N` (15 per page)
- **Data path:** `__NEXT_DATA__` -> `props.pageProps.apolloCache` -> entries keyed `Advert:{ID}`
- **Key fields:** `id`, `uri`, `price`, `charges`, `address({"locale":"CS"})`, `surface`, `disposition`, `gps`, `mainImage` -> `Image:{id}` -> `url({"filter":"RECORD_THUMB"})`
- **Listing URL:** `https://www.bezrealitky.cz/nemovitosti-byty-domy/{uri}`
- **Notes:** ~32 results. Apollo cache has parenthesized keys (e.g. `address({"locale":"CS"})`). No JS needed. Low anti-scraping.

### 3. RE/MAX Czech

- **Method:** HTML scraping with BeautifulSoup
- **Search URL:** `https://www.remax-czech.cz/reality/vyhledavani/?hledani=2&price_to=25000&regions%5B19%5D%5B78%5D=on&types%5B4%5D=on`
- **Pagination:** `&stranka=N`
- **Key fields:** title, price, location, detail URL, image (from listing card HTML)
- **Listing URL:** `https://www.remax-czech.cz/reality/detail/{id}/{slug}`
- **Notes:** HTML scraping required. Need to determine exact CSS selectors when implementing.

---

## Architecture

```
byt_watchdog/
├── config.yaml              # All settings (price, location, email, scrapers, cron interval)
├── main.py                  # Entry point - orchestrates scrape -> dedupe -> notify
├── scrapers/
│   ├── __init__.py
│   ├── base.py              # BaseScraper ABC with Listing dataclass
│   ├── sreality.py          # Sreality REST API scraper
│   ├── bezrealitky.py       # Bezrealitky __NEXT_DATA__ scraper
│   └── remax.py             # RE/MAX HTML scraper
├── notifier.py              # Email sender (SMTP via smtplib)
├── db.py                    # JSON file-based seen-listings store
├── data/
│   └── seen.json            # Persistent DB of seen listing IDs
├── requirements.txt         # Python dependencies
├── install.sh               # pip install + crontab setup
└── email_template.html      # HTML email template for listing cards
```

### Listing Data Model

```python
@dataclass
class Listing:
    id: str              # "{source}:{site_specific_id}" e.g. "sreality:942891852"
    source: str          # "sreality" | "bezrealitky" | "remax"
    title: str           # "Pronajem bytu 2+kk 45 m2"
    price: int           # Monthly rent in CZK
    location: str        # "Vrbenskeho, Praha 7 - Holesovice"
    url: str             # Full detail page URL
    image_url: str | None
    size_m2: int | None
    disposition: str | None  # "2+kk", "1+1", etc.
```

### Flow

1. Load `config.yaml`
2. Run each enabled scraper (graceful per-scraper error handling)
3. Collect all `Listing` objects
4. Check each against `seen.json` - filter to only new ones
5. If new listings exist:
   - Add them to `seen.json` with timestamp
   - Render HTML email with listing cards
   - Send via SMTP
6. Log summary to stdout

### Email

- SMTP via Python's built-in `smtplib` + `email.mime`
- Works with Gmail (app passwords), Outlook, any SMTP provider
- HTML email with listing cards showing: image, title, price, location, link

### Config (config.yaml)

```yaml
search:
  max_price: 25000
  locations:
    - "Praha 7"

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
  smtp_user: "your-email@gmail.com"
  smtp_password: "your-app-password"
  from: "your-email@gmail.com"
  to: "your-email@gmail.com"

schedule:
  cron_interval_hours: 3
```

### Cron Setup

`install.sh` will:
1. Install Python dependencies from `requirements.txt`
2. Add a crontab entry: `0 */3 * * * cd /path/to/byt_watchdog && python3 main.py >> data/cron.log 2>&1`

---

## Key Design Decisions

1. **Python 3** - all needed libs already available on system (requests, beautifulsoup4, httpx, lxml)
2. **JSON database** - `seen.json` maps listing IDs to first-seen timestamps. Simple, no external deps
3. **Per-scraper error isolation** - if one site is down, others still run and results still get emailed
4. **Polite scraping** - 1-2 second delays between requests, reasonable User-Agent
5. **Configurable everything** - sites, price, email, cron interval all in one YAML file

## Implementation Order

1. Project skeleton + config
2. `db.py` - JSON seen-listings store
3. `scrapers/base.py` - BaseScraper ABC + Listing dataclass
4. `scrapers/sreality.py` - cleanest API, implement first
5. `scrapers/bezrealitky.py` - __NEXT_DATA__ parsing
6. `scrapers/remax.py` - HTML scraping
7. `notifier.py` + `email_template.html` - email sender
8. `main.py` - orchestrator
9. `install.sh` - deps + cron
