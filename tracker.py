import json
import os
import re
import smtplib
import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

def clean_price_text(text):
    """Extracts clean float numbers from text like '₹85,999.00' -> 85999.0"""
    try:
        cleaned = re.sub(r'[^\d.]', '', text)
        return float(cleaned)
    except (ValueError, TypeError):
        return None

def fetch_price_with_playwright(product, browser):
    """Uses a real headless Chrome browser to bypass 403s and renders JS content."""
    url = product.get("url", "")
    platform = product.get("platform", "").lower()
    name = product.get("name", "Product")

    if not url:
        return None

    page = browser.new_page(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    )

    try:
        # Load page and wait for DOM content
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(3000)  # Wait 3 seconds for dynamic JS rendering

        html_content = page.content()
        soup = BeautifulSoup(html_content, "html.parser")

        selectors = []
        if platform == "amazon":
            selectors = [
                "span.a-price-whole",
                "span#priceblock_ourprice",
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
                "#price_val",
                ".product-price"
            ]
        else:
            selectors = product.get("selectors", [".price", "#price", "span.price"])

        for selector in selectors:
            elements = soup.select(selector)
            for element in elements:
                price = clean_price_text(element.text)
                if price and price > 100:  # Valid price filter
                    page.close()
                    return price

        print(f"[{platform.upper()}] Could not find price selector in page HTML.")
        page.close()
        return None

    except Exception as e:
        print(f"[{platform.upper()}] Playwright error fetching {name}: {e}")
        page.close()
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

    print(f"--- Tracking {len(products)} products with Playwright ---\n")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        for product in products:
            name = product.get("name", "Unknown Product")
            platform = product.get("platform", "Unknown")
            target_price = product.get("target_price", 0)

            print(f"Checking: {name} ({platform.capitalize()})...")
            current_price = fetch_price_with_playwright(product, browser)

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