import os
import smtplib
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formatdate, make_msgid
from html import escape

from scrapers.base import Listing

TEMPLATE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "email_template.html")


def _safe_url(url: str) -> str:
    """Validate URL starts with http(s)."""
    if url and url.startswith(("https://", "http://")):
        return escape(url, quote=True)
    return "#"


def _render_card(listing: Listing) -> str:
    source = escape(listing.source)
    title = escape(listing.title)
    location = escape(listing.location)
    disposition = escape(listing.disposition) if listing.disposition else ""
    url = _safe_url(listing.url)

    # Source badge colors (inline)
    badge_colors = {
        "sreality": ("background:#e8f0fe;color:#1a73e8;", "Sreality"),
        "bezrealitky": ("background:#fce8e6;color:#d93025;", "Bezrealitky"),
        "remax": ("background:#e6f4ea;color:#1e8e3e;", "RE/MAX"),
    }
    badge_style, badge_label = badge_colors.get(listing.source, ("background:#eee;color:#333;", source))

    # Image
    img_html = ""
    if listing.image_url:
        img_url = _safe_url(listing.image_url)
        img_html = f'<img src="{img_url}" alt="{title}" style="width:100%;max-height:200px;display:block;">'

    # Price display
    price_str = f"{listing.price:,}".replace(",", " ")
    price_html = f'<div style="font-size:20px;font-weight:700;color:#1a8917;margin-bottom:8px;">{price_str} Kc/mesic'

    # Price drop badge
    if listing.price_drop_from:
        old_price = f"{listing.price_drop_from:,}".replace(",", " ")
        savings = listing.price_drop_from - listing.price
        price_html += (
            f' <span style="font-size:13px;color:#d93025;font-weight:600;">'
            f'SLEVA z {old_price} Kc (-{savings:,} Kc)</span>'
        ).replace(",", " ")

    # Charges
    if listing.charges:
        charges_str = f"{listing.charges:,}".replace(",", " ")
        price_html += f' <span style="font-size:13px;color:#888;">+ {charges_str} poplatky</span>'

    price_html += '</div>'

    # Details row
    details = []
    if disposition:
        details.append(disposition)
    if listing.size_m2:
        details.append(f"{listing.size_m2} m&sup2;")
        # Price per m2
        ppm2 = round(listing.price / listing.size_m2)
        details.append(f"{ppm2} Kc/m&sup2;")
    if location:
        details.append(location)

    # Metro distance
    if listing.metro_station and listing.metro_distance_m is not None:
        if listing.metro_distance_m < 1000:
            metro_str = f"M {listing.metro_station} ({listing.metro_distance_m} m)"
        else:
            metro_str = f"M {listing.metro_station} ({listing.metro_distance_m / 1000:.1f} km)"
        details.append(metro_str)

    details_html = " &middot; ".join(
        f'<span style="display:inline-block;margin-right:4px;">{d}</span>' for d in details
    )

    # Score badge
    score_html = ""
    if listing.score > 0:
        if listing.score >= 70:
            score_color = "#1a8917"
        elif listing.score >= 40:
            score_color = "#e8a317"
        else:
            score_color = "#888"
        score_html = (
            f'<span style="display:inline-block;padding:2px 8px;border-radius:4px;'
            f'font-size:11px;font-weight:700;background:{score_color};color:#fff;margin-right:4px;">'
            f'{listing.score}%</span>'
        )

    # Cross-source badge
    cross_html = ""
    if listing.cross_source:
        sites = ", ".join(listing.cross_source)
        cross_html = (
            f'<span style="display:inline-block;padding:2px 8px;border-radius:4px;'
            f'font-size:11px;background:#f0f0f0;color:#555;margin-right:4px;">'
            f'take na: {escape(sites)}</span>'
        )

    # Google Maps link
    maps_html = ""
    if listing.lat and listing.lon:
        maps_url = f"https://maps.google.com/?q={listing.lat},{listing.lon}"
        maps_html = (
            f' <a href="{maps_url}" style="font-size:12px;color:#1a73e8;text-decoration:none;">'
            f'[mapa]</a>'
        )

    # Price drop card border
    card_border = ""
    if listing.price_drop_from:
        card_border = "border-left:4px solid #d93025;"

    return f"""
    <div style="background:#fff;border-radius:8px;overflow:hidden;margin-bottom:16px;{card_border}">
      {img_html}
      <div style="padding:16px;">
        <div style="font-size:16px;font-weight:600;margin:0 0 8px;">
          <a href="{url}" style="color:#1a73e8;text-decoration:none;">{title}</a>{maps_html}
        </div>
        {price_html}
        <div style="color:#555;font-size:13px;margin-bottom:8px;">
          {details_html}
        </div>
        {score_html}
        <span style="display:inline-block;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:600;text-transform:uppercase;{badge_style}">{badge_label}</span>
        {cross_html}
      </div>
    </div>"""


