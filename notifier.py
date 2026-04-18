import smtplib
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formatdate, make_msgid
from html import escape
from urllib.parse import quote as url_quote

from scrapers.base import Listing

NBSP = "\u00a0"


def _safe_url(url: str) -> str:
    if url and url.startswith(("https://", "http://")):
        return escape(url, quote=True)
    return "#"


def _format_price(price: int, is_rent: bool) -> str:
    formatted = f"{price:,}".replace(",", NBSP)
    if is_rent:
        return f"{formatted}{NBSP}Kč/měsíc"
    return f"{formatted}{NBSP}Kč"


def _format_price_plain(price: int, is_rent: bool) -> str:
    formatted = f"{price:,}".replace(",", " ")
    if is_rent:
        return f"{formatted} Kč/měsíc"
    return f"{formatted} Kč"


def _score_badge(listing: Listing) -> str:
    """Render score as a simple colored number - no marketing words."""
    if listing.score <= 0:
        return ""
    if listing.score >= 70:
        color = "#1a8917"
    elif listing.score >= 40:
        color = "#e8a317"
    else:
        color = "#888888"
    return (
        f'<span style="display:inline-block;padding:3px 8px;border-radius:4px;'
        f'font-size:12px;font-weight:700;background:{color};color:#ffffff;'
        f'margin-right:4px;">{listing.score}%</span>'
    )


def _market_chip(listing: Listing) -> str:
    """Render price percentile + median as a factual chip."""
    if listing.price_percentile is None or not listing.size_m2:
        return ""
    text = f"levnější než {listing.price_percentile}% podobných (~{listing.size_m2}{NBSP}m²)"
    if listing.market_median:
        median_str = f"{listing.market_median:,}".replace(",", NBSP)
        text += f" · medián {median_str}{NBSP}Kč"
    return (
        f'<span style="display:inline-block;padding:2px 8px;margin:2px 2px;'
        f'background:#e8f5e9;border-radius:12px;font-size:12px;color:#2e7d32;'
        f'white-space:nowrap;">{text}</span>'
    )


def _maps_link(listing: Listing) -> str:
    if listing.location:
        query = url_quote(f"{listing.location}, Praha, Česko")
        url = f"https://maps.google.com/?q={query}"
        return (
            f'<a href="{escape(url, quote=True)}" style="display:inline-block;'
            f'padding:6px 12px;margin-right:6px;font-size:12px;color:#1a73e8;'
            f'text-decoration:none;border:1px solid #dadce0;border-radius:4px;">'
            f'Mapa</a>'
        )
    elif listing.lat is not None and listing.lon is not None:
        url = f"https://maps.google.com/?q={listing.lat},{listing.lon}"
        return (
            f'<a href="{escape(url, quote=True)}" style="display:inline-block;'
            f'padding:6px 12px;margin-right:6px;font-size:12px;color:#1a73e8;'
            f'text-decoration:none;border:1px solid #dadce0;border-radius:4px;">'
            f'Mapa</a>'
        )
    return ""


