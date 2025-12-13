import requests
from bs4 import BeautifulSoup
import json
from datetime import datetime, timezone
import base64
import io
import pytesseract
from PIL import Image, ImageOps, ImageFilter
import re
import sys
import time
import random

# --- CONFIGURATION ---
URL_PRIMARY = "https://market.isagha.com/prices"
URL_BACKUP = "https://safehavenhub.com/pages/%d8%a7%d8%b3%d8%b9%d8%a7%d8%b1-%d8%a7%d9%84%d8%b0%d9%87%d8%a8-%d9%88%d8%a7%d9%84%d9%81%d8%b6%d8%a9"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
}

# --- VALIDATION THRESHOLDS (EGP) ---
# Update these based on rough market expectations to catch OCR errors
MIN_GOLD_PRICE = 2000.0   # Gold 18k is around 4000+, so 2000 is a safe floor
MIN_SILVER_PRICE = 40.0   # Silver is usually > 50

# --- UTILS ---
def cleanup_text(text):
    """Clean up price text by removing currency symbols and whitespace."""
    if not text:
        return None
    # Replace common OCR misinterpretations before stripping
    text = text.replace(',', '.') # massive safe assumption for price data if comma is used as decimal or thousand sep
    # If we have multiple dots, keep only the last one? or remove all but last?
    # Logic: "4.924.25" -> "4924.25"
    if text.count('.') > 1:
        parts = text.split('.')
        # Join all but last with empty string, keep last part as decimal
        text = "".join(parts[:-1]) + '.' + parts[-1]
    
    # Remove non-numeric chars except dot
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
        if "base64," in base64_string:
            base64_string = base64_string.split("base64,")[1]
            
        image_data = base64.b64decode(base64_string)
        image = Image.open(io.BytesIO(image_data))
        
        # 1. Handle transparency (Composite onto white bg)
        if image.mode in ('RGBA', 'LA'):
            background = Image.new('RGB', image.size, (255, 255, 255))
            background.paste(image, mask=image.split()[-1])
            image = background
        else:
            image = image.convert('RGB')
            
        # 2. Upscale significantly (4x)
        # Lanczos is good, but sometimes Nearest is better for sharp pixel fonts. 
        # sticking to Lanczos for now but increasing scale.
        image = image.resize((image.width * 4, image.height * 4), Image.Resampling.LANCZOS)
        
        # 3. Grayscale
        image = image.convert('L')
        
        # 4. Thresholding (Otsu's method is usually better than fixed 160, but let's stick to fixed if lighting is constant)
        # However, making text thicker (Erosion) is key for "missing digits"
        image = image.point(lambda x: 0 if x < 180 else 255, '1') # Increased threshold to capture lighter gray edge pixels
        
        # 5. Dilation (Thickening text)
        # In PIL, MinFilter(3) on a binary image (0=Black, 255=White) will expand the Black areas (0) by looking for min value in 3x3 kernel.
        # This helps connect broken lines in digits like '0' or '6'.
        image = image.filter(ImageFilter.MinFilter(3))

        # 6. Padding
        image = ImageOps.expand(image, border=40, fill='white')
        
        # OCR Config
        # psm 7 = Treat the image as a single text line.
        # psm 8 = Treat the image as a single word.
        # layout is usually a single number, so 7 or 8 works.
        custom_config = r'--psm 7 -c tessedit_char_whitelist=0123456789.,'
        text = pytesseract.image_to_string(image, config=custom_config)
        
        result = cleanup_text(text)
        
        # Retry with looser config if empty
        if result is None:
             # Try PSM 6 (Assume a uniform block of text)
            custom_config_loose = r'--psm 6 -c tessedit_char_whitelist=0123456789.,'
            text = pytesseract.image_to_string(image, config=custom_config_loose)
            result = cleanup_text(text)

        return result
        
    except Exception as e:
        print(f"⚠️ OCR Error: {e}", file=sys.stderr)
        return None

