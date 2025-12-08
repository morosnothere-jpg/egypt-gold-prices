import json
import time
import random
from datetime import datetime, timezone
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from PIL import Image, ImageEnhance, ImageFilter
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
    chrome_options.add_argument('--disable-blink-features=AutomationControlled')
    chrome_options.add_argument('--window-size=1920,1080')
    
    user_agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    ]
    chrome_options.add_argument(f'user-agent={random.choice(user_agents)}')
    
    driver = webdriver.Chrome(options=chrome_options)
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    
    return driver

def preprocess_image(img):
    """Enhanced preprocessing with multiple techniques"""
    # Convert to grayscale
    img = img.convert('L')
    
    # Scale up 4x for better OCR
    img = img.resize((img.width * 4, img.height * 4), Image.LANCZOS)
    
    # Enhance contrast
    img = ImageEnhance.Contrast(img).enhance(3.0)
    
    # Sharpen
    img = img.filter(ImageFilter.SHARPEN)
    
    # Binary threshold (lower threshold to capture more text)
    img = img.point(lambda x: 255 if x > 130 else 0, mode='1')
    
    return img

def ocr_from_element(driver, element, retries=5):
    """OCR from Selenium element with multiple attempts and configs"""
    configs = [
        r'--oem 1 --psm 7 -c tessedit_char_whitelist=0123456789.',
        r'--oem 3 --psm 7 -c tessedit_char_whitelist=0123456789.',
        r'--oem 1 --psm 8 -c tessedit_char_whitelist=0123456789.',
        r'--oem 3 --psm 8 -c tessedit_char_whitelist=0123456789.',
        r'--oem 1 --psm 13 -c tessedit_char_whitelist=0123456789.',
    ]
    
    for attempt in range(retries):
        try:
            # Take fresh screenshot each time
            png_bytes = element.screenshot_as_png
            img = Image.open(io.BytesIO(png_bytes))
            
            # Try different preprocessing on different attempts
            if attempt < 3:
                processed = preprocess_image(img)
            else:
                # Alternative preprocessing for later attempts
                processed = img.convert('L')
                processed = processed.resize((processed.width * 3, processed.height * 3), Image.LANCZOS)
                processed = ImageEnhance.Contrast(processed).enhance(2.5)
                processed = processed.point(lambda x: 255 if x > 140 else 0, mode='1')
            
            # Use different config for each attempt
            config = configs[attempt % len(configs)]
            text = pytesseract.image_to_string(processed, config=config).strip()
            
            if attempt == 0 or text:  # Only print on first attempt or if we got text
                print(f"  OCR attempt {attempt+1}: '{text}'")
            
            # Clean OCR mistakes
            text = text.replace('O', '0').replace('o', '0')
            text = text.replace('l', '1').replace('I', '1').replace('|', '1')
            text = text.replace('S', '5').replace('s', '5')
            text = text.replace('Z', '2').replace('z', '2')
            text = text.replace(',', '').replace(' ', '').replace('\n', '')
            cleaned = re.sub(r'[^\d.]', '', text)
            
            if cleaned and cleaned != '.' and cleaned.count('.') <= 1:
                try:
                    price = float(cleaned)
                    if 1 <= price <= 100000:
                        print(f"  ✓ Extracted: {price}")
                        return price
                except ValueError:
                    continue
                    
        except Exception as e:
            print(f"  ⚠️ OCR attempt {attempt+1} error: {e}")
        
        time.sleep(0.3)
    
    print("  ❌ OCR failed after all attempts")
    return None

