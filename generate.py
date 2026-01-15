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
 
# Path to your assets
ASSETS_DIR = "assets"
SVG_LAYOUT_PATH = os.path.join(ASSETS_DIR, "ballzy_layout.svg")
PNG_TEMPLATE_PATH = os.path.join(ASSETS_DIR, "ballzy_template.png")
FONT_PATH = os.path.join(ASSETS_DIR, "fonts/poppins.medium.ttf")

OUTPUT_DIR = "generated_ads"
MAX_PRODUCTS_TO_GENERATE = 5000 
TEMP_DOWNLOAD_DIR = "temp_xml_feeds" 

# Define color constants
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

# Global variable to hold the SVG layout
DYNAMIC_LAYOUT = {}

# --- 2. HELPER FUNCTIONS ---

def get_layout_from_svg(svg_path):
    """Parses SVG to find rectangles with IDs: slot_0, slot_1, slot_2, price_border, price_target."""
    print(f"Parsing SVG Layout from {svg_path}...")
    tree = ET.parse(svg_path)
    root = tree.getroot()
    ns = {'svg': 'http://www.w3.org/2000/svg'}
    
    layout = {"slots": [], "price": {}}

    # Extract Slots
    for i in range(3):
        elem = root.find(f".//svg:rect[@id='slot_{i}']", ns)
        if elem is not None:
            layout["slots"].append({
                "x": int(float(elem.get('x'))),
                "y": int(float(elem.get('y'))),
                "w": int(float(elem.get('width'))),
                "h": int(float(elem.get('height')))
            })

    # Extract Price Border
    border = root.find(".//svg:rect[@id='price_border']", ns)
    if border is not None:
        layout["price"]["rect_x0"] = int(float(border.get('x')))
        layout["price"]["rect_y0"] = int(float(border.get('y')))
        layout["price"]["rect_x1"] = layout["price"]["rect_x0"] + int(float(border.get('width')))
        layout["price"]["rect_y1"] = layout["price"]["rect_y0"] + int(float(border.get('height')))

    # Extract Price Text Anchor
    target = root.find(".//svg:rect[@id='price_target']", ns)
    if target is not None:
        # Centering logic: middle of the target rectangle
        layout["price"]["center_x"] = int(float(target.get('x'))) + (int(float(target.get('width'))) / 2)
        layout["price"]["center_y"] = int(float(target.get('y'))) + (int(float(target.get('height'))) / 2)
    
    return layout

def get_template_file_hash():
    hasher = hashlib.sha1()
    with open(PNG_TEMPLATE_PATH, 'rb') as f:
        while chunk := f.read(8192): hasher.update(chunk)
    return hasher.hexdigest()[:8]

def clean_text(text):
    if not text: return ""
    text = html.unescape(text)
    return re.sub('<[^>]*>', '', text).replace('Vaata lähemalt ballzy.eu.', '').strip()

def create_ballzy_ad(image_urls, price_text, product_id, price_color, data_hash):
    output_path = os.path.join(OUTPUT_DIR, f"ad_{product_id}_{data_hash}.jpg")
    if os.path.exists(output_path): return output_path

    try:
        base = Image.open(PNG_TEMPLATE_PATH).convert("RGBA")
    except:
        base = Image.new('RGBA', (1200, 1200), (255, 255, 255, 255))
        
    # 1. Paste Images into SVG slots
    for i, slot in enumerate(DYNAMIC_LAYOUT["slots"]):
        if i >= len(image_urls): continue
        try:
            resp = requests.get(image_urls[i], timeout=10)
            img = Image.open(BytesIO(resp.content)).convert("RGBA")
            fitted_img = ImageOps.fit(img, (slot['w'], slot['h']), Image.Resampling.LANCZOS)
            base.paste(fitted_img, (slot['x'], slot['y']), fitted_img)
        except: continue

    # 2. Draw Price Box
    draw = ImageDraw.Draw(base)
    p = DYNAMIC_LAYOUT["price"]
    draw.rectangle([(p["rect_x0"], p["rect_y0"]), (p["rect_x1"], p["rect_y1"])], outline=price_color, width=6)
    
    # 3. Draw Price Text
    try:
        font = ImageFont.truetype(FONT_PATH, 80)
    except:
        font = ImageFont.load_default()
    
    _, _, w, h = draw.textbbox((0, 0), price_text, font=font)
    draw.text((p["center_x"] - w/2, p["center_y"] - h/2), price_text, fill=price_color, font=font)

    base.convert("RGB").save(output_path, "JPEG", quality=90)
    return output_path

# --- [Keep your existing Feed Generation Logic and process_single_feed here] ---
# Note: Ensure process_single_feed calls create_ballzy_ad

def process_all_feeds(country_configs):
    global DYNAMIC_LAYOUT
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    # LOAD DYNAMIC LAYOUT
    DYNAMIC_LAYOUT = get_layout_from_svg(SVG_LAYOUT_PATH)
    template_hash = get_template_file_hash()
    
    for code, config in country_configs.items():
        # ... your existing download and processing logic ...
        pass