def is_price_plausible(metal, price):
    if price is None: return False
    # Range Checks
    if metal == "gold":
        if price < MIN_GOLD_PRICE: return False # Impossibly low
        if price > 100000: return False # Impossibly high (sanity ceiling)
    elif metal == "silver":
        if price < MIN_SILVER_PRICE: return False
        if price > 5000: return False
    return True

def validate_data(data):
    """
    Checks if the scraped data is valid AND plausible.
    Returns (is_valid, valid_count, total_count).
    """
    valid_prices = 0
    total_prices = 0
    
    # Check Gold
    if "gold" in data:
        for karat, values in data["gold"].items():
            for type_ in ["sell", "buy"]:
                total_prices += 1
                price = values.get(type_)
                if is_price_plausible("gold", price):
                    valid_prices += 1
                else:
                    # Invalid price detected? effectively treat as null for valid_count
                    if price is not None:
                        print(f"⚠️ Suspicious Gold Price detected: {karat}k {type_} = {price}")

    # Check Silver
    if "silver" in data:
        for purity, values in data["silver"].items():
            for type_ in ["sell", "buy"]:
                total_prices += 1
                price = values.get(type_)
                if is_price_plausible("silver", price):
                    valid_prices += 1
                else:
                     if price is not None:
                        print(f"⚠️ Suspicious Silver Price detected: {purity} {type_} = {price}")
    
    # Stricter Rule: We need at least 80% Valid AND Plausible prices
    is_valid = total_prices > 0 and (valid_prices / total_prices) > 0.8
    return is_valid, valid_prices, total_prices

# --- PRIMARY SCRAPER (ISAGHA) ---
def get_price_isagha(selector, soup):
    el = soup.select_one(selector)
    if not el:
        return None
    img = el.select_one('img[src^="data:image/"]')
    if img:
        return extract_price_from_base64_image(img['src'])
    text = el.get_text(strip=True)
    return cleanup_text(text)

def scrape_isagha():
    print("🔄 [Primary] Fetching data from Isagha...")
    try:
        response = requests.get(URL_PRIMARY, headers=HEADERS, timeout=30)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "lxml")

        data = {
            "gold": {
                "24": {
                    "sell": get_price_isagha("#gold > div > div:nth-child(1) > div > div.clearfix.stats > div:nth-child(1) > div.value", soup),
                    "buy": get_price_isagha("#gold > div > div:nth-child(1) > div > div.clearfix.stats > div:nth-child(2) > div.value", soup)
                },

                "21": {
                    "sell": get_price_isagha("#gold > div > div:nth-child(7) > div > div.clearfix.stats > div:nth-child(1) > div.value", soup),
                    "buy": get_price_isagha("#gold > div > div:nth-child(7) > div > div.clearfix.stats > div:nth-child(2) > div.value", soup)
                },
                "18": {
                    "sell": get_price_isagha("#gold > div > div:nth-child(10) > div > div.clearfix.stats > div:nth-child(1) > div.value", soup),
                    "buy": get_price_isagha("#gold > div > div:nth-child(10) > div > div.clearfix.stats > div:nth-child(2) > div.value", soup)
                },
            },
            "silver": {
                "999": {
                    "sell": get_price_isagha("#silver > div > div:nth-child(1) > div > div.clearfix.stats > div:nth-child(1) > div.value", soup),
                    "buy": get_price_isagha("#silver > div > div:nth-child(1) > div > div.clearfix.stats > div:nth-child(2) > div.value", soup)
                },
                "925": {
                    "sell": get_price_isagha("#silver > div > div:nth-child(4) > div > div.clearfix.stats > div:nth-child(1) > div.value", soup),
                    "buy": get_price_isagha("#silver > div > div:nth-child(4) > div > div.clearfix.stats > div:nth-child(2) > div.value", soup)
                },
                "800": {
                    "sell": get_price_isagha("#silver > div > div:nth-child(10) > div > div.clearfix.stats > div:nth-child(1) > div.value", soup),
                    "buy": get_price_isagha("#silver > div > div:nth-child(10) > div > div.clearfix.stats > div:nth-child(2) > div.value", soup)
                },
            }
        }
        return data
    except Exception as e:
        print(f"❌ [Primary] Failed: {e}", file=sys.stderr)
        return None

