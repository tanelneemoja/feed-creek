import requests
import os
import xml.etree.ElementTree as ET
from io import BytesIO
from PIL import Image, ImageOps, ImageDraw, ImageFont

# --- 1. CONFIGURATION ---
 
# 1.1. XML Feed Source
FEED_URL = "https://backend.ballzy.eu/et/amfeed/feed/download?id=102&file=cropink_et.xml"
OUTPUT_DIR = "generated_ads" 
MAX_PRODUCTS_TO_GENERATE = 9 # SET TO 3 FOR FINAL TEST! Change this to a high number (e.g., 9999) for production.

# XML Namespaces (required for parsing Google Shopping/Meta Feed XML)
NAMESPACES = {
    'g': 'http://base.google.com/ns/1.0'
}
  
# 1.2. Figma Design Layout & Image Fitting
# These coordinates are adjusted based on your latest feedback.
LAYOUT_CONFIG = {
    "canvas_size": (1200, 1200), 
    "template_path": "assets/ballzy_template.png", # Ensure this file is uploaded!
    "slots": [
        # Slot 1: Top Left - Adjusted up and larger
        {"x": 50, "y": 90, "w": 550, "h": 550, "center_y": 0.5}, 
        
        # Slot 2: Middle Right - Adjusted right and larger
        {"x": 670, "y": 400, "w": 500, "h": 400, "center_y": 0.6}, 
        
        # Slot 3: Bottom Left - Adjusted lower and left
        {"x": 50, "y": 880, "w": 550, "h": 280, "center_y": 0.6}
    ],
    "price": {
        "x": 920,   # Adjusted right
        "y": 1050,   # Adjusted lower
        "color": "#0055FF", 
        "font_size": 80,
        "font_path": "assets/fonts/BallzyFont-Bold.ttf" # Ensure this file is uploaded!
    }
}

# --- 2. IMAGE GENERATION LOGIC ---

def create_ballzy_ad(image_urls, price_text, product_id):
    """Generates the single stylized image based on the Ballzy layout."""
    
    # 1. Load Background Template
    try:
        base = Image.open(LAYOUT_CONFIG["template_path"]).convert("RGBA")
    except FileNotFoundError:
        print(f"ERROR: Template not found. Creating white canvas.")
        base = Image.new('RGBA', LAYOUT_CONFIG["canvas_size"], (255, 255, 255, 255))
        
    # 2. Loop through the 3 Image Slots
    for i, slot in enumerate(LAYOUT_CONFIG["slots"]):
        if i >= len(image_urls): 
            continue
            
        url = image_urls[i]
        
        try:
            response = requests.get(url, timeout=10)
            img = Image.open(BytesIO(response.content)).convert("RGBA")
            
            target_size = (slot['w'], slot['h'])
            
            # IMPROVED FITTING: ImageOps.fit (Cover method) with dynamic centering
            fitted_img = ImageOps.fit(
                img, 
                target_size, 
                method=Image.Resampling.LANCZOS, 
                centering=(0.5, slot.get("center_y", 0.5))
            )
            
            # Paste image (it's already the exact size of the slot)
            base.paste(fitted_img, (slot['x'], slot['y']), fitted_img)

        except Exception as e:
            print(f"Error processing image {url} for product {product_id}: {e}")

    # 3. Draw the Price
    draw = ImageDraw.Draw(base)
    price_conf = LAYOUT_CONFIG["price"]
    
    try:
        font = ImageFont.truetype(price_conf["font_path"], price_conf["font_size"])
    except:
        font = ImageFont.load_default() 

    _, _, w, h = draw.textbbox((0, 0), price_text, font=font)
    text_x = price_conf["x"] - (w / 2)
    text_y = price_conf["y"] - (h / 2)
    
    draw.text((text_x, text_y), price_text, fill=price_conf["color"], font=font)

    # 4. Save Final Ad
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    output_path = os.path.join(OUTPUT_DIR, f"ad_{product_id}.jpg")
    base.convert("RGB").save(output_path, format="JPEG", quality=95)
    print(f"-> Successfully generated: {output_path} (Price: {price_text})")

# --- 3. XML FEED PROCESSING LOGIC ---

def process_feed(url):
    """Downloads the XML feed, filters products, and iterates through generation."""
    
    print(f"Downloading feed from: {url}")
    # ... (code for downloading feed remains the same) ...
    try:
        feed_response = requests.get(url, timeout=30)
        feed_response.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"FATAL ERROR: Could not download feed. {e}")
        return

    try:
        root = ET.fromstring(feed_response.content)
    except ET.ParseError as e:
        print(f"FATAL ERROR: Could not parse XML feed. {e}")
        return

    # Create output directory if it doesn't exist
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    product_count = 0
    
    for item in root.iter('item'): 
        if product_count >= MAX_PRODUCTS_TO_GENERATE:
            print(f"Stopping after generating {MAX_PRODUCTS_TO_GENERATE} products for testing.")
            break
            
        product_id_element = item.find('g:id', NAMESPACES)
        if product_id_element is None: continue
        product_id = product_id_element.text.strip()
        
        # -------------------------------------------------------------------
        # 🟢 PRODUCT FILTERING LOGIC (NEW)
        # -------------------------------------------------------------------
        
        # 1. Check Google Product Category (must contain "Street Shoes" OR "Boots")
        category_element = item.find('g:google_product_category', NAMESPACES)
        is_correct_category = False
        if category_element is not None:
            category_text = category_element.text.strip().lower()
            if "street shoes" in category_text or "boots" in category_text:
                is_correct_category = True
        
        # 2. Check Custom Label 0 (must exactly equal "Lifestyle")
        label_element = item.find('custom_label_0', NAMESPACES)
        is_lifestyle = False
        if label_element is not None and label_element.text.strip() == "Lifestyle":
            is_lifestyle = True
            
        # If either condition is FALSE, skip this product
        if not is_correct_category or not is_lifestyle:
            # print(f"Skipping product {product_id}: Failed category/label filter.")
            continue 
            
        # -------------------------------------------------------------------
        # 3. Proceed with Price Extraction and Image Link Extraction
        # -------------------------------------------------------------------
        
        # (Price extraction logic remains the same)
        price_element = item.find('g:sale_price', NAMESPACES)
        if price_element is None:
            price_element = item.find('g:price', NAMESPACES)

        if price_element is None: continue
            
        raw_price_str = price_element.text.split()[0]
        
        try:
            price_value = float(raw_price_str)
            if price_value == int(price_value):
                formatted_price = f"{int(price_value)}€" 
            else:
                formatted_price = f"{price_value:.2f}€" 
                
        except ValueError:
            formatted_price = raw_price_str.replace(" EUR", "€")

        # (Image Link Extraction logic remains the same)
        image_urls = []
        main_image = item.find('g:image_link', NAMESPACES)
        if main_image is not None:
            image_urls.append(main_image.text.strip())

        additional_images = item.findall('g:additional_image_link', NAMESPACES)
        for i, img in enumerate(additional_images):
            if i < 2: image_urls.append(img.text.strip())

        if not image_urls: continue
        
        # Generate Image
        create_ballzy_ad(image_urls, formatted_price, product_id)
        product_count += 1
# --- 4. EXECUTION ---

if __name__ == "__main__":
    process_feed(FEED_URL)
