import json
import time
import random
from datetime import datetime, timezone
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from PIL import Image
import pytesseract
import io
import re

URL = "https://market.isagha.com/prices"

def setup_driver():
    """Configure headless Chrome"""
    chrome_options = Options()
    chrome_options.add_argument('--headless=new')
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--window-size=1920,1080')
    
    user_agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    ]
    chrome_options.add_argument(f'user-agent={random.choice(user_agents)}')
    
    driver = webdriver.Chrome(options=chrome_options)
    return driver

def preprocess_image(img):
    """Enhanced preprocessing"""
    img = img.convert('L')
    img = img.resize((img.width * 3, img.height * 3), Image.LANCZOS)
    threshold = 140
    img = img.point(lambda x: 255 if x > threshold else 0, mode='1')
    return img

def ocr_from_element(driver, element, retries=3):
    """OCR from Selenium element screenshot"""
    for attempt in range(retries):
        try:
            png_bytes = element.screenshot_as_png
            img = Image.open(io.BytesIO(png_bytes))
            processed = preprocess_image(img)
            
            custom_config = r'--oem 3 --psm 7 -c tessedit_char_whitelist=0123456789.'
            text = pytesseract.image_to_string(processed, config=custom_config).strip()
            print(f"  Raw OCR: '{text}'")
            
            # Clean OCR mistakes
            text = text.replace('O', '0').replace('o', '0')
            text = text.replace('l', '1').replace('I', '1').replace('|', '1')
            text = text.replace(',', '').replace(' ', '')
            cleaned = re.sub(r'[^\d.]', '', text)
            
            if cleaned and cleaned != '.':
                price = float(cleaned)
                if 1 <= price <= 100000:
                    print(f"  ✓ Extracted: {price}")
                    return price
        except Exception as e:
            print(f"  ⚠️ OCR attempt {attempt+1} failed: {e}")
            time.sleep(0.5)
    
    print("  ❌ OCR failed")
    return None

def find_prices_selenium(driver, section_id, karat_text):
    """Find prices using Selenium with correct selectors"""
    print(f"\n🔍 Looking for {section_id} - {karat_text}")
    
    try:
        # Find section
        section = driver.find_element(By.ID, section_id)
        
        # Find all panels in section
        panels = section.find_elements(By.CSS_SELECTOR, "div.isagha-panel")
        print(f"  Found {len(panels)} panels")
        
        for panel in panels:
            # Check gauge text
            try:
                gauge = panel.find_element(By.CSS_SELECTOR, "div.gauge")
                gauge_text = gauge.text.strip()
                print(f"  Checking: '{gauge_text}'")
                
                if karat_text in gauge_text:
                    print(f"  ✓ Found matching panel!")
                    
                    # Find stats container
                    stats = panel.find_element(By.CSS_SELECTOR, "div.stats")
                    
                    # Find value divs (sell=first, buy=second)
                    value_divs = stats.find_elements(By.CSS_SELECTOR, "div.value")
                    print(f"    Found {len(value_divs)} value divs")
                    
                    if len(value_divs) >= 2:
                        sell_img = value_divs[0].find_element(By.CSS_SELECTOR, "img.price-cell")
                        buy_img = value_divs[1].find_element(By.CSS_SELECTOR, "img.price-cell")
                        
                        print(f"    📸 Found price images")
                        
                        sell_price = ocr_from_element(driver, sell_img)
                        buy_price = ocr_from_element(driver, buy_img)
                        
                        if sell_price and buy_price:
                            print(f"✅ {section_id} {karat_text}: sell={sell_price}, buy={buy_price}")
                            return sell_price, buy_price
            except Exception as e:
                continue
                
    except Exception as e:
        print(f"❌ Error: {e}")
    
    return None, None

def scrape_prices():
    """Main scraping function"""
    driver = None
    
    try:
        print("🚀 Starting Selenium scraper...")
        driver = setup_driver()
        
        time.sleep(random.uniform(2, 4))
        
        print(f"📡 Loading {URL}")
        driver.get(URL)
        
        # Wait for page load
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.ID, "gold"))
        )
        
        print("✓ Page loaded")
        time.sleep(2)
        
        data = {
            "gold": {},
            "silver": {},
            "last_updated": datetime.now(timezone.utc).isoformat()
        }
        
        # Scrape gold
        print("\n📊 Extracting GOLD prices...")
        for karat in ["24", "21", "18"]:
            sell, buy = find_prices_selenium(driver, "gold", karat)
            data["gold"][karat] = {"sell": sell, "buy": buy}
        
        # Scrape silver
        print("\n📊 Extracting SILVER prices...")
        for karat in ["999", "925", "800"]:
            sell, buy = find_prices_selenium(driver, "silver", karat)
            data["silver"][karat] = {"sell": sell, "buy": buy}
        
        # Count successes
        total_prices = sum(
            1 for metal in data.values() if isinstance(metal, dict)
            for karat in metal.values() if isinstance(karat, dict)
            for price in karat.values() if price is not None
        )
        
        print(f"\n📈 Extracted {total_prices}/12 prices")
        
        if total_prices == 0:
            raise ValueError("❌ No prices extracted!")
        elif total_prices < 8:
            print(f"⚠️ Warning: Only {total_prices}/12 prices")
        
        return data
        
    finally:
        if driver:
            driver.quit()

def main():
    try:
        data = scrape_prices()
        
        with open("prices.json", "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        print("\n✅ prices.json updated!")
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        raise

if __name__ == "__main__":
    main()