def find_prices_selenium(driver, section_id, karat_text):
    """Find prices using Selenium with correct selectors"""
    print(f"\n🔍 Looking for {section_id} - عيار {karat_text}")
    
    try:
        # Find section
        section = driver.find_element(By.ID, section_id)
        
        # Find all panels in section
        panels = section.find_elements(By.CSS_SELECTOR, "div.isagha-panel")
        print(f"  Found {len(panels)} panels in section")
        
        for i, panel in enumerate(panels):
            try:
                # Check gauge text
                gauge = panel.find_element(By.CSS_SELECTOR, "div.gauge")
                gauge_text = gauge.text.strip()
                print(f"  Panel {i+1} gauge: '{gauge_text}'")
                
                # Match karat text (handle both Arabic and English)
                if karat_text in gauge_text or f"عيار {karat_text}" in gauge_text:
                    print(f"  ✓ Found matching panel!")
                    
                    # Find stats container
                    stats = panel.find_element(By.CSS_SELECTOR, "div.stats")
                    
                    # Find value divs (sell=first, buy=second)
                    value_divs = stats.find_elements(By.CSS_SELECTOR, "div.value")
                    print(f"    Found {len(value_divs)} value divs")
                    
                    if len(value_divs) >= 2:
                        # Scroll element into view for better screenshot
                        driver.execute_script("arguments[0].scrollIntoView(true);", panel)
                        time.sleep(0.5)
                        
                        sell_img = value_divs[0].find_element(By.CSS_SELECTOR, "img.price-cell")
                        buy_img = value_divs[1].find_element(By.CSS_SELECTOR, "img.price-cell")
                        
                        print(f"    📸 Extracting sell price...")
                        sell_price = ocr_from_element(driver, sell_img)
                        
                        print(f"    📸 Extracting buy price...")
                        buy_price = ocr_from_element(driver, buy_img)
                        
                        if sell_price and buy_price:
                            print(f"✅ {section_id} {karat_text}: sell={sell_price}, buy={buy_price}")
                            return sell_price, buy_price
                        elif sell_price or buy_price:
                            print(f"⚠️ Partial success: sell={sell_price}, buy={buy_price}")
                            return sell_price, buy_price
                            
            except Exception as e:
                print(f"  ⚠️ Error in panel {i+1}: {e}")
                continue
                
    except Exception as e:
        print(f"❌ Error finding section: {e}")
    
    return None, None

def scrape_prices():
    """Main scraping function"""
    driver = None
    
    try:
        print("🚀 Starting Selenium scraper...")
        driver = setup_driver()
        
        # Random delay
        delay = random.uniform(2, 5)
        print(f"⏳ Waiting {delay:.1f}s before loading...")
        time.sleep(delay)
        
        print(f"📡 Loading {URL}")
        driver.get(URL)
        
        # Wait for page load
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.ID, "gold"))
        )
        
        print("✓ Page loaded successfully")
        time.sleep(2)
        
        data = {
            "gold": {},
            "silver": {},
            "last_updated": datetime.now(timezone.utc).isoformat()
        }
        
        # Scrape gold prices
        print("\n" + "="*50)
        print("📊 EXTRACTING GOLD PRICES")
        print("="*50)
        for karat in ["24", "21", "18"]:
            sell, buy = find_prices_selenium(driver, "gold", karat)
            data["gold"][karat] = {"sell": sell, "buy": buy}
            time.sleep(1)  # Small delay between extractions
        
        # Scrape silver prices
        print("\n" + "="*50)
        print("📊 EXTRACTING SILVER PRICES")
        print("="*50)
        for karat in ["999", "925", "800"]:
            sell, buy = find_prices_selenium(driver, "silver", karat)
            data["silver"][karat] = {"sell": sell, "buy": buy}
            time.sleep(1)
        
        # Count successes
        total_prices = sum(
            1 for metal in data.values() if isinstance(metal, dict)
            for karat in metal.values() if isinstance(karat, dict)
            for price in karat.values() if price is not None
        )
        
        print("\n" + "="*50)
        print(f"📈 FINAL RESULT: Extracted {total_prices}/12 prices")
        print("="*50)
        
        if total_prices == 0:
            raise ValueError("❌ Failed to extract any prices!")
        elif total_prices < 6:
            print(f"⚠️ Warning: Only {total_prices}/12 prices extracted")
        
        return data
        
    finally:
        if driver:
            print("\n🔒 Closing browser...")
            driver.quit()

def main():
    try:
        data = scrape_prices()
        
        with open("prices.json", "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        print("\n✅ prices.json updated successfully!")
        
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        raise

if __name__ == "__main__":
    main()
