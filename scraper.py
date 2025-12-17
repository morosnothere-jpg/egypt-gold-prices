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
    
    # Common OCR substitutions (Digits misread as letters)
    text = text.replace('S', '5').replace('s', '5')
    text = text.replace('O', '0').replace('o', '0')
    text = text.replace('I', '1').replace('l', '1')
    text = text.replace('B', '8')
    
    # Replace common OCR misinterpretations before stripping
    text = text.replace(',', '.') 
    
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

from collections import Counter

def extract_price_from_base64_image(base64_string):
    """
    Extracts numeric price from a base64-encoded PNG image using OCR.
    Uses Majority Vote strategy to avoid outliers (e.g. extra noise interpreted as digits).
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
            img_to_process = background
        else:
            img_to_process = original_image.convert('RGB')
            
        # Try variations
        strategies = ["standard", "lighter_threshold", "no_dilation"]
        candidates = []
        
        for strategy in strategies:
            processed_img = process_image_variant(img_to_process, strategy)
            # Use stricter config if possible, but keep whitelist to force digits
            custom_config = r'--psm 7 -c tessedit_char_whitelist=0123456789.,SlBoI'
            
            text = pytesseract.image_to_string(processed_img, config=custom_config)
            result = cleanup_text(text)
            
            if result is not None:
                candidates.append(result)
        
        if candidates:
            # STRATEGY: Majority Vote / Mode
            # If we have [5765, 57655, 5765], we want 5765.
            # If we have [5765, 5765, 5765], we want 5765.
            # If we have [5765, 5766, 5767], we have a problem (Tie).
            
            counts = Counter(candidates)
            most_common = counts.most_common()
            
            # Get the value with the highest count
            best_val, count = most_common[0]
            
            # If there's a tie for first place (e.g. 1 vote each for 3 diff numbers),
            # we prefer the one that came from the 'standard' strategy (first in list).
            # But Counter.most_common preserves insertion order for ties in modern Python? 
            # Not strictly guaranteed to rely on.
            # Let's check for specific outliers: 
            # If the max value is > 5x the min value, and min value is plausible (>20), prefer min.
            # (Fixes the 5765 vs 57655 issue where noise adds a digit)
            
            min_c = min(candidates)
            max_c = max(candidates)
            
            if max_c > 5 * min_c and min_c > 20:
                 # Suspect extra digit error (e.g. 5000 vs 50000)
                 # Unless the 'min' is absurdly low (like 5.0), but we check > 20.
                 return min_c
                 
            return best_val
                
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
def get_price_from_card(card_element):
    """Helper to extract sell/buy prices from a specific gauge card element."""
    try:
        # Select Stats section
        stats = card_element.select_one(".clearfix.stats")
        if not stats: return None, None
        
        # Usually: 
        # Div 1 -> Sell (value, state=بيع)
        # Div 2 -> Buy (value, state=شراء)
        
        # Ensure we target the right columns based on inner text or order
        # The HTML Structure:
        # <div class="col-xs-4"> <div class="value">...</div> <div class="state">بيع</div> </div>
        # <div class="col-xs-4"> <div class="value">...</div> <div class="state">شراء</div> </div>
        
        sell_price = None
        buy_price = None
        
        columns = stats.select(".col-xs-4, .col-sm-4") # Responsive classes might vary
        
        for col in columns:
            state_div = col.select_one(".state")
            val_div = col.select_one(".value")
            
            if state_div and val_div:
                state_text = state_div.get_text(strip=True)
                
                # Extract raw value (image or text)
                raw_val = None
                img = val_div.select_one('img[src^="data:image/"]')
                if img:
                    raw_val = extract_price_from_base64_image(img['src'])
                else:
                    raw_val = cleanup_text(val_div.get_text(strip=True))
                
                if "بيع" in state_text:
                    sell_price = raw_val
                elif "شراء" in state_text:
                    buy_price = raw_val
                    
        return sell_price, buy_price
    except Exception as e:
        print(f"⚠️ Error parsing card: {e}")
        return None, None

def scrape_isagha():
    print("🔄 [Primary] Fetching data from Isagha...")
    try:
        response = requests.get(URL_PRIMARY, headers=HEADERS, timeout=30)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "lxml")

        data = { "gold": {}, "silver": {} }

        # --- DYNAMIC PARSING ---
        # Locate the container for Gold and Silver
        # Based on HTML: <div role="tabpanel" class="tab-pane active in fade" id="gold">
        # and id="silver"
        
        metals = ["gold", "silver"]
        
        for metal in metals:
            container = soup.select_one(f"#{metal}")
            if not container:
                print(f"⚠️ Container #{metal} not found.")
                continue
                
            # Iterate through all product/gauge cards
            # The structure is direct children rows/cols. 
            # We look for divs that act as cards.
            # Best selector: look for elements containing ".isagha-panel" which seems to be the Gauge Card class.
            
            gauge_cards = container.select(".isagha-panel")
            
            for card in gauge_cards:
                # Find the gauge title (e.g. "عيار 24")
                gauge_title_div = card.select_one(".gauge")
                if not gauge_title_div: continue
                
                title_text = gauge_title_div.get_text(strip=True)
                
                # Normalize Title (remove "عيار", whitespace)
                # "عيار 24 " -> "24"
                karat = "".join(filter(str.isdigit, title_text))
                
                if not karat: continue
                
                # Map 999/etc for silver if needed, or just use extracted number
                # Silver usually: "عيار 999", "عيار 925"...
                
                sell, buy = get_price_from_card(card)
                
                # Store
                if metal == "gold" and karat in ["24", "22", "21", "18", "14", "12", "9"]:
                   data["gold"][karat] = {"sell": sell, "buy": buy}
                   
                elif metal == "silver" and karat in ["999", "925", "800"]:
                   data["silver"][karat] = {"sell": sell, "buy": buy}

        # Check if we missed any critical keys, fill with None to match structure
        required_keys = {
            "gold": ["24", "21", "18"], 
            "silver": ["999", "925", "800"]
        }
        
        for metal, keys in required_keys.items():
            for k in keys:
                if k not in data[metal]:
                    data[metal][k] = {"sell": None, "buy": None}

        # Filter out random junk karats if we want strictly the schema (Optional)
        # For now, keeping what we found is fine, but lets ensure structure matches expectation
        
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
