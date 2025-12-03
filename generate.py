import requests
import os
import xml.etree.ElementTree as ET
from io import BytesIO
from PIL import Image, ImageOps, ImageDraw, ImageFont

# --- 1. CONFIGURATION ---

# 1.1. XML Feed Source
FEED_URL = "https://backend.ballzy.eu/et/amfeed/feed/download?id=102&file=cropink_et.xml"
OUTPUT_DIR = "generated_ads" # Directory to save the final images
MAX_PRODUCTS_TO_GENERATE = 5 # Start small to test faster! Change to 1000 later.

# XML Namespaces (required for parsing Google Shopping/Meta Feed XML)
NAMESPACES = {
    'g': 'http://base.google.com/ns/1.0'
}

# 1.2. Figma Design Coordinates (Ballzy Layout)
# You MUST verify these coordinates based on your exported template.
LAYOUT_CONFIG = {
    "canvas_size": (1080, 1080), 
    "template_path": "assets/ballzy_template.png", # Your transparent overlay PNG
    "slots": [
        # Slot 1: Main Pair (Top Left)
        {"x": 50, "y": 200, "w": 600, "h": 500}, 
        # Slot 2: Side Profile (Middle Right)
        {"x": 600, "y": 350, "w": 450, "h": 350},
        # Slot 3: Sole (Bottom Left)
        {"x": 50, "y": 750, "w": 600, "h": 300}
    ],
    "price": {
        "x": 840,   # Center X of the price box
        "y": 880,   # Center Y of the price box
        "color": "#0055FF", 
        "font_size": 80,
        "font_path": "assets/fonts/BallzyFont-Bold.ttf" 
    }
}

# --- 2. IMAGE GENERATION LOGIC ---

def create_ballzy_ad(image_urls, price_text, product_id):
    """Generates the single stylized image based on the Ballzy layout."""
    
    # 1. Load Background Template
    try:
        base = Image.open(LAYOUT_CONFIG["template_path"]).convert("RGBA")
    except FileNotFoundError:
        print(f"ERROR: Template not found at {LAYOUT_CONFIG['template_path']}. Creating a white canvas.")
        base = Image.new('RGBA', LAYOUT_CONFIG["canvas_size"], (255, 255, 255, 255))
    
    # 2. Loop through the 3 Image Slots
    for i, slot in enumerate(LAYOUT_CONFIG["slots"]):
        if i >= len(image_urls): 
            print(f"Warning: Product {product_id} only has {len(image_urls)} images, skipping slot {i+1}")
            continue
            
        url = image_urls[i]
        
        try:
            # Download image
            response = requests.get(url, timeout=10)
            img = Image.open(BytesIO(response.content)).convert("RGBA")
            
            # Smart Fit: Resize image to fit the slot while keeping aspect ratio
            target_size = (slot['w'], slot['h'])
            # We use 'contain' so the whole shoe is visible (will leave empty space if aspect ratio differs)
            fitted_img = ImageOps.contain(img, target_size, method=Image.Resampling.LANCZOS)
            
            # Calculate centering within the slot
            paste_x = slot['x'] + (slot['w'] - fitted_img.width) // 2
            paste_y = slot['y'] + (slot['h'] - fitted_img.height) // 2
            
            # Paste image onto the base
            base.paste(fitted_img, (paste_x, paste_y), fitted_img)

        except Exception as e:
            print(f"Error processing image {url} for product {product_id}: {e}")
            # Fails silently, leaving that area covered by the template

    # 3. Draw the Price
    draw = ImageDraw.Draw(base)
    price_conf = LAYOUT_CONFIG["price"]
    
    # Load Font
    try:
        font = ImageFont.truetype(price_conf["font_path"], price_conf["font_size"])
    except:
        font = ImageFont.load_default() # Fallback

    # Calculate text size to center it perfectly
    _, _, w, h = draw.textbbox((0, 0), price_text, font=font)
    text_x = price_conf["x"] - (w / 2)
    text_y = price_conf["y"] - (h / 2)
    
    draw.text((text_x, text_y), price_text, fill=price_conf["color"], font=font)

    # 4. Save Final Ad
    output_path = os.path.join(OUTPUT_DIR, f"ad_{product_id}.jpg")
    base.convert("RGB").save(output_path, format="JPEG", quality=95)
    print(f"-> Successfully generated: {output_path} (Price: {price_text})")

# --- 3. XML FEED PROCESSING LOGIC ---

def process_feed(url):
    """Downloads the XML feed and iterates through products."""
    
    print(f"Downloading feed from: {url}")
    try:
        feed_response = requests.get(url, timeout=30)
        feed_response.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"FATAL ERROR: Could not download feed. {e}")
        return

    # Create output directory if it doesn't exist
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    # Parse XML
    try:
        # We wrap the response text in BytesIO and then use ET.parse
        root = ET.fromstring(feed_response.content)
    except ET.ParseError as e:
        print(f"FATAL ERROR: Could not parse XML feed. {e}")
        return

    # Look for the channel items (adjust tag based on feed structure)
    # The structure is usually: rss/channel/item
    product_count = 0
    
    # ET.iter() is used to find all 'item' tags regardless of depth
    for item in root.iter('item'): 
        if product_count >= MAX_PRODUCTS_TO_GENERATE:
            print(f"Stopping after generating {MAX_PRODUCTS_TO_GENERATE} products for testing.")
            break
            
        # --- A. Extract Product ID (for file name) ---
        product_id_element = item.find('g:id', NAMESPACES)
        if product_id_element is None:
            # Skip items without an ID
            continue 
        product_id = product_id_element.text.strip()
        
        # --- B. Extract Price ---
        # Prioritize sale_price over price
        price_element = item.find('g:sale_price', NAMESPACES)
        if price_element is None:
            price_element = item.find('g:price', NAMESPACES)

        if price_element is None:
            # Skip if no price is found
            print(f"Skipping product {product_id}: No price found.")
            continue
            
        # Format price (e.g., '12.00 EUR' -> '12.00€')
        raw_price = price_element.text.split()[0]
        formatted_price = f"{raw_price}€"
        
        # --- C. Extract Image Links ---
        image_urls = []
        
        # 1. Main image
        main_image = item.find('g:image_link', NAMESPACES)
        if main_image is not None:
            image_urls.append(main_image.text.strip())

        # 2. Additional images (find up to 2)
        additional_images = item.findall('g:additional_image_link', NAMESPACES)
        for i, img in enumerate(additional_images):
            if i < 2: 
                image_urls.append(img.text.strip())

        # Need at least one image to run the generator
        if not image_urls:
            print(f"Skipping product {product_id}: No images found.")
            continue
        
        # --- D. Generate Image ---
        create_ballzy_ad(image_urls, formatted_price, product_id)
        product_count += 1

# --- 4. EXECUTION ---

if __name__ == "__main__":
    process_feed(FEED_URL)
