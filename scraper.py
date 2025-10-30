import requests
from bs4 import BeautifulSoup
import json
from datetime import datetime, timezone

URL = "https://market.isagha.com/prices"
HEADERS = {"User-Agent": "Mozilla/5.0"}

def get_price(selector, soup):
    """Extract and clean price text using a CSS selector."""
    el = soup.select_one(selector)
    if not el:
        return None
    text = el.get_text(strip=True).replace("ج.م", "").strip()
    try:
        return float(text)
    except ValueError:
        return None

def main():
    print("🔄 Fetching data from", URL)
    response = requests.get(URL, headers=HEADERS)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "lxml")

    data = {
        "gold": {
            "24": {
                "sell": get_price("#gold > div > div:nth-child(1) > div > div.clearfix.stats > div:nth-child(1) > div.value", soup),
                "buy": get_price("#gold > div > div:nth-child(1) > div > div.clearfix.stats > div:nth-child(2) > div.value", soup)
            },
            "21": {
                "sell": get_price("#gold > div > div:nth-child(7) > div > div.clearfix.stats > div:nth-child(1) > div.value", soup),
                "buy": get_price("#gold > div > div:nth-child(7) > div > div.clearfix.stats > div:nth-child(2) > div.value", soup)
            },
            "18": {
                "sell": get_price("#gold > div > div:nth-child(10) > div > div.clearfix.stats > div:nth-child(1) > div.value", soup),
                "buy": get_price("#gold > div > div:nth-child(10) > div > div.clearfix.stats > div:nth-child(2) > div.value", soup)
            },
        },
        "silver": {
            "999": {
                "sell": get_price("#silver > div > div:nth-child(1) > div > div.clearfix.stats > div:nth-child(1) > div.value", soup),
                "buy": get_price("#silver > div > div:nth-child(1) > div > div.clearfix.stats > div:nth-child(2) > div.value", soup)
            },
            "925": {
                "sell": get_price("#silver > div > div:nth-child(4) > div > div.clearfix.stats > div:nth-child(1) > div.value", soup),
                "buy": get_price("#silver > div > div:nth-child(4) > div > div.clearfix.stats > div:nth-child(2) > div.value", soup)
            },
            "800": {
                "sell": get_price("#silver > div > div:nth-child(10) > div > div.clearfix.stats > div:nth-child(1) > div.value", soup),
                "buy": get_price("#silver > div > div:nth-child(10) > div > div.clearfix.stats > div:nth-child(2) > div.value", soup)
            },
        },
        "last_updated": datetime.now(timezone.utc).isoformat()
    }

    with open("prices.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print("✅ prices.json updated successfully!")

if __name__ == "__main__":
    main()
