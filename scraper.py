import requests
from bs4 import BeautifulSoup
import json
from datetime import datetime, timezone
import re
import base64
from io import BytesIO
from PIL import Image, ImageEnhance, ImageFilter
import pytesseract
import random
import time

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
        # Convert to grayscale
        image = image.convert('L')
        # Resize to improve OCR accuracy
        image = image.resize((image.width*2, image.height*2), Image.LANCZOS)
        # Sharpen and enhance contrast
        image = image.filter(ImageFilter.SHARPEN)
        image = ImageEnhance.Contrast(image).enhance(2.0)
        # Binarize image
        image = image.point(lambda x: 0 if x < 128 else 255, '1')

        # OCR using Tesseract
        custom_config = r'--oem 3 --psm 7 -c tessedit_char_whitelist=0123456789.'
        raw_text = pytesseract.image_to_string(image, config=custom_config)
        print(f"Raw OCR output: '{raw_text}'")

        # Correct common misreads
        raw_text = raw_text.replace('O', '0').replace('l', '1').replace(',', '')
        cleaned = re.sub(r'[^\d.]', '', raw_text)

        if cleaned and cleaned != '.':
            price = float(cleaned)
            if 1 <= price <= 100000:  # Reasonable range
                return price
        return None
    except Exception as e:
        print(f"⚠️ OCR error: {e}")
        return None

def find_price_images_accurate(soup, section_id, karat_text):
    """Find price images for a given karat/purity using improved method"""
    section = soup.find(id=section_id)
    if not section:
        print(f"⚠️  Section '{section_id}' not found")
        return None, None

    all_spans = section.find_all('span')
    for span in all_spans:
        if karat_text in span.get_text(strip=True):
            current = span
            price_container = None
            for _ in range(10):
                current = current.parent
                if current is None:
                    break
                stats_div = current.find('div', class_='clearfix stats') or current.find('div', class_='stats')
                if stats_div:
                    price_container = stats_div
                    break
            if price_container:
                value_divs = price_container.find_all('div', class_='value')
                if len(value_divs) >= 2:
                    sell_img_tag = value_divs[0].find('img', class_='price-cell')
                    buy_img_tag = value_divs[1].find('img', class_='price-cell')
                    if sell_img_tag and buy_img_tag:
                        sell_image = decode_base64_image(sell_img_tag.get('src', ''))
                        buy_image = decode_base64_image(buy_img_tag.get('src', ''))
                        sell_price = ocr_price_from_image(sell_image)
                        buy_price = ocr_price_from_image(buy_image)
                        if sell_price and buy_price:
                            print(f"✓ {section_id} {karat_text}: sell={sell_price}, buy={buy_price}")
                            return sell_price, buy_price
                        else:
                            print(f"⚠️  OCR failed for {section_id} {karat_text}")
    print(f"⚠️  Could not find structure for {section_id} {karat_text}")
    return None, None

def scrape_prices():
    print("🔄 Fetching data from", URL)
    try:
        delay = random.uniform(1, 3)
        print(f"⏳ Waiting {delay:.1f}s before request...")
        time.sleep(delay)
        response = requests.get(URL, headers=get_headers(), timeout=30)
        response.raise_for_status()
        print(f"✓ Status: {response.status_code}")
    except requests.RequestException as e:
        print(f"❌ Failed to fetch URL: {e}")
        raise

    soup = BeautifulSoup(response.text, "html.parser")
    print("\n📊 Extracting prices with OCR...")

    gold_24_sell, gold_24_buy = find_price_images_accurate(soup, "gold", "24")
    gold_21_sell, gold_21_buy = find_price_images_accurate(soup, "gold", "21")
    gold_18_sell, gold_18_buy = find_price_images_accurate(soup, "gold", "18")

    silver_999_sell, silver_999_buy = find_price_images_accurate(soup, "silver", "999")
    silver_925_sell, silver_925_buy = find_price_images_accurate(soup, "silver", "925")
    silver_800_sell, silver_800_buy = find_price_images_accurate(soup, "silver", "800")

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
    elif total_prices < 8:
        print(f"⚠️  Warning: Only {total_prices}/12 prices extracted")

    return data

def main():
    try:
        data = scrape_prices()
        with open("prices.json", "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print("\n✅ prices.json updated successfully!")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        raise

if __name__ == "__main__":
    main()
