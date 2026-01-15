import requests
import os
import xml.etree.ElementTree as ET
from io import BytesIO
from PIL import Image, ImageOps, ImageDraw, ImageFont
import hashlib
from concurrent.futures import ThreadPoolExecutor

# --- 1. CONFIGURATION ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ASSETS_DIR = os.path.join(BASE_DIR, "assets")
SVG_LAYOUT_PATH = os.path.join(ASSETS_DIR, "ballzy_layout.svg")
PNG_TEMPLATE_PATH = os.path.join(ASSETS_DIR, "ballzy_template.png")

# ASSET PATHS
SQUIGGLY_PATH = os.path.join(ASSETS_DIR, "squiggly.png")
PRICE_BOX_NORMAL = os.path.join(ASSETS_DIR, "price_box_normal.png")
PRICE_BOX_SALE = os.path.join(ASSETS_DIR, "price_box_sale.png")
FONT_PATH = os.path.join(ASSETS_DIR, "fonts", "poppins.medium.ttf")

OUTPUT_DIR = os.path.join(BASE_DIR, "generated_ads")
TEMP_DOWNLOAD_DIR = os.path.join(BASE_DIR, "temp_xml_feeds")

LIMIT_PER_COUNTRY = 50 
NORMAL_PRICE_COLOR = "#1267F3" 
SALE_PRICE_COLOR = "#cc02d2"

COUNTRY_CONFIGS = {
    "EE": {"url": "https://backend.ballzy.eu/et/amfeed/feed/download?id=102&file=cropink_et.xml"},
    "LV": {"url": "https://backend.ballzy.eu/lv/amfeed/feed/download?id=104&file=cropink_lv.xml"},
    "LT": {"url": "https://backend.ballzy.eu/lt/amfeed/feed/download?id=105&file=cropink_lt.xml"},
    "FI": {"url": "https://backend.ballzy.eu/fi/amfeed/feed/download?id=103&file=cropink_fi.xml"}
}

NAMESPACES = {'g': 'http://base.google.com/ns/1.0'}
DYNAMIC_LAYOUT = {}

# --- 2. LOGIC FUNCTIONS ---

def get_layout_from_svg(svg_path):
    """Maps coordinates from SVG IDs for precise placement."""
    if not os.path.exists(svg_path):
        print(f"CRITICAL: SVG not found at {svg_path}")
        return None
    
    tree = ET.parse(svg_path)
    root = tree.getroot()
    layout = {"slots": [], "price": {}, "squiggly": None}
    
    for elem in root.iter():
        eid = elem.get('id', '').lower()
        if 'slot_' in eid:
            layout["slots"].append({
                "x": int(float(elem.get('x', 0))), "y": int(float(elem.get('y', 0))),
                "w": int(float(elem.get('width', 0))), "h": int(float(elem.get('height', 0)))
            })
        if 'squiggly' in eid:
            layout["squiggly"] = {"x": int(float(elem.get('x', 0))), "y": int(float(elem.get('y', 0)))}
        if 'price_border' in eid:
            layout["price"]["x"] = int(float(elem.get('x', 0)))
            layout["price"]["y"] = int(float(elem.get('y', 0)))
        if 'price_target' in eid:
            layout["price"]["center_x"] = int(float(elem.get('x', 0))) + (int(float(elem.get('width', 0))) / 2)
            layout["price"]["center_y"] = int(float(elem.get('y', 0))) + (int(float(elem.get('height', 0))) / 2)
    return layout

