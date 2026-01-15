import requests
import os
import xml.etree.ElementTree as ET
from io import BytesIO
from PIL import Image, ImageOps, ImageDraw, ImageFont
import csv
import re
import html
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib 
import glob

# --- 1. CONFIGURATION ---
# Dynamically locate assets folder regardless of where the script runs
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ASSETS_DIR = os.path.join(BASE_DIR, "assets")
SVG_LAYOUT_PATH = os.path.join(ASSETS_DIR, "ballzy_layout.svg")
PNG_TEMPLATE_PATH = os.path.join(ASSETS_DIR, "ballzy_template.png")
FONT_PATH = os.path.join(ASSETS_DIR, "fonts", "poppins.medium.ttf")

OUTPUT_DIR = os.path.join(BASE_DIR, "generated_ads")
MAX_PRODUCTS_TO_GENERATE = 100 # Adjust as needed
TEMP_DOWNLOAD_DIR = "temp_xml_feeds" 

# Brand Colors
NORMAL_PRICE_COLOR = "#0055FF"
SALE_PRICE_COLOR = "#cc02d2"

COUNTRY_CONFIGS = {
    "EE": {"feed_url": "https://backend.ballzy.eu/et/amfeed/feed/download?id=102&file=cropink_et.xml", "currency": "EUR", "google_feed_required": True},
    "LV": {"feed_url": "https://backend.ballzy.eu/lv/amfeed/feed/download?id=104&file=cropink_lv.xml", "currency": "EUR", "google_feed_required": True},
    "LT": {"feed_url": "https://backend.ballzy.eu/lt/amfeed/feed/download?id=105&file=cropink_lt.xml", "currency": "EUR", "google_feed_required": True},
    "FI": {"feed_url": "https://backend.ballzy.eu/fi/amfeed/feed/download?id=103&file=cropink_fi.xml", "currency": "EUR", "google_feed_required": False}
}

GITHUB_PAGES_BASE_URL = "https://tanelneemoja.github.io/feed-creek/generated_ads"
NAMESPACES = {'g': 'http://base.google.com/ns/1.0'}

# Global variable to hold the SVG layout coordinates
DYNAMIC_LAYOUT = {}

# --- 2. HELPER FUNCTIONS ---

def get_layout_from_svg(svg_path):
    """Parses SVG to find rectangles with IDs: slot_0, slot_1, slot_2, price_border, price_target."""
    if not os.path.exists(svg_path):
        print(f"CRITICAL ERROR: SVG Layout not found at {svg_path}")
        return None

    print(f"Parsing SVG Layout from {svg_path}...")
    tree = ET.parse(svg_path)
    root = tree.getroot()
    
    # Helper to find elements by ID regardless of SVG namespace
    def find_by_id(id_val):
        return root.find(f".//*[@id='{id_val}']")

    layout = {"slots": [], "price": {}}

    # Extract Slots (Sneaker positions)
    for i in range(3):
        elem = find_by_id(f"slot_{i}")
        if elem is not None:
            layout["slots"].append({
                "x": int(float(elem.get('x', 0))),
                "y": int(float(elem.get('y', 0))),
                "w": int(float(elem.get('width', 0))),
                "h": int(float(elem.get('height', 0)))
            })

    # Extract Price Box Border
    border = find_by_id("price_border")
    if border is not None:
        bx = int(float(border.get('x', 0)))
        by = int(float(border.get('y', 0)))
        layout["price"]["rect_x0"] = bx
        layout["price"]["rect_y0"] = by
        layout["price"]["rect_x1"] = bx + int(float(border.get('width', 0)))
        layout["price"]["rect_y1"] = by + int(float(border.get('height', 0)))

    # Extract Price Text Anchor (Center of this rectangle)
    target = find_by_id("price_target")
    if target is not None:
        layout["price"]["center_x"] = int(float(target.get('x', 0))) + (int(float(target.get('width', 0))) / 2)
        layout["price"]["center_y"] = int(float(target.get('y', 0))) + (int(float(target.get('height', 0))) / 2)
    
    return layout

def get_template_file_hash():
    if not os.path.exists(PNG_TEMPLATE_PATH): return "notfound"
    hasher = hashlib.sha1()
    with open(PNG_TEMPLATE_PATH, 'rb') as f:
        while chunk := f.read(8192): hasher.update(chunk)
    return hasher.hexdigest()[:8]

def download_feed_xml(country_code, url):
    os.makedirs(TEMP_DOWNLOAD_DIR, exist_ok=True)
    file_path = os.path.join(TEMP_DOWNLOAD_DIR, f"{country_code.lower()}_feed.xml")
    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        with open(file_path, 'wb') as f: f.write(resp.content)
        return file_path
    except Exception as e:
        print(f"Error downloading {country_code}: {e}")
        return None

