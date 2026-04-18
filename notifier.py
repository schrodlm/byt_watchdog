import smtplib
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formatdate, make_msgid
from html import escape

from scrapers.base import Listing


def _safe_url(url: str) -> str:
    if url and url.startswith(("https://", "http://")):
        return escape(url, quote=True)
    return "#"


def _format_price(price: int, is_rent: bool) -> str:
    """Format price with spaces as thousand separator."""
    formatted = f"{price:,}".replace(",", " ")
    if is_rent:
        return f"{formatted} Kc/mesic"
    return f"{formatted} Kc"


def _render_card(listing: Listing, is_rent: bool) -> str:
    source = escape(listing.source)
    title = escape(listing.title)
    location = escape(listing.location)
    disposition = escape(listing.disposition) if listing.disposition else ""
    url = _safe_url(listing.url)

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

    # Price
    price_html = f'<div style="font-size:20px;font-weight:700;color:#1a8917;margin-bottom:8px;">{_format_price(listing.price, is_rent)}'

    if listing.price_drop_from:
        old_price = _format_price(listing.price_drop_from, is_rent)
        savings = listing.price_drop_from - listing.price
        savings_str = f"{savings:,}".replace(",", " ")
        price_html += (
            f' <span style="font-size:13px;color:#d93025;font-weight:600;">'
            f'SLEVA z {old_price} (-{savings_str} Kc)</span>'
        )

    if listing.charges and is_rent:
        charges_str = f"{listing.charges:,}".replace(",", " ")
        price_html += f' <span style="font-size:13px;color:#888;">+ {charges_str} poplatky</span>'

    price_html += '</div>'

    # Details
    details = []
    if disposition:
        details.append(disposition)
    if listing.size_m2:
        details.append(f"{listing.size_m2} m&sup2;")
        if is_rent and listing.size_m2 > 0:
            ppm2 = round(listing.price / listing.size_m2)
            details.append(f"{ppm2} Kc/m&sup2;")
    if listing.land_m2:
        land_str = f"{listing.land_m2:,}".replace(",", " ")
        details.append(f"pozemek {land_str} m&sup2;")
    if location:
        details.append(location)

    # Tram/transport stop
    if listing.nearest_stop and listing.stop_distance_m is not None:
        if listing.stop_distance_m < 1000:
            stop_str = f"{escape(listing.nearest_stop)} ({listing.stop_distance_m} m)"
        else:
            stop_str = f"{escape(listing.nearest_stop)} ({listing.stop_distance_m / 1000:.1f} km)"
        details.append(stop_str)

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

    # Maps link
    maps_html = ""
    if listing.lat and listing.lon:
        maps_url = f"https://maps.google.com/?q={listing.lat},{listing.lon}"
        maps_html = f' <a href="{maps_url}" style="font-size:12px;color:#1a73e8;text-decoration:none;">[mapa]</a>'

    card_border = "border-left:4px solid #d93025;" if listing.price_drop_from else ""

    return f"""
    <div style="background:#fff;border-radius:8px;overflow:hidden;margin-bottom:16px;{card_border}">
      {img_html}
      <div style="padding:16px;">
        <div style="font-size:16px;font-weight:600;margin:0 0 8px;">
          <a href="{url}" style="color:#1a73e8;text-decoration:none;">{title}</a>{maps_html}
        </div>
        {price_html}
        <div style="color:#555;font-size:13px;margin-bottom:8px;">{details_html}</div>
        {score_html}
        <span style="display:inline-block;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:600;text-transform:uppercase;{badge_style}">{badge_label}</span>
        {cross_html}
      </div>
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
            f'<div style="padding:8px 0;border-bottom:1px solid #eee;font-size:13px;">'
            f'<a href="{url}" style="color:#999;text-decoration:line-through;">{title}</a>'
            f' - {price_str}</div>'
        )
    extra = f'<div style="color:#999;font-size:12px;margin-top:8px;">...a dalsi {len(disappeared) - 10}</div>' if len(disappeared) > 10 else ''
    return f"""
    <div style="margin-top:24px;padding:16px;background:#fff;border-radius:8px;">
      <div style="font-size:16px;font-weight:600;color:#d93025;margin-bottom:12px;">
        Zmizelo {len(disappeared)} nabidek
      </div>
      {''.join(rows)}
      {extra}
    </div>"""


def send_email(listings: list[Listing], email_cfg: dict, profile: dict | None = None,
               disappeared: list[dict] | None = None) -> None:
    if not listings:
        return

    profile = profile or {}
    profile_name = profile.get("name", "Byt Watchdog")
    is_rent = profile.get("search", {}).get("offer_type", "rent") == "rent"

    # Sort by score descending
    listings = sorted(listings, key=lambda l: l.score, reverse=True)

    cards_html = "\n".join(_render_card(l, is_rent) for l in listings)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    disappeared_html = _render_disappeared_section(disappeared or [], is_rent)

    new_count = sum(1 for l in listings if not l.price_drop_from)
    drop_count = sum(1 for l in listings if l.price_drop_from)
    subtitle_parts = []
    if new_count:
        subtitle_parts.append(f"{new_count} novych")
    if drop_count:
        subtitle_parts.append(f"{drop_count} slev")
    subtitle = ", ".join(subtitle_parts) + f" ({now})"

    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#f5f5f5;margin:0;padding:20px;">
<div style="max-width:700px;margin:0 auto;">
  <h1 style="color:#1a1a1a;font-size:22px;margin-bottom:4px;">{escape(profile_name)}</h1>
  <p style="color:#666;font-size:14px;margin-bottom:24px;">{subtitle}</p>
  {cards_html}
  {disappeared_html}
  <p style="text-align:center;color:#999;font-size:12px;margin-top:24px;">Byt Watchdog</p>
</div>
</body>
</html>"""

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"{profile_name}: {len(listings)} novych nabidek"
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
        if l.price_drop_from:
            extras.append(f"SLEVA z {l.price_drop_from}")
        if l.land_m2:
            extras.append(f"pozemek {l.land_m2}m2")
        if l.nearest_stop:
            extras.append(l.nearest_stop)
        extra_str = " | ".join(extras)
        if extra_str:
            extra_str = f" | {extra_str}"
        plain_lines.append(f"- [{l.score}%] {l.title} | {_format_price(l.price, is_rent)}{extra_str} | {l.url}")
    plain = "\n".join(plain_lines)

    msg.attach(MIMEText(plain, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))

    with smtplib.SMTP(email_cfg["smtp_host"], email_cfg["smtp_port"]) as server:
        server.starttls()
        server.login(email_cfg["smtp_user"], email_cfg["smtp_password"])
        server.sendmail(email_cfg["from"], recipients, msg.as_string())
