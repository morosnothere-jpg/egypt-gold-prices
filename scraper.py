import requests
from bs4 import BeautifulSoup
import json
from datetime import datetime, timezone
import re
import base64
from io import BytesIO
from PIL import Image
import pytesseract
import random

# Configuration
URL = "https://market.isagha.com/prices"

# Rotating User-Agents (looks like different browsers/devices)
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]

def get_headers():
    """Generate realistic headers with random User-Agent"""
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,ar;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Cache-Control": "max-age=0",
    }

def decode_base64_image(base64_string):
    """Decode base64 image string to PIL Image"""
    try:
        # Remove data:image/png;base64, prefix if present
        if 'base64,' in base64_string:
            base64_string = base64_string.split('base64,')[1]
        
        image_data = base64.b64decode(base64_string)
        image = Image.open(BytesIO(image_data))
        return image
    except Exception as e:
        print(f"⚠️  Error decoding image: {e}")
        return None

def ocr_price_from_image(image):
    """Extract price number from image using OCR"""
    if image is None:
        return None
    
    try:
        # Convert to grayscale for better OCR
        image = image.convert('L')
        
        # OCR configuration optimized for numbers
        custom_config = r'--oem 3 --psm 7 -c tessedit_char_whitelist=0123456789.'
        text = pytesseract.image_to_string(image, config=custom_config)
        
        # Extract number from OCR result
        text = text.strip()
        # Remove any non-numeric characters except decimal point
        cleaned = re.sub(r'[^\d.]', '', text)
        
        if cleaned:
            return float(cleaned)
        return None
    except Exception as e:
        print(f"⚠️  OCR error: {e}")
        return None

def find_price_images(soup, section_id, karat_text):
    """
    Find price images for a specific karat/purity in a section
    Returns tuple: (sell_price, buy_price)
    """
    section = soup.find(id=section_id)
    if not section:
        print(f"⚠️  Section '{section_id}' not found")
        return None, None
    
    # Find all cards/containers
    all_divs = section.find_all('div', recursive=True)
    
    for div in all_divs:
        div_text = div.get_text()
        
        # Check if this div contains our karat/purity
        if karat_text in div_text:
            # Find all img tags with class 'price-cell' in this div
            price_images = div.find_all('img', class_='price-cell')
            
            if len(price_images) >= 2:
                # First image = sell, Second image = buy
                sell_img = price_images[0].get('src', '')
                buy_img = price_images[1].get('src', '')
                
                # Decode and OCR
                sell_image = decode_base64_image(sell_img)
                buy_image = decode_base64_image(buy_img)
                
                sell_price = ocr_price_from_image(sell_image)
                buy_price = ocr_price_from_image(buy_image)
                
                if sell_price and buy_price:
                    print(f"✓ {section_id} {karat_text}: sell={sell_price}, buy={buy_price}")
                    return sell_price, buy_price
                else:
                    print(f"⚠️  Failed OCR for {section_id} {karat_text}")
    
    print(f"⚠️  Could not find images for {section_id} {karat_text}")
    return None, None

def scrape_prices():
    """Main scraping function with OCR"""
    print("🔄 Fetching data from", URL)
    
    try:
        # Add random delay before request (1-3 seconds)
        delay = random.uniform(1, 3)
        print(f"⏳ Waiting {delay:.1f}s before request...")
        import time
        time.sleep(delay)
        
        response = requests.get(URL, headers=get_headers(), timeout=30)
        response.raise_for_status()
        print(f"✓ Status: {response.status_code}")
        
    except requests.RequestException as e:
        print(f"❌ Failed to fetch URL: {e}")
        raise
    
    soup = BeautifulSoup(response.text, "html.parser")
    
    print("\n📊 Extracting prices with OCR...")
    
    # Extract gold prices
    gold_24_sell, gold_24_buy = find_price_images(soup, "gold", "24")
    gold_21_sell, gold_21_buy = find_price_images(soup, "gold", "21")
    gold_18_sell, gold_18_buy = find_price_images(soup, "gold", "18")
    
    # Extract silver prices
    silver_999_sell, silver_999_buy = find_price_images(soup, "silver", "999")
    silver_925_sell, silver_925_buy = find_price_images(soup, "silver", "925")
    silver_800_sell, silver_800_buy = find_price_images(soup, "silver", "800")
    
    # Build data structure
    data = {
        "gold": {
            "24": {"sell": gold_24_sell, "buy": gold_24_buy},
            "21": {"sell": gold_21_sell, "buy": gold_21_buy},
            "18": {"sell": gold_18_sell, "buy": gold_18_buy},
        },
        "silver": {
            "999": {"sell": silver_999_sell, "buy": silver_999_buy},
            "925": {"sell": silver_925_sell, "buy": silver_925_buy},
            "800": {"sell": silver_800_sell, "buy": silver_800_buy},
        },
        "last_updated": datetime.now(timezone.utc).isoformat()
    }
    
    # Validation
    total_prices = sum(
        1 for metal in data.values() 
        if isinstance(metal, dict)
        for karat in metal.values()
        if isinstance(karat, dict)
        for price in karat.values()
        if price is not None
    )
    
    print(f"\n📈 Extracted {total_prices}/12 prices successfully")
    
    if total_prices == 0:
        raise ValueError("❌ Failed to extract any prices!")
    elif total_prices < 12:
        print(f"⚠️  Warning: Only {total_prices}/12 prices extracted")
    
    return data

def main():
    try:
        data = scrape_prices()
        
        # Save to JSON
        with open("prices.json", "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        print("\n✅ prices.json updated successfully!")
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        raise

if __name__ == "__main__":
    main()