# --- BACKUP SCRAPER (SAFEHAVEN) ---
def scrape_safehaven():
    print("🔄 [Backup] Fetching data from SafeHaven...")
    try:
        response = requests.get(URL_BACKUP, headers=HEADERS, timeout=30)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "lxml")

        # Parsing logic based on provided HTML
        # Look for tables with known structure
        
        def parse_table_row(row):
            cols = row.find_all('td')
            if len(cols) < 3: return None, None, None
            
            # Col 1: Name (e.g. "عيار 24")
            name_text = cols[0].get_text(strip=True)
            
            # Identify Karat from name
            karat = None
            if "24" in name_text: karat = "24"
            elif "22" in name_text: karat = "22"
            elif "21" in name_text: karat = "21"
            elif "18" in name_text: karat = "18"
            elif "999" in name_text: karat = "999"
            elif "925" in name_text: karat = "925"
            elif "800" in name_text: karat = "800"
            
            # Col 2: Sell, Col 3: Buy
            sell = cleanup_text(cols[1].get_text())
            buy = cleanup_text(cols[2].get_text())
            
            return karat, sell, buy

        gold_data = {}
        silver_data = {}
        
        # Locate all tables and try to parse rows
        for table in soup.find_all("table"):
            for row in table.find_all("tr"):
                karat, sell, buy = parse_table_row(row)
                if karat:
                    item = {"sell": sell, "buy": buy}
                    if int(karat) < 100: # Simple heuristic for Gold vs Silver
                        gold_data[karat] = item
                    else:
                        silver_data[karat] = item
                        
        # Ensure we have the structure even if partial data
        data = {
            "gold": {
                 "24": gold_data.get("24", {"sell": None, "buy": None}),

                 "21": gold_data.get("21", {"sell": None, "buy": None}),
                 "18": gold_data.get("18", {"sell": None, "buy": None}),
            },
            "silver": {
                 "999": silver_data.get("999", {"sell": None, "buy": None}),
                 "925": silver_data.get("925", {"sell": None, "buy": None}),
                 "800": silver_data.get("800", {"sell": None, "buy": None}),
            }
        }
        return data

    except Exception as e:
        print(f"❌ [Backup] Failed: {e}", file=sys.stderr)
        return None

# --- MAIN ---
def main():
    final_data = None
    
    # Try Primary
    data_primary = scrape_isagha()
    if data_primary:
        is_valid, valid_count, total = validate_data(data_primary)
        print(f"📊 [Primary] Extracted {valid_count}/{total} prices.")
        if is_valid:
            final_data = data_primary
        else:
            print("⚠️ [Primary] Data validation failed (too many nulls or suspicious values).")
    
    # Try Backup if Primary failed
    if not final_data:
        print("⚠️ Switching to Backup Source...")
        data_backup = scrape_safehaven()
        if data_backup:
            is_valid, valid_count, total = validate_data(data_backup)
            print(f"📊 [Backup] Extracted {valid_count}/{total} prices.")
            if is_valid:
                final_data = data_backup
            else:
                 print("⚠️ [Backup] Data validation failed.")
    
    # Save Logic
    if final_data:
        final_data["last_updated"] = datetime.now(timezone.utc).isoformat()
        with open("prices.json", "w", encoding="utf-8") as f:
            json.dump(final_data, f, ensure_ascii=False, indent=2)
        print("✅ prices.json updated successfully!")
    else:
        print("❌ All scrapers failed. No data saved.")
        sys.exit(1)

if __name__ == "__main__":
    main()