def _render_card(listing: Listing, is_rent: bool) -> str:
    title = escape(listing.title)
    url = _safe_url(listing.url)
    disposition = escape(listing.disposition) if listing.disposition else ""

    badge_colors = {
        "sreality": ("background:#e8f0fe;color:#1a73e8;", "Sreality"),
        "bezrealitky": ("background:#fce8e6;color:#d93025;", "Bezrealitky"),
        "remax": ("background:#e6f4ea;color:#1e8e3e;", "RE/MAX"),
        "idnes": ("background:#fff3e0;color:#e65100;", "Idnes"),
    }
    badge_style, badge_label = badge_colors.get(
        listing.source, ("background:#eeeeee;color:#333333;", escape(listing.source)))

    # Image
    img_html = ""
    if listing.image_url:
        img_url = _safe_url(listing.image_url)
        alt_text = escape(f"{listing.title} - {listing.disposition or ''} {listing.location}".strip(" -"))
        img_html = (
            f'<div style="width:100%;background:#f0f0f0;">'
            f'<img src="{img_url}" alt="{alt_text}" '
            f'style="width:100%;height:auto;display:block;border:0;" />'
            f'</div>'
        )

    # Hero numbers: price on left, size/disposition on right (table for Outlook compat)
    price_str = _format_price(listing.price, is_rent)
    right_parts = []
    if disposition:
        right_parts.append(disposition)
    if listing.size_m2:
        right_parts.append(f"{listing.size_m2}{NBSP}m²")
    if not is_rent and listing.land_m2:
        land_str = f"{listing.land_m2:,}".replace(",", NBSP)
        right_parts.append(f"pozemek {land_str}{NBSP}m²")
    right_col = " · ".join(right_parts)

    # Total cost for rentals (rent + charges)
    price_detail = ""
    if listing.charges and is_rent:
        total = listing.price + listing.charges
        total_str = _format_price(total, is_rent)
        charges_str = f"{listing.charges:,}".replace(",", NBSP)
        price_str = total_str
        price_detail = (
            f'<div style="font-size:12px;color:#888888;margin-bottom:4px;">'
            f'nájemné {_format_price(listing.price, True)} + poplatky {charges_str}{NBSP}Kč</div>'
        )

    # Price drop
    drop_html = ""
    if listing.price_drop_from:
        old_price = _format_price(listing.price_drop_from, is_rent)
        savings = listing.price_drop_from - listing.price
        savings_str = f"{savings:,}".replace(",", NBSP)
        drop_html = (
            f'<div style="font-size:13px;color:#d93025;font-weight:600;margin-bottom:4px;">'
            f'SLEVA z {old_price} (−{savings_str}{NBSP}Kč)</div>'
        )

    # Detail chips (pill-style tags that wrap on mobile)
    chips = []
    if listing.size_m2 and is_rent:
        ppm2 = round(listing.price / listing.size_m2)
        chips.append(f"{ppm2}{NBSP}Kč/m²")
    if listing.location:
        chips.append(escape(listing.location))
    if listing.nearest_stop and listing.stop_distance_m is not None:
        if listing.stop_distance_m < 1000:
            chips.append(f"{escape(listing.nearest_stop)} ({listing.stop_distance_m}{NBSP}m)")
        else:
            chips.append(f"{escape(listing.nearest_stop)} ({listing.stop_distance_m / 1000:.1f}{NBSP}km)")

    chips_html = " ".join(
        f'<span style="display:inline-block;padding:2px 8px;margin:2px 2px;'
        f'background:#f5f5f5;border-radius:12px;font-size:12px;color:#555555;'
        f'white-space:nowrap;">{c}</span>'
        for c in chips
    )

    # Cross-source
    cross_html = ""
    if listing.cross_source:
        sites = ", ".join(listing.cross_source)
        cross_html = (
            f'<span style="display:inline-block;padding:2px 8px;margin:2px 2px;'
            f'background:#f0f0f0;border-radius:12px;font-size:11px;color:#555555;">'
            f'také na: {escape(sites)}</span>'
        )

    # Score badge + market data + source badge
    score_html = _score_badge(listing)
    market_html = _market_chip(listing)
    source_badge = (
        f'<span style="display:inline-block;padding:2px 8px;border-radius:4px;'
        f'font-size:11px;font-weight:600;text-transform:uppercase;{badge_style}">'
        f'{badge_label}</span>'
    )

    # CTA button + map button
    cta_html = (
        f'<a href="{url}" style="display:inline-block;padding:6px 12px;'
        f'margin-right:6px;background:#1a73e8;color:#ffffff;text-decoration:none;'
        f'border-radius:4px;font-size:12px;font-weight:600;">Zobrazit detail</a>'
    )
    map_html = _maps_link(listing)

    # Card border
    card_border = ""
    if listing.urgency == "hot":
        card_border = "border-left:4px solid #1a8917;"
    elif listing.price_drop_from:
        card_border = "border-left:4px solid #d93025;"

    return f"""
    <div style="background:#ffffff;border-radius:8px;overflow:hidden;margin-bottom:16px;border:1px solid #e0e0e0;{card_border}">
      {img_html}
      <div style="padding:12px 16px;">
        {score_html}{source_badge} {cross_html}
        <table cellpadding="0" cellspacing="0" border="0" width="100%" style="margin:8px 0;">
          <tr>
            <td style="font-size:20px;font-weight:700;color:#1a8917;vertical-align:bottom;">{price_str}</td>
            <td style="text-align:right;font-size:16px;font-weight:600;color:#222222;vertical-align:bottom;">{right_col}</td>
          </tr>
        </table>
        {price_detail}{drop_html}
        <div style="font-size:14px;font-weight:600;margin-bottom:6px;">
          <a href="{url}" style="color:#1a73e8;text-decoration:none;">{title}</a>
        </div>
        <div style="margin-bottom:10px;">{chips_html}{market_html}</div>
        <div>{cta_html}{map_html}</div>
      </div>
    </div>"""


