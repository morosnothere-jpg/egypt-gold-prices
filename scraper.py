import requests
from bs4 import BeautifulSoup
import json
from datetime import datetime, timezone
import base64
import io
import pytesseract
from PIL import Image
import re
import sys

URL = "https://market.isagha.com/prices"
HEADERS = {"User-Agent": "Mozilla/5.0"}

def cleanup_text(text):
    """Clean up price text by removing currency symbols and whitespace."""
    if not text:
        return None
    # Remove "ج.م" and other non-numeric chars except dot
    cleaned = re.sub(r'[^\d.]', '', text)
    try:
        return float(cleaned)
    except ValueError:
        return None

def extract_price_from_base64_image(base64_string):
    """
    Extracts numeric price from a base64-encoded PNG image using OCR.
    """
    try:
        # Remove header if present
        if "base64," in base64_string:
            base64_string = base64_string.split("base64,")[1]
            
        # Decode base64 to image
        image_data = base64.b64decode(base64_string)
        image = Image.open(io.BytesIO(image_data))
        
        # Preprocess image
        # Convert to grayscale
        image = image.convert('L')
        # Binarize (thresholding) - this often helps with clear text on solid backgrounds
        # You might need to adjust the threshold value (128 is a starting point)
        image = image.point(lambda x: 0 if x < 140 else 255, '1')
        
        # Configure Tesseract
        # --psm 7: Treat the image as a single text line.
        # -c tessedit_char_whitelist=0123456789.: Only recognize numbers and decimal point
        custom_config = r'--psm 7 -c tessedit_char_whitelist=0123456789.'
        
        # Run OCR
        text = pytesseract.image_to_string(image, config=custom_config)
        
        # Clean and parse
        return cleanup_text(text)
        
    except Exception as e:
        print(f"⚠️ OCR Error: {e}", file=sys.stderr)
        return None

def get_price(selector, soup):
    """Extract price using CSS selector, handling both text and base64 images."""
    el = soup.select_one(selector)
    if not el:
        return None
        
    # Check for image with base64 data
    img = el.select_one('img[src^="data:image/"]')
    if img:
        return extract_price_from_base64_image(img['src'])
        
    # Fallback to text
    text = el.get_text(strip=True)
    return cleanup_text(text)

def main():
    print("🔄 Fetching data from", URL)
    try:
        response = requests.get(URL, headers=HEADERS)
        response.raise_for_status()
    except Exception as e:
        print(f"❌ Failed to fetch URL: {e}")
        sys.exit(1)

    soup = BeautifulSoup(response.text, "lxml")

    # Selectors based on provided HTML structure (some IDs differ from previous version)
    # The provided HTML shows table structure. We need to be careful with selectors.
    # The previous selectors were very specific (nth-child). Let's try to keep them if they still work,
    # or update based on the new HTML if possible. 
    # Based on the user's provided HTML snippet, the structure seems to be:
    # #gold > ... > stats
    
    # We will stick to the previous selectors for now but add error checking
    # If selectors fail, we might need to inspect the full page structure again.
    
    data = {
        "gold": {
            "24": {
                "sell": get_price("#gold > div > div:nth-child(1) > div > div.clearfix.stats > div:nth-child(1) > div.value", soup),
                "buy": get_price("#gold > div > div:nth-child(1) > div > div.clearfix.stats > div:nth-child(2) > div.value", soup)
            },
            "22": { # Derived from user HTML snippet if available, or keep existing structure
                "sell": get_price("#gold > div > div:nth-child(4) > div > div.clearfix.stats > div:nth-child(1) > div.value", soup), 
                "buy": get_price("#gold > div > div:nth-child(4) > div > div.clearfix.stats > div:nth-child(2) > div.value", soup)
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

    # Validation: Check if we got at least some data
    valid_prices = 0
    total_prices = 0
    for metal in ["gold", "silver"]:
        for karat in data[metal]:
            for type_ in ["sell", "buy"]:
                total_prices += 1
                if data[metal][karat][type_] is not None:
                    valid_prices += 1
    
    print(f"📊 Extracted {valid_prices}/{total_prices} prices successfully.")

    with open("prices.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print("✅ prices.json updated successfully!")

if __name__ == "__main__":
    main()
