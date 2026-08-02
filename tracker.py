import json
import os
import re
import smtplib
from email.mime.text import MIMEText
from email.header import Header
import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

def clean_price_text(text):
    """Extracts numbers from messy text like '₹85,399.00' -> 85399.0"""
    try:
        cleaned = re.sub(r'[^\d.]', '', text.replace(',', ''))
        return float(cleaned)
    except (ValueError, TypeError):
        return None

def fetch_price_stealth(product, browser):
    url = product.get("url", "")
    platform = product.get("platform", "").lower()
    name = product.get("name", "Product")

    if not url:
        return None

    # Mobile Web User Agent bypasses Datacenter Bot Protection on GitHub Actions
    context = browser.new_context(
        user_agent="Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Mobile Safari/537.36",
        viewport={"width": 412, "height": 915},
        locale="en-IN",
        timezone_id="Asia/Kolkata"
    )

    page = context.new_page()

    try:
        print(f" -> Navigating to URL...")
        # 'commit' means we stop waiting as soon as initial HTML receives response, avoiding timeout hangs!
        page.goto(url, wait_until="commit", timeout=30000)
        page.wait_for_timeout(4000)

        html_content = page.content()
        soup = BeautifulSoup(html_content, "html.parser")

        # Broad price selectors covering mobile & desktop structures
        selectors = [
            "span.a-price-whole",
            "span.a-offscreen",
            "div.Nx9bqj",
            "div._30jeq3",
            "#price_val",
            ".current-price",
            "span.price-val",
            ".product-price"
        ]

        for selector in selectors:
            elements = soup.select(selector)
            for element in elements:
                price = clean_price_text(element.text)
                if price and 10000 <= price <= 300000:
                    context.close()
                    return price

        # Regex Fallback for price extraction
        page_text = soup.get_text()
        raw_matches = re.findall(r'(?:₹|Rs\.?)\s*([\d,]+)', page_text)
        valid_prices = [clean_price_text(m) for m in raw_matches if clean_price_text(m) and 10000 <= clean_price_text(m) <= 300000]

        if valid_prices:
            most_common = max(set(valid_prices), key=valid_prices.count)
            context.close()
            return most_common

        print(f"[{platform.upper()}] Price element not found.")
        context.close()
        return None

    except Exception as e:
        print(f"[{platform.upper()}] Error fetching {name}: {e}")
        context.close()
        return None

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
    body = f"Good news!\n\nThe price for '{product_name}' dropped to ₹{current_price:,.2f} (Target: ₹{target_price:,.2f}) on {platform}.\n\nBuy now: {product.get('url', '')}"

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
        f"🚨 *PRICE DROP ALERT!*\n\n"
        f"📦 *Item:* {product_name}\n"
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

    print(f"--- Tracking {len(products)} products with Stealth Playwright ---\n")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox"]
        )

        for product in products:
            name = product.get("name", "Unknown Product")
            platform = product.get("platform", "Unknown")
            target_price = product.get("target_price", 0)

            print(f"Checking: {name} ({platform.capitalize()})...")
            current_price = fetch_price_stealth(product, browser)

            if current_price:
                print(f" -> Current Price: ₹{current_price:,.2f} | Target: ₹{target_price:,.2f}")
                if current_price <= target_price:
                    print(" 🚨 Price drop detected! Sending alerts...")
                    send_telegram_alert(product, current_price)
                    send_email_alert(product, current_price)
            else:
                print(" -> Could not retrieve price.")
            print("-" * 40)

        browser.close()

if __name__ == "__main__":
    run_tracker()