def _render_compact_card(listing: Listing, is_rent: bool) -> str:
    """Minimal single-row card for low-score listings (no image)."""
    title = escape(listing.title)
    url = _safe_url(listing.url)
    price_str = _format_price(listing.price, is_rent)
    disp = escape(listing.disposition) if listing.disposition else ""
    size = f"{listing.size_m2}{NBSP}m²" if listing.size_m2 else ""
    info = f"{disp} {size}".strip()

    return f"""
    <div style="padding:10px 16px;border-bottom:1px solid #eeeeee;font-size:13px;">
      <a href="{url}" style="color:#1a73e8;text-decoration:none;font-weight:600;">{title}</a>
      <span style="color:#1a8917;font-weight:700;margin-left:8px;">{price_str}</span>
      <span style="color:#888888;margin-left:8px;">{info}</span>
    </div>"""


def _render_disappeared_section(disappeared: list[dict], is_rent: bool) -> str:
    if not disappeared:
        return ""
    rows = []
    for d in disappeared[:10]:
        title = escape(d.get("title", "?"))
        price = d.get("price", 0)
        url = _safe_url(d.get("url", ""))
        price_str = _format_price(price, is_rent) if price else "?"
        rows.append(
            f'<div style="padding:8px 0;border-bottom:1px solid #eeeeee;font-size:13px;">'
            f'<a href="{url}" style="color:#999999;text-decoration:line-through;">{title}</a>'
            f' − {price_str}</div>'
        )
    extra = f'<div style="color:#999999;font-size:12px;margin-top:8px;">...a dalších {len(disappeared) - 10}</div>' if len(disappeared) > 10 else ''
    return f"""
    <div style="margin-top:24px;padding:16px;background:#ffffff;border-radius:8px;border:1px solid #e0e0e0;">
      <div style="font-size:16px;font-weight:600;color:#d93025;margin-bottom:12px;">
        Zmizelo {len(disappeared)} nabídek
      </div>
      {''.join(rows)}{extra}
    </div>"""


def _render_market_footer(listings: list[Listing], all_seen: dict, is_rent: bool, profile_name: str = "") -> str:
    """Render market stats footer - just the numbers."""
    from market import compute_avg_time_on_market

    unit = "Kč/měsíc" if is_rent else "Kč"

    # Price ranges by disposition
    by_disp: dict[str, list[int]] = {}
    for l in listings:
        if l.disposition and l.price:
            by_disp.setdefault(l.disposition, []).append(l.price)

    lines = []
    for disp in sorted(by_disp, key=lambda d: len(by_disp[d]), reverse=True)[:4]:
        prices = sorted(by_disp[disp])
        lo = f"{prices[0]:,}".replace(",", NBSP)
        hi = f"{prices[-1]:,}".replace(",", NBSP)
        med = f"{prices[len(prices) // 2]:,}".replace(",", NBSP)
        lines.append(
            f'<div>{escape(disp)}: {lo} – {hi}{NBSP}{unit},'
            f' medián {med}{NBSP}{unit} ({len(prices)})</div>'
        )

    avg_days = compute_avg_time_on_market(all_seen)
    total_seen = sum(1 for v in all_seen.values() if isinstance(v, dict) and v.get("price"))

    footer_lines = []
    if lines:
        footer_lines.append("".join(lines))
    if avg_days is not None:
        footer_lines.append(f'<div>Průměrně na trhu {avg_days} dní</div>')
    if total_seen > 0:
        location_note = f" v {escape(profile_name)}" if profile_name else ""
        footer_lines.append(
            f'<div>Srovnání: ±15{NBSP}m² z {total_seen} historických nabídek{location_note}</div>'
        )

    if not footer_lines:
        return ""

    return f"""
    <div style="margin-top:20px;padding-top:12px;border-top:1px solid #e0e0e0;
      font-size:11px;color:#999999;line-height:1.8;">
      {"".join(footer_lines)}
    </div>"""


def _render_listings_grouped(listings: list[Listing], is_rent: bool) -> str:
    """Render listings grouped by urgency tier with factual section headers."""
    hot = [l for l in listings if l.urgency == "hot"]
    normal = [l for l in listings if l.urgency == "normal"]
    low = [l for l in listings if l.urgency == "low"]

    html = ""
    if hot:
        html += f'<div style="font-size:13px;font-weight:600;color:#1a8917;margin:16px 0 8px;padding-bottom:4px;border-bottom:2px solid #1a8917;">Skóre 75%+ ({len(hot)})</div>'
        html += "\n".join(_render_card(l, is_rent) for l in hot)
    if normal:
        label = f"Skóre 30–74% ({len(normal)})" if hot else ""
        if label:
            html += f'<div style="font-size:13px;font-weight:600;color:#555555;margin:24px 0 8px;padding-bottom:4px;border-bottom:1px solid #dddddd;">{label}</div>'
        html += "\n".join(_render_card(l, is_rent) for l in normal)
    if low:
        html += f'<div style="font-size:13px;color:#999999;margin:24px 0 8px;padding-bottom:4px;border-bottom:1px solid #eeeeee;">Skóre pod 30% ({len(low)})</div>'
        html += "\n".join(_render_compact_card(l, is_rent) for l in low)
    return html