def _render_disappeared_section(disappeared: list[dict]) -> str:
    if not disappeared:
        return ""

    rows = []
    for d in disappeared[:10]:
        title = escape(d.get("title", "?"))
        price = d.get("price", 0)
        url = _safe_url(d.get("url", ""))
        price_str = f"{price:,}".replace(",", " ") if price else "?"
        rows.append(
            f'<div style="padding:8px 0;border-bottom:1px solid #eee;font-size:13px;">'
            f'<a href="{url}" style="color:#999;text-decoration:line-through;">{title}</a>'
            f' - {price_str} Kc</div>'
        )

    return f"""
    <div style="margin-top:24px;padding:16px;background:#fff;border-radius:8px;">
      <div style="font-size:16px;font-weight:600;color:#d93025;margin-bottom:12px;">
        Zmizel{'o' if len(disappeared) != 1 else ''} {len(disappeared)} nabid{'ka' if len(disappeared) == 1 else 'ek'}
      </div>
      {''.join(rows)}
      {f'<div style="color:#999;font-size:12px;margin-top:8px;">...a dalsi {len(disappeared) - 10}</div>' if len(disappeared) > 10 else ''}
    </div>"""


def _render_email(listings: list[Listing], disappeared: list[dict] | None = None) -> str:
    cards_html = "\n".join(_render_card(l) for l in listings)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    disappeared_html = _render_disappeared_section(disappeared or [])

    # Count sections
    new_count = sum(1 for l in listings if not l.price_drop_from)
    drop_count = sum(1 for l in listings if l.price_drop_from)

    subtitle_parts = []
    if new_count:
        subtitle_parts.append(f"{new_count} novych")
    if drop_count:
        subtitle_parts.append(f"{drop_count} slev")
    subtitle = ", ".join(subtitle_parts) + f" ({now})"

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#f5f5f5;margin:0;padding:20px;">
<div style="max-width:700px;margin:0 auto;">
  <h1 style="color:#1a1a1a;font-size:22px;margin-bottom:4px;">Nove byty k pronajmu - Praha 7</h1>
  <p style="color:#666;font-size:14px;margin-bottom:24px;">{subtitle}</p>

  {cards_html}
  {disappeared_html}

  <p style="text-align:center;color:#999;font-size:12px;margin-top:24px;">Byt Watchdog - automaticky monitoring pronajmu</p>
</div>
</body>
</html>"""


def send_email(listings: list[Listing], config: dict, disappeared: list[dict] | None = None) -> None:
    if not listings:
        return

    email_cfg = config["email"]

    # Sort by score descending (best first)
    listings = sorted(listings, key=lambda l: l.score, reverse=True)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Byt Watchdog: {len(listings)} novych bytu v Praha 7"
    msg["From"] = email_cfg["from"]
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain="byt-watchdog")

    recipients = email_cfg["to"]
    if isinstance(recipients, str):
        recipients = [recipients]
    msg["To"] = ", ".join(recipients)

    # Plain text fallback
    plain_lines = [f"Nalezeno {len(listings)} novych bytu k pronajmu v Praha 7:\n"]
    for l in listings:
        extra = ""
        if l.price_drop_from:
            extra = f" (SLEVA z {l.price_drop_from} Kc)"
        if l.metro_station:
            extra += f" | M {l.metro_station} {l.metro_distance_m}m"
        plain_lines.append(f"- [{l.score}%] {l.title} | {l.price:,} Kc{extra} | {l.location} | {l.url}")
    if disappeared:
        plain_lines.append(f"\nZmizelo {len(disappeared)} nabidek:")
        for d in disappeared[:10]:
            plain_lines.append(f"- {d.get('title', '?')} | {d.get('price', '?')} Kc")
    plain = "\n".join(plain_lines)

    html = _render_email(listings, disappeared)

    msg.attach(MIMEText(plain, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))

    with smtplib.SMTP(email_cfg["smtp_host"], email_cfg["smtp_port"]) as server:
        server.starttls()
        server.login(email_cfg["smtp_user"], email_cfg["smtp_password"])
        server.sendmail(email_cfg["from"], recipients, msg.as_string())