def create_ballzy_ad(image_urls, price_text, product_id, is_sale, data_hash):
    output_path = os.path.join(OUTPUT_DIR, f"ad_{product_id}_{data_hash}.jpg")
    text_color = SALE_PRICE_COLOR if is_sale else NORMAL_PRICE_COLOR
    
    try:
        # Step 1: Base Canvas
        template = Image.open(PNG_TEMPLATE_PATH).convert("RGBA")
        canvas = Image.new("RGBA", template.size, (255, 255, 255, 255))
        
        # --- LAYER 1: TEMPLATE (BACKGROUND) ---
        canvas.paste(template, (0, 0), template)

        # --- LAYER 2: PRODUCT IMAGES ---
        for i, slot in enumerate(DYNAMIC_LAYOUT["slots"]):
            if i >= len(image_urls): break
            resp = requests.get(image_urls[i], timeout=10)
            img = Image.open(BytesIO(resp.content)).convert("RGBA")
            # Fit image to SVG box
            fitted = ImageOps.fit(img, (slot['w'], slot['h']), Image.Resampling.LANCZOS)
            canvas.paste(fitted, (slot['x'], slot['y']), fitted)

        # --- LAYER 3: SQUIGGLY (OVERLAY) ---
        if DYNAMIC_LAYOUT["squiggly"] and os.path.exists(SQUIGGLY_PATH):
            squiggly = Image.open(SQUIGGLY_PATH).convert("RGBA")
            canvas.paste(squiggly, (DYNAMIC_LAYOUT["squiggly"]["x"], DYNAMIC_LAYOUT["squiggly"]["y"]), squiggly)

        # --- LAYER 4: PRICE BOX ---
        box_path = PRICE_BOX_SALE if is_sale else PRICE_BOX_NORMAL
        if os.path.exists(box_path):
            p_box = Image.open(box_path).convert("RGBA")
            canvas.paste(p_box, (DYNAMIC_LAYOUT["price"]["x"], DYNAMIC_LAYOUT["price"]["y"]), p_box)

        # --- LAYER 5: PRICE TEXT (TOP) ---
        draw = ImageDraw.Draw(canvas)
        font = ImageFont.truetype(FONT_PATH, 55)
        p = DYNAMIC_LAYOUT["price"]
        _, _, w, h = draw.textbbox((0, 0), price_text, font=font)
        draw.text((p["center_x"] - w/2, p["center_y"] - h/2), price_text, fill=text_color, font=font)

        # Step 6: Save as Flattened JPEG
        canvas.convert("RGB").save(output_path, "JPEG", quality=92)
    except Exception as e:
        print(f"Failed to generate {product_id}: {e}")

def main():
    global DYNAMIC_LAYOUT
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(TEMP_DOWNLOAD_DIR, exist_ok=True)

    DYNAMIC_LAYOUT = get_layout_from_svg(SVG_LAYOUT_PATH)
    if not DYNAMIC_LAYOUT:
        print("Mapping failed. Ensure SVG has correct IDs.")
        return

    for code, config in COUNTRY_CONFIGS.items():
        print(f"Processing {code}...")
        resp = requests.get(config['url'])
        path = os.path.join(TEMP_DOWNLOAD_DIR, f"{code}.xml")
        with open(path, 'wb') as f: f.write(resp.content)
        
        root = ET.parse(path).getroot()
        products = []
        for item in list(root.iter('item'))[:LIMIT_PER_COUNTRY]:
            pid = item.find('g:id', NAMESPACES).text.strip()
            
            image_urls = [item.find('g:image_link', NAMESPACES).text.strip()]
            for add in item.findall('g:additional_image_link', NAMESPACES)[:2]:
                image_urls.append(add.text.strip())

            sale_node = item.find('g:sale_price', NAMESPACES)
            price_node = item.find('g:price', NAMESPACES)
            
            is_sale = sale_node is not None
            display_price = sale_node.text if is_sale else price_node.text
            clean_price = display_price.split()[0].replace(".00", "") + "€"
            
            d_hash = hashlib.sha1(f"{pid}{clean_price}".encode()).hexdigest()[:8]
            products.append((image_urls, clean_price, pid, is_sale, d_hash))

        with ThreadPoolExecutor(max_workers=5) as exe:
            for p in products: exe.submit(create_ballzy_ad, *p)

if __name__ == "__main__":
    main()