def send_email(listings: list[Listing], email_cfg: dict, profile: dict | None = None,
               disappeared: list[dict] | None = None, all_seen: dict | None = None) -> None:
    if not listings:
        return

    profile = profile or {}
    profile_name = profile.get("name", "Byt Watchdog")
    is_rent = profile.get("search", {}).get("offer_type", "rent") == "rent"

    # Sort by score descending
    listings = sorted(listings, key=lambda l: l.score, reverse=True)

    cards_html = _render_listings_grouped(listings, is_rent)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    disappeared_html = _render_disappeared_section(disappeared or [], is_rent)
    footer_html = _render_market_footer(listings, all_seen or {}, is_rent, profile_name)

    new_count = sum(1 for l in listings if not l.price_drop_from)
    drop_count = sum(1 for l in listings if l.price_drop_from)
    hot_count = sum(1 for l in listings if l.urgency == "hot")

    subtitle_parts = []
    if new_count:
        subtitle_parts.append(f"{new_count} nových")
    if drop_count:
        subtitle_parts.append(f"{drop_count} slev")
    subtitle = ", ".join(subtitle_parts) + f" ({now})"

    # Subject line: count + cheapest price
    subject_parts = []
    if new_count:
        subject_parts.append(f"{new_count} nových")
    if drop_count:
        subject_parts.append(f"{drop_count} slev")
    subject_detail = ", ".join(subject_parts)
    cheapest = _format_price_plain(listings[-1].price, is_rent) if listings else ""
    subject = f"{subject_detail} | {profile_name}"
    if cheapest and new_count:
        subject += f" | od {cheapest}"

    # Preheader (hidden preview text for inbox)
    preheader = ""
    if listings:
        top = listings[0]
        preheader = f"Top: {top.score}% | {_format_price_plain(top.price, is_rent)}"
        if top.disposition:
            preheader += f" | {top.disposition}"
    preheader_html = (
        f'<div style="display:none;max-height:0;overflow:hidden;'
        f'mso-hide:all;font-size:1px;color:#f5f5f5;line-height:1px;">'
        f'{escape(preheader)}</div>'
    ) if preheader else ""

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="color-scheme" content="light dark">
<meta name="supported-color-schemes" content="light dark">
<title>{escape(profile_name)}</title>
</head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#f5f5f5;margin:0;padding:20px;">
{preheader_html}
<div style="max-width:700px;margin:0 auto;">
  <h1 style="color:#222222;font-size:22px;margin-bottom:4px;">{escape(profile_name)}</h1>
  <p style="color:#666666;font-size:14px;margin-bottom:24px;">{subtitle}</p>
  {cards_html}
  {disappeared_html}
  {footer_html}
  <p style="text-align:center;color:#999999;font-size:12px;margin-top:24px;">Byt Watchdog</p>
</div>
</body>
</html>"""

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = email_cfg["from"]
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain="byt-watchdog")

    recipients = email_cfg.get("to", [])
    if isinstance(recipients, str):
        recipients = [recipients]
    msg["To"] = ", ".join(recipients)

    # Plain text
    plain_lines = [f"{profile_name} - {subtitle}\n"]
    for l in listings:
        extras = []
        if l.urgency == "hot":
            extras.append("DOPORUCUJEME")
        if l.price_drop_from:
            extras.append(f"SLEVA z {_format_price_plain(l.price_drop_from, is_rent)}")
        if l.land_m2:
            extras.append(f"pozemek {l.land_m2} m2")
        if l.nearest_stop:
            extras.append(l.nearest_stop)
        extra_str = " | ".join(extras)
        if extra_str:
            extra_str = f" | {extra_str}"
        plain_lines.append(f"- [{l.score}%] {l.title} | {_format_price_plain(l.price, is_rent)}{extra_str} | {l.url}")
    plain = "\n".join(plain_lines)

    msg.attach(MIMEText(plain, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))

    with smtplib.SMTP(email_cfg["smtp_host"], email_cfg["smtp_port"]) as server:
        server.starttls()
        server.login(email_cfg["smtp_user"], email_cfg["smtp_password"])
        server.sendmail(email_cfg["from"], recipients, msg.as_string())
