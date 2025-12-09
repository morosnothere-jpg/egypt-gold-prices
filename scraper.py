import requests
from bs4 import BeautifulSoup
import json
from datetime import datetime, timezone
import base64
from PIL import Image, ImageEnhance, ImageFilter
from io import BytesIO
import pytesseract
import re
import numpy as np

URL = "https://market.isagha.com/prices"
HEADERS = {"User-Agent": "Mozilla/5.0"}

def preprocess_image(image):
    """Preprocess image for better OCR accuracy."""
    try:
        # Convert to grayscale
        image = image.convert('L')
        
        # Increase contrast
        enhancer = ImageEnhance.Contrast(image)
        image = enhancer.enhance(2.0)
        
        # Increase sharpness
        enhancer = ImageEnhance.Sharpness(image)
        image = enhancer.enhance(2.0)
        
        # Scale up the image (OCR works better on larger images)
        width, height = image.size
        image = image.resize((width * 3, height * 3), Image.Resampling.LANCZOS)
        
        # Apply threshold to make it pure black and white
        img_array = np.array(image)
        threshold = 128
        img_array = np.where(img_array > threshold, 255, 0).astype(np.uint8)
        image = Image.fromarray(img_array)
        
        return image
    except Exception as e:
        print(f"Error preprocessing image: {e}")
        return image

def extract_price_from_base64_image(base64_string, debug_name=""):
    """Extract price from base64-encoded image using OCR with multiple attempts."""
    try:
        # Remove the data:image/png;base64, prefix if present
        if ',' in base64_string:
            base64_string = base64_string.split(',')[1]
        
        # Decode base64 to image
        image_data = base64.b64decode(base64_string)
        original_image = Image.open(BytesIO(image_data))
        
        # Preprocess the image
        processed_image = preprocess_image(original_image)
        
        # Try multiple OCR configurations
        configs = [
            r'--oem 3 --psm 7 -c tessedit_char_whitelist=0123456789.',
            r'--oem 3 --psm 8 -c tessedit_char_whitelist=0123456789.',
            r'--oem 3 --psm 13 -c tessedit_char_whitelist=0123456789.',
            r'--oem 1 --psm 7 -c tessedit_char_whitelist=0123456789.',
        ]
        
        results = []
        for config in configs:
            try:
                text = pytesseract.image_to_string(processed_image, config=config)
                text = text.strip().replace(' ', '').replace('\n', '').replace(',', '')
                
                # Extract all number patterns
                numbers = re.findall(r'\d+\.?\d*', text)
                if numbers:
                    results.extend([float(n) for n in numbers])
            except:
                continue
        
        if not results:
            print(f"⚠️  No numbers found for {debug_name}")
            return None
        
        # Take the most common result, or the longest number if all different
        # This helps filter out OCR errors
        result_counts = {}
        for r in results:
            result_counts[r] = result_counts.get(r, 0) + 1
        
        # Get the most frequent result
        best_result = max(result_counts, key=result_counts.get)
        
        # Validation: reject obviously wrong values
        # Gold prices should be between 100 and 100000
        # Silver prices should be between 1 and 10000
        if best_result < 0.1 or best_result > 200000:
            print(f"⚠️  Rejected invalid price {best_result} for {debug_name}")
            return None
        
        print(f"✓ Extracted {best_result} for {debug_name} (from {len(results)} attempts)")
        return best_result
        
    except Exception as e:
        print(f"❌ Error extracting price from image {debug_name}: {e}")
        return None

def get_price(selector, soup, debug_name=""):
    """Extract and clean price from either text or base64 image."""
    el = soup.select_one(selector)
    if not el:
        print(f"⚠️  Element not found: {debug_name}")
        return None
    
    # Check if price is in an image
    img = el.select_one('img.price-cell')
    if img and img.get('src'):
        src = img.get('src')
        if src.startswith('data:image'):
            return extract_price_from_base64_image(src, debug_name)
    
    # Fallback to text extraction (old method)
    text = el.get_text(strip=True).replace("ج.م", "").replace("$", "").strip()
    try:
        return float(text)
    except ValueError:
        return None

def main():
    print("🔄 Fetching data from", URL)
    response = requests.get(URL, headers=HEADERS)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "lxml")

    print("\n📊 Extracting prices...")
    data = {
        "gold": {
            "24": {
                "sell": get_price("#gold > div > div:nth-child(1) > div > div.clearfix.stats > div:nth-child(1) > div.value", soup, "Gold 24k Sell"),
                "buy": get_price("#gold > div > div:nth-child(1) > div > div.clearfix.stats > div:nth-child(2) > div.value", soup, "Gold 24k Buy")
            },
            "21": {
                "sell": get_price("#gold > div > div:nth-child(7) > div > div.clearfix.stats > div:nth-child(1) > div.value", soup, "Gold 21k Sell"),
                "buy": get_price("#gold > div > div:nth-child(7) > div > div.clearfix.stats > div:nth-child(2) > div.value", soup, "Gold 21k Buy")
            },
            "18": {
                "sell": get_price("#gold > div > div:nth-child(10) > div > div.clearfix.stats > div:nth-child(1) > div.value", soup, "Gold 18k Sell"),
                "buy": get_price("#gold > div > div:nth-child(10) > div > div.clearfix.stats > div:nth-child(2) > div.value", soup, "Gold 18k Buy")
            },
        },
        "silver": {
            "999": {
                "sell": get_price("#silver > div > div:nth-child(1) > div > div.clearfix.stats > div:nth-child(1) > div.value", soup, "Silver 999 Sell"),
                "buy": get_price("#silver > div > div:nth-child(1) > div > div.clearfix.stats > div:nth-child(2) > div.value", soup, "Silver 999 Buy")
            },
            "925": {
                "sell": get_price("#silver > div > div:nth-child(4) > div > div.clearfix.stats > div:nth-child(1) > div.value", soup, "Silver 925 Sell"),
                "buy": get_price("#silver > div > div:nth-child(4) > div > div.clearfix.stats > div:nth-child(2) > div.value", soup, "Silver 925 Buy")
            },
            "800": {
                "sell": get_price("#silver > div > div:nth-child(10) > div > div.clearfix.stats > div:nth-child(1) > div.value", soup, "Silver 800 Sell"),
                "buy": get_price("#silver > div > div:nth-child(10) > div > div.clearfix.stats > div:nth-child(2) > div.value", soup, "Silver 800 Buy")
            },
        },
        "last_updated": datetime.now(timezone.utc).isoformat()
    }

    with open("prices.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print("\n✅ prices.json updated successfully!")
    print("\n📋 Summary:")
    print(f"   Gold 24k: sell={data['gold']['24']['sell']}, buy={data['gold']['24']['buy']}")
    print(f"   Gold 21k: sell={data['gold']['21']['sell']}, buy={data['gold']['21']['buy']}")
    print(f"   Silver 999: sell={data['silver']['999']['sell']}, buy={data['silver']['999']['buy']}")

if __name__ == "__main__":
    main()
