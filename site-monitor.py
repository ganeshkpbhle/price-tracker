import os
import requests

TARGET_URL = "https://sevasindhugs1.karnataka.gov.in/gruhajyothi/renderApplicationForm.do"

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def send_telegram_alert(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram tokens not configured.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Error sending Telegram alert: {e}")

def check_portal():
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://sevasindhugs1.karnataka.gov.in/"
    }

    try:
        response = requests.get(TARGET_URL, headers=headers, timeout=15)
        print(f"HTTP Status Code: {response.status_code}")
        
        if response.status_code == 200:
            page_content = response.text.lower()
            
            # Key indicators present when the form is blocked/disabled
            disabled_keywords = [
                "service is disabled",
                "disabled in seva sindhu",
                "infromation",             # Common portal typo
                "ನಿಷ್ಕ್ರಿಯಗೊಳಿಸಲಾಗಿದೆ",     # Kannada for 'disabled'
                "ಇಲಾಖೆಯನ್ನು ಸಂಪರ್ಕಿಸಿ"       # Kannada for 'contact department'
            ]
            
            # Key form elements that MUST exist when the real application form loads
            active_form_keywords = [
                "escom",
                "consumer id",
                "account id",
                "aadhaar"
            ]
            
            # Check conditions
            has_disabled_msg = any(kw in page_content for kw in disabled_keywords)
            has_active_form = any(kw in page_content for kw in active_form_keywords)
            
            # Decisive evaluation: Must NOT have disabled messages AND MUST have active form fields
            if not has_disabled_msg and has_active_form:
                msg = f"🎉 GREEN LIGHT! The Gruha Jyothi ServicePlus form is REALLY online!\nAccess it here: {TARGET_URL}"
                print(msg)
                send_telegram_alert(msg)
            else:
                print("Page loaded (200 OK), but Content Inspection confirms form is STILL DISABLED. Retrying in 6 hours.")
        else:
            print(f"Server returned HTTP Status Code: {response.status_code}")
            
    except Exception as e:
        print(f"Network error during execution: {e}")

if __name__ == "__main__":
    check_portal()