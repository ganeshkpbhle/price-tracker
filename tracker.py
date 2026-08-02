import json
import os
import re
import smtplib
import requests
from bs4 import BeautifulSoup

def clean_price_text(text):
    """Extracts numbers from messy text like '₹1,999' or '85,000' -> 85000.0"""
    try:
        cleaned = re.sub(r'[^\d.]', '', text)
        return float(cleaned)
    except (ValueError, TypeError):
        return None

def fetch_price(product):
    """Fetches product page and extracts the price based on platform."""
    # Rotate User-Agents to prevent 403 Forbidden errors
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Cache-Control": "max-age=0",
    }
    
    platform = product.get("platform", "").lower()
    url = product.get("url", "")

    if not url:
        print("Missing URL for product.")
        return None

    try:
        session = requests.Session()
        response = session.get(url, headers=headers, timeout=15)
        
        if response.status_code != 200:
            print(f"[{platform.upper()}] HTTP Error {response.status_code}")
            return None

        soup = BeautifulSoup(response.text, "html.parser")
        
        # Platform-specific HTML price selectors
        selectors = []
        if platform == "amazon":
            selectors = [
                "span.a-price-whole",
                "span#priceblock_ourprice",
                "span#priceblock_dealprice",
                "span.a-offscreen",
                ".apexPriceToPay span.a-offscreen"
            ]
        elif platform == "flipkart":
            selectors = [
                "div.Nx9bqj",
                "div._30jeq3",
                "div._16JThd"
            ]
        elif platform == "buyhatke":
            selectors = [
                "div.current-price",
                "span.price-val",
                ".product-price",
                "#price_val"
            ]
        else:
            # Generic fallback selectors for other sites
            selectors = product.get("selectors", [".price", "#price", "span.price"])

        # Try each selector sequentially
        for selector in selectors:
            elements = soup.select(selector)
            for element in elements:
                price = clean_price_text(element.text)
                if price and price > 0:
                    return price

        print(f"[{platform.upper()}] Could not locate price element in HTML.")
        return None

    except Exception as e:
        print(f"Error fetching {product.get('name', 'Product')}: {e}")
        return None

def send_email_alert(product, current_price):
    """Sends email alert via Gmail SMTP."""
    sender_email = os.getenv("GMAIL_USER")
    app_password = os.getenv("GMAIL_APP_PASSWORD")
    recipient_email = os.getenv("ALERT_EMAIL")

    if not all([sender_email, app_password, recipient_email]):
        print(" -> Gmail credentials missing in environment. Skipping email.")
        return

    product_name = product.get("name", "Tracked Item")
    target_price = product.get("target_price", 0)
    platform = product.get("platform", "E-Commerce").capitalize()

    subject = f"🚨 Price Drop Alert: {product_name} at ₹{current_price:,.2f}!"
    body = (
        f"Good news!\n\n"
        f"The price for '{product_name}' dropped to ₹{current_price:,.2f} (Target: ₹{target_price:,.2f}) on {platform}.\n\n"
        f"Buy now: {product.get('url', '')}"
    )
    message = f"Subject: {subject}\n\n{body}"

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(sender_email, app_password)
            server.sendmail(sender_email, recipient_email, message)
        print(f" -> Email alert sent for {product_name}!")
    except Exception as e:
        print(f" -> Failed to send email alert: {e}")

def send_telegram_alert(product, current_price):
    """Sends a formatted notification via Telegram Bot API."""
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not (bot_token and chat_id):
        print(" -> Telegram secrets missing in environment. Skipping Telegram.")
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
    """Main loop to check all products in products.json"""
    if not os.path.exists("products.json"):
        print("Error: products.json file missing!")
        return

    with open("products.json", "r") as f:
        products = json.load(f)

    print(f"--- Tracking {len(products)} products ---\n")

    for product in products:
        name = product.get("name", "Unknown Product")
        platform = product.get("platform", "Unknown Platform")
        target_price = product.get("target_price", 0)

        print(f"Checking: {name} ({platform.capitalize()})...")
        current_price = fetch_price(product)
        
        if current_price:
            print(f" -> Current Price: ₹{current_price} | Target: ₹{target_price}")
            if current_price <= target_price:
                print(f" 🚨 Price drop detected! Sending alerts...")
                send_telegram_alert(product, current_price)
                send_email_alert(product, current_price)
        else:
            print(f" -> Could not retrieve price.")
        print("-" * 40)

if __name__ == "__main__":
    run_tracker()