def create_ballzy_ad(image_urls, price_text, product_id, price_color, data_hash):
    """Generates the single stylized image based on SVG coordinates."""
    output_path = os.path.join(OUTPUT_DIR, f"ad_{product_id}_{data_hash}.jpg")
    if os.path.exists(output_path): return output_path

    try:
        base = Image.open(PNG_TEMPLATE_PATH).convert("RGBA")
    except:
        base = Image.new('RGBA', (1200, 1200), (255, 255, 255, 255))
        
    # 1. Paste Images into SVG slots
    for i, slot in enumerate(DYNAMIC_LAYOUT["slots"]):
        if i >= len(image_urls): continue # Skip if no image for this slot
        try:
            resp = requests.get(image_urls[i], timeout=10)
            img = Image.open(BytesIO(resp.content)).convert("RGBA")
            fitted_img = ImageOps.fit(img, (slot['w'], slot['h']), Image.Resampling.LANCZOS)
            base.paste(fitted_img, (slot['x'], slot['y']), fitted_img)
        except: continue

    # 2. Draw Price Box using SVG coordinates
    draw = ImageDraw.Draw(base)
    p = DYNAMIC_LAYOUT.get("price", {})
    if "rect_x0" in p:
        draw.rectangle([(p["rect_x0"], p["rect_y0"]), (p["rect_x1"], p["rect_y1"])], outline=price_color, width=6)
    
    # 3. Draw Price Text (Centered in SVG target)
    try:
        font = ImageFont.truetype(FONT_PATH, 80)
    except:
        font = ImageFont.load_default()
    
    if "center_x" in p:
        _, _, w, h = draw.textbbox((0, 0), price_text, font=font)
        draw.text((p["center_x"] - w/2, p["center_y"] - h/2), price_text, fill=price_color, font=font)

    base.convert("RGB").save(output_path, "JPEG", quality=90)
    return output_path

# --- 3. FEED PROCESSING ---

def process_single_feed(country_code, config, xml_file_path, template_hash):
    print(f"\n--- Processing {country_code} ---")
    try:
        tree = ET.parse(xml_file_path)
        root = tree.getroot()
    except: return

    products_for_feed = []
    
    for item in root.iter('item'):
        if len(products_for_feed) >= MAX_PRODUCTS_TO_GENERATE: break
        
        pid = item.find('g:id', NAMESPACES).text.strip()
        
        # --- Strict Image Slot Mapping ---
        # image_urls[0] = main, [1] = first additional, [2] = second additional
        image_urls = []
        main_img = item.find('g:image_link', NAMESPACES)
        if main_img is not None and main_img.text:
            image_urls.append(main_img.text.strip())
        else: continue # Skip products without main images

        add_imgs = item.findall('g:additional_image_link', NAMESPACES)
        if len(add_imgs) > 0 and add_imgs[0].text:
            image_urls.append(add_imgs[0].text.strip())
        if len(add_imgs) > 1 and add_imgs[1].text:
            image_urls.append(add_imgs[1].text.strip())

        # Price Logic
        sale_node = item.find('g:sale_price', NAMESPACES)
        price_node = item.find('g:price', NAMESPACES)
        if sale_node is not None:
            display_price = sale_node.text
            color = SALE_PRICE_COLOR
        else:
            display_price = price_node.text if price_node is not None else "0"
            color = NORMAL_PRICE_COLOR

        clean_price = display_price.split()[0].replace(".00", "") + "€"
        data_hash = hashlib.sha1(f"{pid}{display_price}{template_hash}".encode()).hexdigest()[:8]

        products_for_feed.append({
            'id': pid, 'final_price_color': color, 'formatted_display_price': clean_price,
            'image_urls': image_urls, 'data_hash': data_hash
        })

    # Generate Images with ThreadPool
    with ThreadPoolExecutor(max_workers=10) as executor:
        for p in products_for_feed:
            executor.submit(create_ballzy_ad, p['image_urls'], p['formatted_display_price'], p['id'], p['final_price_color'], p['data_hash'])

    print(f"Completed {country_code}: {len(products_for_feed)} images processed.")

def process_all_feeds():
    global DYNAMIC_LAYOUT
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    # Load the Map
    DYNAMIC_LAYOUT = get_layout_from_svg(SVG_LAYOUT_PATH)
    if not DYNAMIC_LAYOUT: return
    
    t_hash = get_template_file_hash()
    for code, config in COUNTRY_CONFIGS.items():
        xml_path = download_feed_xml(code, config['feed_url'])
        if xml_path:
            process_single_feed(code, config, xml_path, t_hash)

if __name__ == "__main__":
    process_all_feeds()
