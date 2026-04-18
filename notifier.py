import os
import smtplib
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from scrapers.base import Listing

TEMPLATE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "email_template.html")

SOURCE_BADGE_CLASS = {
    "sreality": "badge-sreality",
    "bezrealitky": "badge-bezrealitky",
    "remax": "badge-remax",
}


def _render_card(listing: Listing) -> str:
    badge_cls = SOURCE_BADGE_CLASS.get(listing.source, "badge-sreality")

    img_html = ""
    if listing.image_url:
        img_html = f'<img class="card-img" src="{listing.image_url}" alt="{listing.title}">'

    details = []
    if listing.disposition:
        details.append(f"<span>{listing.disposition}</span>")
    if listing.size_m2:
        details.append(f"<span>{listing.size_m2} m&sup2;</span>")
    if listing.location:
        details.append(f"<span>{listing.location}</span>")

    return f"""
    <div class="card">
      {img_html}
      <div class="card-body">
        <div class="card-title"><a href="{listing.url}">{listing.title}</a></div>
        <div class="card-price">{listing.price:,} Kc/mesic</div>
        <div class="card-details">
          {' '.join(details)}
        </div>
        <span class="badge {badge_cls}">{listing.source}</span>
      </div>
    </div>"""


def _render_email(listings: list[Listing]) -> str:
    with open(TEMPLATE_PATH, "r") as f:
        template = f.read()

    cards_html = "\n".join(_render_card(l) for l in listings)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    html = template.replace("{{count}}", str(len(listings)))
    html = html.replace("{{date}}", now)
    html = html.replace("{{listings}}", cards_html)
    return html


def send_email(listings: list[Listing], config: dict) -> None:
    if not listings:
        return

    email_cfg = config["email"]

    # Sort by price ascending
    listings = sorted(listings, key=lambda l: l.price)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Byt Watchdog: {len(listings)} novych bytu v Praha 7"
    msg["From"] = email_cfg["from"]
    msg["To"] = email_cfg["to"]

    # Plain text fallback
    plain_lines = [f"Nalezeno {len(listings)} novych bytu k pronajmu v Praha 7:\n"]
    for l in listings:
        plain_lines.append(f"- {l.title} | {l.price:,} Kc | {l.location} | {l.url}")
    plain = "\n".join(plain_lines)

    html = _render_email(listings)

    msg.attach(MIMEText(plain, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))

    with smtplib.SMTP(email_cfg["smtp_host"], email_cfg["smtp_port"]) as server:
        server.starttls()
        server.login(email_cfg["smtp_user"], email_cfg["smtp_password"])
        server.sendmail(email_cfg["from"], email_cfg["to"], msg.as_string())
