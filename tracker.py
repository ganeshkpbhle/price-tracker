import json
import os
import re
import smtplib
from email.mime.text import MIMEText
from email.header import Header
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()


def clean_price_text(text):
    """Extracts clean float numbers from text like '₹85,399.00' -> 85399.0"""
    try:
        cleaned = re.sub(r'[^\d.]', '', text.replace(',', ''))
        return float(cleaned)
    except (ValueError, TypeError):
        return None


def fetch_price_via_proxy(product):
    """
    Fetches product HTML via ScraperAPI proxy network.
    Returns a tuple: (price, is_available)
    """
    raw_url = product.get("url", "")
    platform = product.get("platform", "").lower()
    name = product.get("name", "Product")
    api_key = os.getenv("SCRAPER_API_KEY")

    if not raw_url:
        return None, False

    # Enable JS rendering ONLY for Amazon; use fast standard proxy for Flipkart & BuyHatke
    if api_key:
        print(" -> Fetching via ScraperAPI proxy...")
        if platform == "buyhatke":
            proxy_url = f"https://api.scraperapi.com?api_key={api_key}&url={raw_url}&country_code=in"
        elif platform == "flipkart":
            proxy_url = f"https://api.scraperapi.com?api_key={api_key}&url={raw_url}"
        else:
            proxy_url = f"https://api.scraperapi.com?api_key={api_key}&url={raw_url}&render=true"
    else:
        print(" -> Fetching directly...")
        proxy_url = raw_url

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/126.0.0.0 Safari/537.36"
        )
    }

    try:
        response = requests.get(proxy_url, headers=headers, timeout=60)
        if response.status_code != 200:
            print(f"[{platform.upper()}] HTTP Error {response.status_code}")
            return None, False

        soup = BeautifulSoup(response.text, "html.parser")

        # --- AVAILABILITY CHECK ---
        is_available = True
        oos_selectors = [
            "#availability .a-color-price",      # Amazon ("Currently unavailable")
            "#outOfStock",                       # Amazon out of stock wrapper
            "div._16FRp0",                       # Flipkart "Currently Out of Stock"
            "button._2KpZ6l._2U9uOA._3dGepF"     # Flipkart disabled / sold out button
        ]

        for oos_sel in oos_selectors:
            el = soup.select_one(oos_sel)
            if el and any(phrase in el.text.lower() for phrase in ["currently unavailable", "out of stock", "sold out"]):
                is_available = False
                break

        # Fallback check on general availability text blocks
        if is_available:
            avail_div = soup.select_one("#availability") or soup.select_one(".availability")
            if avail_div and any(phrase in avail_div.text.lower() for phrase in ["currently unavailable", "out of stock"]):
                is_available = False

        # --- TIER 1: Explicit High-Priority Selectors ---
        selectors = []
        if platform == "amazon":
            selectors = [
                "span.a-price-whole",
                "span#priceblock_ourprice",
                ".apexPriceToPay span.a-offscreen",
                "span.a-offscreen"
            ]
        elif platform == "flipkart":
            selectors = [
                "div.Nx9bqj._16JThd",
                "div.Nx9bqj",
                "div._30jeq3._16JThd",
                "div._30jeq3"
            ]
        elif platform == "buyhatke":
            selectors = [
                "#price_val",
                ".current-price",
                "span.price-val",
                ".product-price",
                "div[class*='price']"
            ]
        else:
            selectors = product.get("selectors", [".price", "#price", "span.price"])

        # Try Tier 1 Selectors
        for selector in selectors:
            elements = soup.select(selector)
            for element in elements:
                parent_text = element.parent.text if element.parent else ""
                if any(k in parent_text.lower() for k in ["emi", "off", "exchange", "save", "per month"]):
                    continue

                price = clean_price_text(element.text)
                if price and 50000 <= price <= 150000:
                    return price, is_available

        # --- TIER 2: Contextual Container Parsing Fallback ---
        print(f"[{platform.upper()}] Specific selectors missed. Running Context-Scoped Parser...")

        main_containers = soup.find_all(['div', 'main', 'section', 'span'])
        valid_prices = []

        for container in main_containers:
            text = container.get_text()
            if any(k in text.lower() for k in ["emi", "off", "exchange", "per month"]):
                continue
            raw_matches = re.findall(r'(?:₹|Rs\.?)\s*([\d,]+)', text)
            for m in raw_matches:
                val = clean_price_text(m)
                if val and 50000 <= val <= 150000:
                    valid_prices.append(val)

        if valid_prices:
            most_common = max(set(valid_prices), key=valid_prices.count)
            return most_common, is_available

        print(f"[{platform.upper()}] Could not locate valid product price.")
        return None, is_available

    except Exception as e:
        print(f"[{platform.upper()}] Error fetching {name}: {e}")
        return None, False


