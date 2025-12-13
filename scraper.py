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
MIN_GOLD_PRICE = 2000.0   
MIN_SILVER_PRICE = 40.0   

# --- UTILS ---
def cleanup_text(text):
    """Clean up price text by removing currency symbols and whitespace."""
    if not text:
        return None
    # Replace common OCR misinterpretations before stripping
    text = text.replace(',', '.') 
    
    # Handle "5.745" or "5,745" -> "5745" logic
    # If the text has a dot/comma that is followed by 3 digits at the end, it's likely a thousand separator
    # UNLESS it's a small number. But gold prices are > 1000.
    # Safe heuristic: removing all non-digits first, then if original had a decimal point at the very end... 
    # Actually, simplistic approach: "5.745" -> 5745.0
    
    # Remove non-numeric chars except dot
    cleaned = re.sub(r'[^\d.]', '', text)
    
    # If multiple dots, keep last one ONLY if it looks like a decimal (followed by 1 or 2 digits). 
    # Otherwise remove all dots.
    if cleaned.count('.') > 0:
        parts = cleaned.split('.')
        if len(parts[-1]) == 3: # 5.745 -> likely thousand separator
             cleaned = cleaned.replace('.', '')
        elif cleaned.count('.') > 1:
             cleaned = "".join(parts[:-1]) + '.' + parts[-1]
            
    try:
        return float(cleaned)
    except ValueError:
        return None

def process_image_variant(image, variant):
    """Apply different preprocessing based on variant strategy."""
    img = image.copy()
    
    if variant == "standard":
        # Strategy 1: High Contrast + Thickening
        img = img.resize((img.width * 4, img.height * 4), Image.Resampling.LANCZOS)
        img = img.convert('L')
        img = img.point(lambda x: 0 if x < 180 else 255, '1')
        img = img.filter(ImageFilter.MinFilter(3)) # Dilation
        img = ImageOps.expand(img, border=50, fill='white')
        
    elif variant == "no_dilation":
        # Strategy 2: Just clean high res (for when dilation merges digits too much)
        img = img.resize((img.width * 5, img.height * 5), Image.Resampling.BICUBIC)
        img = img.convert('L')
        img = img.point(lambda x: 0 if x < 160 else 255, '1')
        img = ImageOps.expand(img, border=50, fill='white')
        
    elif variant == "lighter_threshold":
        # Strategy 3: Catch faint pixels (Leading '5' issue detection)
        img = img.resize((img.width * 4, img.height * 4), Image.Resampling.LANCZOS)
        img = img.convert('L')
        # Threshold higher (200) means more grey becomes black
        img = img.point(lambda x: 0 if x < 210 else 255, '1') 
        img = ImageOps.expand(img, border=50, fill='white')

    return img

def extract_price_from_base64_image(base64_string):
    """
    Extracts numeric price from a base64-encoded PNG image using OCR.
    Tries multiple strategies to get a plausible number.
    """
    try:
        if "base64," in base64_string:
            base64_string = base64_string.split("base64,")[1]
            
        image_data = base64.b64decode(base64_string)
        original_image = Image.open(io.BytesIO(image_data))
        
        # Handle transparency
        if original_image.mode in ('RGBA', 'LA'):
            background = Image.new('RGB', original_image.size, (255, 255, 255))
            background.paste(original_image, mask=original_image.split()[-1])
            original_image = background
        else:
            original_image = original_image.convert('RGB')
            
        # Try variations until we find a plausible number (or valid format)
        strategies = ["lighter_threshold", "standard", "no_dilation"]
        
        for strategy in strategies:
            processed_img = process_image_variant(original_image, strategy)
            
            custom_config = r'--psm 7 -c tessedit_char_whitelist=0123456789.,'
            text = pytesseract.image_to_string(processed_img, config=custom_config)
            
            result = cleanup_text(text)
            
            # If we got a result, check basic plausibility immediately? 
            # Or just return the first non-None? 
            # In this case, "745" is a result, but it's bad.
            # But the OCR function doesn't know context (Gold vs Silver).
            # So we return the raw number.
            if result is not None:
                return result
                
        return None
        
    except Exception as e:
        print(f"⚠️ OCR Error: {e}", file=sys.stderr)
        return None

