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

URL = "https://market.isagha.com/prices"

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
    try:
        if 'base64,' in base64_string:
            base64_string = base64_string.split('base64,')[1]
        return Image.open(BytesIO(base64.b64decode(base64_string)))
    except Exception as e:
        print(f"⚠️ Error decoding image: {e}")
        return None

def preprocess_image(img):
    """Resize, sharpen, enhance, binarize"""
    img = img.convert('L')  # grayscale
    img = img.resize((img.width*2, img.height*2), Image.LANCZOS)
    img = img.filter(ImageFilter.SHARPEN)
    img = ImageEnhance.Contrast(img).enhance(2.0)
    img = img.point(lambda x: 0 if x < 128 else 255, '1')
    return img

def ocr_price_from_image(img, max_retries=3):
    if img is None:
        return None
    for attempt in range(max_retries):
        try:
            processed = preprocess_image(img)
            custom_config = r'--oem 3 --psm 7 -c tessedit_char_whitelist=0123456789.'
            raw = pytesseract.image_to_string(processed, config=custom_config).strip()
            print(f"Raw OCR output: '{raw}'")
            raw = raw.replace('O', '0').replace('l', '1').replace('I','1').replace(',', '')
            cleaned = re.sub(r'[^\d.]', '', raw)
            if cleaned and cleaned != '.':
                price = float(cleaned)
                if 1 <= price <= 100000:
                    return price
        except Exception as e:
            print(f"⚠️ OCR attempt {attempt+1} failed: {e}")
        time.sleep(0.1)  # small delay between retries
    print("⚠️ OCR failed completely for this image")
    return None

def find_price_images_accurate(soup, section_id, karat_text):
    section = soup.find(id=section_id)
    if not section:
        print(f"⚠️ Section '{section_id}' not found")
        return None, None
    for span in section.find_all('span'):
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
                        sell_img = decode_base64_image(sell_img_tag.get('src',''))
                        buy_img = decode_base64_image(buy_img_tag.get('src',''))
                        sell_price = ocr_price_from_image(sell_img)
                        buy_price = ocr_price_from_image(buy_img)
                        if sell_price and buy_price:
                            print(f"✓ {section_id} {karat_text}: sell={sell_price}, buy={buy_price}")
                            return sell_price, buy_price
    return None, None

def scrape_prices():
    print("🔄 Fetching data from", URL)
    try:
        time.sleep(random.uniform(1,3))
        response = requests.get(URL, headers=get_headers(), timeout=30)
        response.raise_for_status()
        print(f"✓ Status: {response.status_code}")
    except Exception as e:
        print(f"❌ Failed to fetch URL: {e}")
        raise

    soup = BeautifulSoup(response.text, "html.parser")
    print("\n📊 Extracting prices with OCR...")

    data = {
        "gold": {},
        "silver": {},
        "last_updated": datetime.now(timezone.utc).isoformat()
    }

    for karat in ["24","21","18"]:
        sell, buy = find_price_images_accurate(soup, "gold", karat)
        data["gold"][karat] = {"sell": sell, "buy": buy}

    for karat in ["999","925","800"]:
        sell, buy = find_price_images_accurate(soup, "silver", karat)
        data["silver"][karat] = {"sell": sell, "buy": buy}

    total_prices = sum(
        1 for metal in data.values() if isinstance(metal, dict)
        for karat in metal.values() if isinstance(karat, dict)
        for price in karat.values() if price is not None
    )
    print(f"\n📈 Extracted {total_prices}/12 prices successfully")
    if total_prices == 0:
        raise ValueError("❌ Failed to extract any prices!")
    elif total_prices < 8:
        print(f"⚠️ Warning: Only {total_prices}/12 prices extracted")
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
