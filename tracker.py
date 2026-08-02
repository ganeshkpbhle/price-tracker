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
    """Extracts clean float numbers from text like '₹85,399.00' -> 85399.0"""
    try:
        cleaned = re.sub(r'[^\d.]', '', text.replace(',', ''))
        return float(cleaned)
    except (ValueError, TypeError):
        return None

def fetch_price_stealth(product, browser):
    """Uses Playwright with a two-tier extraction pipeline for resilient price parsing."""
    url = product.get("url", "")
    platform = product.get("platform", "").lower()
    name = product.get("name", "Product")

    if not url:
        return None

    context = browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        viewport={"width": 1366, "height": 768},
        locale="en-IN",
        timezone_id="Asia/Kolkata"
    )

    page = context.new_page()

    # Mask automation flags
    page.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
    """)

    try:
        print(f" -> Navigating to URL...")
        page.goto(url, wait_until="domcontentloaded", timeout=45000)
        
        # Scroll down slightly and wait for dynamic JavaScript to load
        page.evaluate("window.scrollBy(0, 400)")
        page.wait_for_timeout(5000)

        html_content = page.content()
        soup = BeautifulSoup(html_content, "html.parser")

        # --- TIER 1: Standard CSS Selectors ---
        selectors = []
        if platform == "amazon":
            selectors = [
                "span.a-price-whole",
                "span#priceblock_ourprice",
                "span#priceblock_dealprice",
                "span.a-offscreen",
                ".apexPriceToPay span.a-offscreen",
                "span.a-color-price"
            ]
        elif platform == "flipkart":
            selectors = [
                "div.Nx9bqj._16JThd",
                "div.Nx9bqj",
                "div._30jeq3._16JThd",
                "div._30jeq3",
                "div._16JThd",
                "div.C23321",
                "div._25bR30",
                "div.UOC20"
            ]
        elif platform == "buyhatke":
            selectors = [
                "#price_val",
                ".current-price",
                "span.price-val",
                ".product-price",
                "div.price-box",
                ".p-price",
                "span.amount",
                "div[class*='price']",
                ".top-price"
            ]
        else:
            selectors = product.get("selectors", [".price", "#price", "span.price"])

        # Attempt Tier 1 extraction
        for selector in selectors:
            elements = soup.select(selector)
            for element in elements:
                price = clean_price_text(element.text)
                if price and price > 1000:  # Valid product price threshold
                    context.close()
                    return price

        # --- TIER 2: Regex DOM Text Fallback ---
        # Search page text for price patterns like ₹85,399 or Rs. 85399
        print(f"[{platform.upper()}] Selectors failed. Trying Tier 2 Regex Fallback...")
        page_text = soup.get_text()
        raw_matches = re.findall(r'(?:₹|Rs\.?)\s*([\d,]+(?:\.\d{2})?)', page_text)
        
        valid_prices = []
        for match in raw_matches:
            val = clean_price_text(match)
            # Filter out tiny values (like discounts or delivery fees) and huge unreal numbers
            if val and 10000 <= val <= 300000:
                valid_prices.append(val)

        if valid_prices:
            # Pick the most frequently occurring valid price on the page
            most_common_price = max(set(valid_prices), key=valid_prices.count)
            context.close()
            return most_common_price

        print(f"[{platform.upper()}] Price element not found in rendered DOM.")
        context.close()
        return None

    except Exception as e:
        print(f"[{platform.upper()}] Error fetching {name}: {e}")
        context.close()
        return None

def send_email_alert(product, current_price):
    """Sends UTF-8 encoded email alert via Gmail SMTP."""
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
    """Sends notification via Telegram Bot API."""
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
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-setuid-sandbox"
            ]
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