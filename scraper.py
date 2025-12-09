import requests
from bs4 import BeautifulSoup
import json
from datetime import datetime, timezone
import base64
from PIL import Image
from io import BytesIO
import pytesseract
import re

URL = "https://market.isagha.com/prices"
HEADERS = {"User-Agent": "Mozilla/5.0"}

def extract_price_from_base64_image(base64_string):
    """Extract price from base64-encoded image using OCR."""
    try:
        # Remove the data:image/png;base64, prefix if present
        if ',' in base64_string:
            base64_string = base64_string.split(',')[1]
        
        # Decode base64 to image
        image_data = base64.b64decode(base64_string)
        image = Image.open(BytesIO(image_data))
        
        # Use Tesseract to extract text from image
        # Configure Tesseract to recognize digits and decimal points
        custom_config = r'--oem 3 --psm 7 -c tessedit_char_whitelist=0123456789.'
        text = pytesseract.image_to_string(image, config=custom_config)
        
        # Clean the extracted text and convert to float
        text = text.strip().replace(' ', '').replace('\n', '')
        
        # Extract numbers using regex
        numbers = re.findall(r'\d+\.?\d*', text)
        if numbers:
            return float(numbers[0])
        return None
    except Exception as e:
        print(f"Error extracting price from image: {e}")
        return None

def get_price(selector, soup):
    """Extract and clean price from either text or base64 image."""
    el = soup.select_one(selector)
    if not el:
        return None
    
    # Check if price is in an image
    img = el.select_one('img.price-cell')
    if img and img.get('src'):
        src = img.get('src')
        if src.startswith('data:image'):
            return extract_price_from_base64_image(src)
    
    # Fallback to text extraction (old method)
    text = el.get_text(strip=True).replace("ج.م", "").replace("$", "").strip()
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
    print(f"Sample prices - Gold 24k sell: {data['gold']['24']['sell']}, Silver 999 sell: {data['silver']['999']['sell']}")

if __name__ == "__main__":
    main()
