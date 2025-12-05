import requests
import os
import xml.etree.ElementTree as ET
from io import BytesIO
from PIL import Image, ImageOps, ImageDraw, ImageFont

# --- 1. CONFIGURATION ---
 
# 1.1. XML Feed Source
FEED_URL = "https://backend.ballzy.eu/et/amfeed/feed/download?id=102&file=cropink_et.xml"
OUTPUT_DIR = "generated_ads" 
MAX_PRODUCTS_TO_GENERATE = 15 # SET TO 3 FOR FINAL TEST! Change this to a high number (e.g., 9999) for production.

# XML Namespaces (required for parsing Google Shopping/Meta Feed XML)
NAMESPACES = {
    'g': 'http://base.google.com/ns/1.0'
}
# Define color constants (you can adjust these hex codes)
NORMAL_PRICE_COLOR = "#0055FF" # Original Ballzy blue
SALE_PRICE_COLOR = "#cc05d1"   # A standard purple color  
# 1.2. Figma Design Layout & Image Fitting
# These coordinates are adjusted based on your latest feedback.
LAYOUT_CONFIG = {
    "canvas_size": (1200, 1200), 
    "template_path": "assets/ballzy_template.png", # Ensure this file is uploaded!
    "slots": [
        # Slot 1: Top Left - Adjusted up and larger
        {"x": 25, "y": 25, "w": 606, "h": 700, "center_y": 0.5}, 
        
        # Slot 2: Middle Right - Adjusted right and larger
        {"x": 656, "y": 305, "w": 522, "h": 624, "center_y": 0.6}, 
        
        # Slot 3: Bottom Left - Adjusted lower and left
        {"x": 25, "y": 823, "w": 606, "h": 350, "center_y": 0.5}
    ],
    "price": {
        "x": 920,   # Adjusted right
        "y": 1050,   # Adjusted lower
        "font_size": 80,
        "font_path": "assets/fonts/BallzyFont-Bold.ttf"
     # 🟢 NEW: Rectangle Dimensions (Matches Slot 2 Width)
        "rect_x0": 656,  # Starting X (left edge of Slot 2)
        "rect_y0": 980,  # Starting Y (Adjusted for position below Slot 2)
        "rect_x1": 1178, # Ending X (656 + 522 = 1178, right edge of Slot 2)
        "rect_y1": 1180, # Ending Y (Bottom edge of canvas/price area)
    }
}

# --- 2. IMAGE GENERATION LOGIC ---

def create_ballzy_ad(image_urls, price_text, product_id, price_color):
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
            
            # Paste image 
            base.paste(fitted_img, (slot['x'], slot['y']), fitted_img)

        except Exception as e:
            print(f"Error processing image {url} for product {product_id}: {e}")

   # 3. Draw the Price
    draw = ImageDraw.Draw(base)
    price_conf = LAYOUT_CONFIG["price"]
    
    # 🟢 NEW: Draw the Colored Rectangle Background
    rect_coords = [
        (price_conf["rect_x0"], price_conf["rect_y0"]),
        (price_conf["rect_x1"], price_conf["rect_y1"])
    ]
    # The 'price_color' is used as the fill color!
    draw.rectangle(rect_coords, fill=price_color) 
    
    # Load Font
    try:
        font = ImageFont.truetype(price_conf["font_path"], price_conf["font_size"])
    except:
        font = ImageFont.load_default() 

    # Calculate text size and position (remains the same)
    _, _, w, h = draw.textbbox((0, 0), price_text, font=font)
    text_x = price_conf["x"] - (w / 2)
    text_y = price_conf["y"] - (h / 2)
    
    # Draw the price text *over* the new rectangle.
    # We will draw the text in WHITE for high contrast over blue/purple.
    draw.text((text_x, text_y), price_text, fill="white", font=font)

    # 4. Save Final Ad
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    output_path = os.path.join(OUTPUT_DIR, f"ad_{product_id}.jpg")
    base.convert("RGB").save(output_path, format="JPEG", quality=95)
    print(f"-> Successfully generated: {output_path} (Price: {price_text}, Color: {price_color})")

# --- 3. XML FEED PROCESSING LOGIC ---

def process_feed(url):
    """Downloads the XML feed, filters products, and iterates through generation."""
    
    print(f"Downloading feed from: {url}")
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

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    product_count = 0
    
    for item in root.iter('item'): 
        if product_count >= MAX_PRODUCTS_TO_GENERATE:
            print(f"Stopping after generating {MAX_PRODUCTS_TO_GENERATE} products for testing.")
            break
            
        product_id_element = item.find('g:id', NAMESPACES)
        if product_id_element is None: continue
        product_id = product_id_element.text.strip()
        
        # --- PRODUCT FILTERING LOGIC ---
        category_element = item.find('g:google_product_category', NAMESPACES)
        is_correct_category = False
        if category_element is not None:
            category_text = category_element.text.strip().lower()
            if "street shoes" in category_text or "boots" in category_text:
                is_correct_category = True
        
        label_element = item.find('custom_label_0', NAMESPACES)
        is_lifestyle = False
        if label_element is not None and label_element.text.strip() == "Lifestyle":
            is_lifestyle = True
            
        if not is_correct_category or not is_lifestyle:
            continue 
            
        # --- Price Extraction and Coloring (FINALIZED) ---
        
        sale_price_element = item.find('g:sale_price', NAMESPACES)
        
        if sale_price_element is not None:
            # SALE PRICE FOUND: Use sale price and PURPLE color
            price_element = sale_price_element
            final_price_color = SALE_PRICE_COLOR
        else:
            # NO SALE PRICE: Use regular price and BLUE color
            price_element = item.find('g:price', NAMESPACES)
            final_price_color = NORMAL_PRICE_COLOR


        if price_element is None: continue
            
        # Price Formatting: Strip .00 if integer, keep decimals otherwise, and append €
        raw_price_str = price_element.text.split()[0]
        
        try:
            price_value = float(raw_price_str)
            if price_value == int(price_value):
                formatted_price = f"{int(price_value)}€" 
            else:
                formatted_price = f"{price_value:.2f}€" 
                
        except ValueError:
            formatted_price = raw_price_str.replace(" EUR", "€")

        # --- Image Link Extraction ---
        image_urls = []
        main_image = item.find('g:image_link', NAMESPACES)
        if main_image is not None:
            image_urls.append(main_image.text.strip())

        additional_images = item.findall('g:additional_image_link', NAMESPACES)
        for i, img in enumerate(additional_images):
            if i < 2: image_urls.append(img.text.strip())

        if not image_urls: continue
        
        # Generate Image (passing the final_price_color)
        create_ballzy_ad(image_urls, formatted_price, product_id, final_price_color)
        product_count += 1

# --- 4. EXECUTION ---

if __name__ == "__main__":
    process_feed(FEED_URL)
