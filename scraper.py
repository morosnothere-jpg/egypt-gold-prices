import requests
from bs4 import BeautifulSoup
import json
from datetime import datetime, timezone
import base64
import io
import pytesseract
from PIL import Image, ImageOps
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

# --- UTILS ---
def cleanup_text(text):
    """Clean up price text by removing currency symbols and whitespace."""
    if not text:
        return None
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
        
        # 1. Handle transparency
        if image.mode in ('RGBA', 'LA'):
            background = Image.new('RGB', image.size, (255, 255, 255))
            background.paste(image, mask=image.split()[-1])
            image = background
        else:
            image = image.convert('RGB')
            
        # 2. Upscale (3x)
        image = image.resize((image.width * 3, image.height * 3), Image.Resampling.LANCZOS)
        
        # 3. Grayscale
        image = image.convert('L')
        
        # 4. Thresholding
        image = image.point(lambda x: 0 if x < 160 else 255, '1')
        
        # 5. Padding
        image = ImageOps.expand(image, border=20, fill='white')
        
        # OCR Config
        custom_config = r'--psm 7 -c tessedit_char_whitelist=0123456789.,'
        text = pytesseract.image_to_string(image, config=custom_config)
        
        if not text.strip():
            custom_config_loose = r'--psm 7'
            text = pytesseract.image_to_string(image, config=custom_config_loose)

        return cleanup_text(text)
        
    except Exception as e:
        print(f"⚠️ OCR Error: {e}", file=sys.stderr)
        return None

def validate_data(data):
    """
    Checks if the scraped data is valid (i.e., has enough non-null values).
    Returns (is_valid, valid_count, total_count).
    """
    valid_prices = 0
    total_prices = 0
    for metal in ["gold", "silver"]:
        if metal in data:
            for karat in data[metal]:
                for type_ in ["sell", "buy"]:
                    total_prices += 1
                    if data[metal][karat].get(type_) is not None:
                        valid_prices += 1
    
    # Consider valid if we have > 50% of the data
    is_valid = total_prices > 0 and (valid_prices / total_prices) >= 0.5
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
            print("⚠️ [Primary] Data validation failed (too many nulls).")
    
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
