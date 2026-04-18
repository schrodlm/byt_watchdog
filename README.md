# RentCzecher

Multi-profile real estate monitor for the Czech Republic. Scrapes major Czech real estate sites, deduplicates, scores, and emails new listings - supports any combination of location, property type, and offer type.

## Features

- **Multi-profile**: Run independent searches in parallel (e.g., flats in Praha 7 + houses in Domažlice)
- **3 sources**: Sreality.cz (API), Bezrealitky.cz (SSR), RE/MAX Czech (HTML)
- **Any property type**: Flats, houses, cottages, land, agricultural estates
- **Any offer type**: Rent or sale
- **Any location**: Configurable per profile via district IDs and OSM region IDs
- **Smart scoring**: 0-100 score with configurable weights (price/m2, disposition, size, land area, neighborhood, total price)
- **Price drop alerts**: Detects when a listing's price decreases
- **Disappeared listings**: Tracks when properties are removed
- **Cross-source dedup**: Detects same property listed on multiple sites
- **Prague tram enrichment**: Nearest tram stop + lines (for Prague profiles)
- **Google Maps links**: One-click map view per listing
- **Per-profile DB**: Each profile has its own `seen-{id}.json`
- **Per-profile recipients**: Different email recipients per search

## Setup

```bash
# Install (creates venv, installs deps, sets up cron)
./install.sh

# Or manually:
python3 -m venv venv
venv/bin/pip install -r requirements.txt

# Configure
cp config.example.yaml config.yaml
# Edit config.yaml

# Test
venv/bin/python main.py --dry-run
venv/bin/python main.py --dry-run --profile praha7-byty

# Run for real
venv/bin/python main.py
```

## Config

The config has a shared `email` section and multiple `profiles`:

```yaml
email:
  smtp_host: "smtp.gmail.com"
  smtp_port: 587
  smtp_user: "you@gmail.com"
  smtp_password: "your-app-password"
  from: "you@gmail.com"

profiles:
  # Flat rentals in Praha 7
  praha7-byty:
    name: "Praha 7 - byty k pronajmu"
    to: ["you@gmail.com", "partner@gmail.com"]
    search:
      offer_type: rent
      estate_type: flat
      max_price: 25000
    scrapers:
      sreality:
        enabled: true
        category_main_cb: 1       # 1=byty
        category_type_cb: 2       # 2=pronajem
        locality_district_id: 5007
      bezrealitky:
        enabled: true
        estate_type: "BYT"
        offer_type: "PRONAJEM"
        region_osm_id: "R20000064250"
      remax:
        enabled: true
        search_url: "https://www.remax-czech.cz/reality/vyhledavani/?hledani=2&..."
    scoring:
      price_per_m2_weight: 40
      disposition_weight: 30
      preferred_dispositions: ["2+kk", "2+1"]
      size_weight: 15
      ideal_size_m2: 55
      neighborhood_weight: 15
      preferred_neighborhoods: ["Holešovice", "Letná"]
    tram_enrichment: true

  # Houses for sale in Domažlice district
  domazlice-domy:
    name: "Domažlicko - domy a chalupy"
    to: ["father@gmail.com"]
    search:
      offer_type: sale
      estate_type: house
      max_price: 5000000
      min_land_m2: 500
    scrapers:
      sreality:
        enabled: true
        category_main_cb: 2       # 2=domy
        category_type_cb: 1       # 1=prodej
        locality_district_id: 8   # Domažlický okres
        category_sub_cb: "37|43|44"
      bezrealitky:
        enabled: true
        estate_type: "DUM"
        offer_type: "PRODEJ"
        region_osm_id: "R441864"
      remax:
        enabled: true
        search_url: "https://www.remax-czech.cz/reality/vyhledavani/?hledani=1&types%5B6%5D=on&types%5B10%5D=on&regions%5B43%5D%5B3402%5D=on"
    scoring:
      land_weight: 40
      ideal_land_m2: 2000
      price_weight: 30
      max_good_price: 3000000
      size_weight: 30
      ideal_size_m2: 150
```

See `config.example.yaml` for a complete reference with all options.

## Adding a new profile

1. Choose scraper parameters:
   - **Sreality**: `category_main_cb` (1=byty, 2=domy, 3=pozemky), `category_type_cb` (1=prodej, 2=pronajem), `locality_district_id` (find via sreality.cz URL)
   - **Bezrealitky**: `estate_type` (BYT/DUM/POZEMEK/REKREACNI_OBJEKT), `offer_type` (PRODEJ/PRONAJEM), `region_osm_id` (find via OpenStreetMap)
   - **RE/MAX**: Build a `search_url` on remax-czech.cz and paste it
2. Configure scoring weights for what matters (price/m2 for rentals, land_area for houses, etc.)
3. Set the `to` recipients

## CLI

```bash
python3 main.py                          # Run all profiles
python3 main.py --profile praha7-byty    # Run one profile
python3 main.py --dry-run                # No email, no DB changes
python3 main.py --dry-run --profile X    # Test one profile
```

## Logs

```bash
tail -f data/cron.log
```