def is_price_plausible(metal, price):
    if price is None: return False
    # Range Checks
    if metal == "gold":
        if price < MIN_GOLD_PRICE: return False # 745 < 2000 -> False
        if price > 100000: return False 
    elif metal == "silver":
        if price < MIN_SILVER_PRICE: return False
        if price > 5000: return False
    return True

def validate_data(data):
    """
    Checks if the scraped data is valid AND plausible.
    CRITICAL: Fails validation if ANY Gold price is impossible.
    """
    valid_prices = 0
    total_prices = 0
    suspicious_found = False
    
    # Check Gold
    if "gold" in data:
        for karat, values in data["gold"].items():
            for type_ in ["sell", "buy"]:
                total_prices += 1
                price = values.get(type_)
                if is_price_plausible("gold", price):
                    valid_prices += 1
                else:
                    if price is not None:
                        print(f"⚠️ Suspicious Gold Price detected: {karat}k {type_} = {price} (Expected > {MIN_GOLD_PRICE})")
                        suspicious_found = True # Mark as tainted
                    else:
                        pass # Null is just missing data, not necessarily "suspicious" logic error, but reduces count

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
                        # Silver being wrong is bad, but maybe not block-the-whole-scraping bad?
                        # For now, let's play safe.
                        suspicious_found = True
    
    # STRICT RULE: If we found ANY suspicious (impossible) value, the OCR failed dangerously.
    # In that case, we should declare the data INVALID to force fallback.
    if suspicious_found:
        print("🛑 FAST FAIL: Suspicious prices detected. Rejecting Primary source.")
        return False, valid_prices, total_prices
    
    # Otherwise, check coverage
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
        
        def parse_table_row(row):
            cols = row.find_all('td')
            if len(cols) < 3: return None, None, None
            
            name_text = cols[0].get_text(strip=True)
            
            karat = None
            if "24" in name_text: karat = "24"
            elif "22" in name_text: karat = "22"
            elif "21" in name_text: karat = "21"
            elif "18" in name_text: karat = "18"
            elif "999" in name_text: karat = "999"
            elif "925" in name_text: karat = "925"
            elif "800" in name_text: karat = "800"
            
            sell = cleanup_text(cols[1].get_text())
            buy = cleanup_text(cols[2].get_text())
            
            return karat, sell, buy

        gold_data = {}
        silver_data = {}
        
        for table in soup.find_all("table"):
            for row in table.find_all("tr"):
                karat, sell, buy = parse_table_row(row)
                if karat:
                    item = {"sell": sell, "buy": buy}
                    if int(karat) < 100: 
                        gold_data[karat] = item
                    else:
                        silver_data[karat] = item
                        
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
    
    # Try Primary with Retries
    max_retries = 3
    for attempt in range(1, max_retries + 1):
        print(f"🔄 [Primary] Attempt {attempt}/{max_retries}...")
        data_primary = scrape_isagha()
        
        if data_primary:
            is_valid, valid_count, total = validate_data(data_primary)
            if is_valid:
                print(f"📊 [Primary] Success! Extracted {valid_count}/{total} prices.")
                final_data = data_primary
                break # Success, exit loop
            else:
                print(f"⚠️ [Primary] Validation failed (Attempt {attempt}). Retrying...")
        else:
            print(f"⚠️ [Primary] Connection/Scraping failed (Attempt {attempt}). Retrying...")
            
        if attempt < max_retries:
            time.sleep(2) # Short pause between retries
    
    # Try Backup if Primary failed after all retries
    if not final_data:
        print("❌ [Primary] All attempts failed. Switching to Backup Source...")
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