def send_email_alert(product, current_price):
    sender_email = os.getenv("GMAIL_USER")
    app_password = os.getenv("GMAIL_APP_PASSWORD")
    recipient_email = os.getenv("ALERT_EMAIL")

    if not all([sender_email, app_password, recipient_email]):
        print(" -> Gmail credentials missing. Skipping email.")
        return

    product_name = product.get("name", "Tracked Item")
    target_price = product.get("target_price", 0)
    platform = product.get("platform", "E-Commerce").capitalize()

    subject = f"🚨 Price Drop Alert: {product_name} at ₹{current_price:,.2f}!"
    body = (
        f"Good news!\n\n"
        f"The item '{product_name}' is IN STOCK and dropped to ₹{current_price:,.2f} "
        f"(Target: ₹{target_price:,.2f}) on {platform}.\n\n"
        f"Buy now: {product.get('url', '')}"
    )

    msg = MIMEText(body, 'plain', 'utf-8')
    msg['Subject'] = Header(subject, 'utf-8')
    msg['From'] = sender_email
    msg['To'] = recipient_email

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(sender_email, app_password)
            server.sendmail(sender_email, [recipient_email], msg.as_string())
        print(f" -> Email alert sent for {product_name}!")
    except Exception as e:
        print(f" -> Failed to send email: {e}")


def send_telegram_alert(product, current_price):
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not (bot_token and chat_id):
        print(" -> Telegram credentials missing. Skipping Telegram.")
        return

    product_name = product.get("name", "Tracked Item")
    target_price = product.get("target_price", 0)
    platform = product.get("platform", "E-Commerce").capitalize()

    message = (
        f"🚨 *IN-STOCK PRICE DROP ALERT!*\n\n"
        f"📦 *Item:* {product_name}\n"
        f"⚡ *Status:* Available to Buy ✅\n"
        f"🏷️ *Current Price:* ₹{current_price:,.2f}\n"
        f"🎯 *Target Price:* ₹{target_price:,.2f}\n"
        f"🛒 *Platform:* {platform}\n\n"
        f"🔗 [Buy Now]({product.get('url', '')})"
    )

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {"chat_id": chat_id, "text": message, "parse_mode": "Markdown"}

    try:
        res = requests.post(url, json=payload, timeout=10)
        if res.status_code == 200:
            print(f" -> Telegram alert sent for {product_name}!")
        else:
            print(f" -> Telegram API error: {res.status_code}")
    except Exception as e:
        print(f" -> Failed to send Telegram alert: {e}")


def run_tracker():
    if not os.path.exists("products.json"):
        print("Error: products.json missing!")
        return

    with open("products.json", "r") as f:
        products = json.load(f)

    print(f"--- Tracking {len(products)} products via Proxy Network ---\n")

    for product in products:
        name = product.get("name", "Unknown Product")
        platform = product.get("platform", "Unknown")
        target_price = product.get("target_price", 0)

        print(f"Checking: {name} ({platform.capitalize()})...")
        current_price, is_available = fetch_price_via_proxy(product)

        if not is_available:
            print(" -> Status: ❌ OUT OF STOCK")
        elif current_price:
            print(f" -> Status: ✅ IN STOCK | Price: ₹{current_price:,.2f} | Target: ₹{target_price:,.2f}")
            if current_price <= target_price:
                print(" 🚨 In-stock deal detected! Sending alerts...")
                send_telegram_alert(product, current_price)
                send_email_alert(product, current_price)
            else:
                print(" -> In stock, but waiting for target price.")
        else:
            print(" -> Could not retrieve price.")
        print("-" * 40)


if __name__ == "__main__":
    run_tracker()