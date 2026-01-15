import requests
import os
import xml.etree.ElementTree as ET
from io import BytesIO
from PIL import Image, ImageOps, ImageDraw, ImageFont
import hashlib
import re
from concurrent.futures import ThreadPoolExecutor

# --- 1. CONFIGURATION ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ASSETS_DIR = os.path.join(BASE_DIR, "assets")
SVG_LAYOUT_PATH = os.path.join(ASSETS_DIR, "ballzy_layout.svg")
PNG_TEMPLATE_PATH = os.path.join(ASSETS_DIR, "ballzy_template.png")

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

# --- 2. HELPER FUNCTIONS (Defined before use) ---

def get_coords_from_path(d_string):
    """Extracts bounding box from SVG path data."""
    numbers = re.findall(r"[-+]?\d*\.\d+|\d+", d_string)
    if not numbers: return 0, 0, 0, 0
    coords = [float(n) for n in numbers]
    x_vals, y_vals = coords[0::2], coords[1::2]
    if not x_vals or not y_vals: return 0, 0, 0, 0
    return int(min(x_vals)), int(min(y_vals)), int(max(x_vals)-min(x_vals)), int(max(y_vals)-min(y_vals))

def extract_best_coords(elem):
    """Checks for x/y attributes or parses path 'd'."""
    x = elem.get('x')
    y = elem.get('y')
    w = elem.get('width')
    h = elem.get('height')
    d = elem.get('d')
    if x is not None and y is not None:
        return int(float(x)), int(float(y)), int(float(w or 0)), int(float(h or 0))
    elif d:
        return get_coords_from_path(d)
    return None

def get_layout_from_svg(svg_path):
    if not os.path.exists(svg_path): 
        print(f"Error: {svg_path} not found")
        return None
    
    tree = ET.parse(svg_path)
    root = tree.getroot()
    layout = {"slots": {}, "price": {}, "squiggly": None}
    
    for elem in root.iter():
        eid = elem.get('id', '').lower()
        
        # 1. Image Slots
        for idx in range(3):
            if f'slot_{idx}' in eid:
                coords = extract_best_coords(elem)
                if coords:
                    layout["slots"][idx] = {"x": coords[0], "y": coords[1], "w": coords[2], "h": coords[3]}

        # 2. Squiggly (Deep Search for nested mask coords)
        if 'squiggly' in eid:
            coords = extract_best_coords(elem)
            # If group is empty, look deep inside for the first element with coords (like your mask)
            if not coords or coords[0] == 0:
                for descendant in elem.iter():
                    d_coords = extract_best_coords(descendant)
                    if d_coords and d_coords[0] != 0:
                        coords = d_coords
                        break
            if coords:
                layout["squiggly"] = {"x": coords[0], "y": coords[1]}
                print(f"DEBUG: Found Squiggly at {layout['squiggly']}")

        # 3. Price
        if 'price_border' in eid:
            coords = extract_best_coords(elem)
            if coords: layout["price"]["x"], layout["price"]["y"] = coords[0], coords[1]
                
        if 'price_target' in eid:
            coords = extract_best_coords(elem)
            if coords:
                layout["price"]["center_x"] = coords[0] + (coords[2] / 2)
                layout["price"]["center_y"] = coords[1] + (coords[3] / 2)
                
    return layout

# --- 3. CORE LOGIC ---

def create_ballzy_ad(image_urls, price_text, product_id, is_sale, data_hash, layout):
    output_path = os.path.join(OUTPUT_DIR, f"ad_{product_id}_{data_hash}.jpg")
    text_color = SALE_PRICE_COLOR if is_sale else NORMAL_PRICE_COLOR
    
    try:
        template = Image.open(PNG_TEMPLATE_PATH).convert("RGBA")
        canvas = Image.new("RGBA", template.size, (255, 255, 255, 255))
        
        # LAYER 1: TEMPLATE (BACKGROUND)
        canvas.paste(template, (0, 0), template)

        # LAYER 2: PRODUCT IMAGES (Slot Mapping Logic)
        mapping = {0: image_urls[0]} # Main image always in slot 0
        if len(image_urls) == 2:
            mapping[1] = image_urls[1] # Single extra goes to slot 1
        elif len(image_urls) >= 3:
            mapping[1] = image_urls[1]
            mapping[2] = image_urls[2]

        for slot_idx, url in mapping.items():
            if slot_idx in layout["slots"]:
                slot = layout["slots"][slot_idx]
                resp = requests.get(url, timeout=10)
                img = Image.open(BytesIO(resp.content)).convert("RGBA")
                fitted = ImageOps.fit(img, (slot['w'], slot['h']), Image.Resampling.LANCZOS)
                canvas.paste(fitted, (slot['x'], slot['y']), fitted)

        # LAYER 3: SQUIGGLY
        if layout["squiggly"] and os.path.exists(SQUIGGLY_PATH):
            squiggly = Image.open(SQUIGGLY_PATH).convert("RGBA")
            canvas.paste(squiggly, (layout["squiggly"]["x"], layout["squiggly"]["y"]), squiggly)

        # LAYER 4: PRICE BOX
        box_path = PRICE_BOX_SALE if is_sale else PRICE_BOX_NORMAL
        if os.path.exists(box_path) and "x" in layout["price"]:
            p_box = Image.open(box_path).convert("RGBA")
            canvas.paste(p_box, (layout["price"]["x"], layout["price"]["y"]), p_box)

        # LAYER 5: PRICE TEXT
        if "center_x" in layout["price"]:
            draw = ImageDraw.Draw(canvas)
            font = ImageFont.truetype(FONT_PATH, 55)
            p = layout["price"]
            _, _, w, h = draw.textbbox((0, 0), price_text, font=font)
            draw.text((p["center_x"] - w/2, p["center_y"] - h/2), price_text, fill=text_color, font=font)

        canvas.convert("RGB").save(output_path, "JPEG", quality=92)
    except Exception as e:
        print(f"Error processing {product_id}: {e}")

def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(TEMP_DOWNLOAD_DIR, exist_ok=True)
    
    layout = get_layout_from_svg(SVG_LAYOUT_PATH)
    if not layout: return

    for code, config in COUNTRY_CONFIGS.items():
        print(f"Processing Feed: {code}...")
        resp = requests.get(config['url'])
        path = os.path.join(TEMP_DOWNLOAD_DIR, f"{code}.xml")
        with open(path, 'wb') as f: f.write(resp.content)
        
        root = ET.parse(path).getroot()
        products = []
        for item in list(root.iter('item'))[:LIMIT_PER_COUNTRY]:
            pid = item.find('g:id', NAMESPACES).text.strip()
            
            # Collect images
            image_urls = [item.find('g:image_link', NAMESPACES).text.strip()]
            for add in item.findall('g:additional_image_link', NAMESPACES)[:2]:
                image_urls.append(add.text.strip())

            # Price logic
            sale_node = item.find('g:sale_price', NAMESPACES)
            is_sale = sale_node is not None
            display_price = sale_node.text if is_sale else item.find('g:price', NAMESPACES).text
            clean_price = display_price.split()[0].replace(".00", "") + "€"
            
            d_hash = hashlib.sha1(f"{pid}{clean_price}".encode()).hexdigest()[:8]
            products.append((image_urls, clean_price, pid, is_sale, d_hash, layout))

        with ThreadPoolExecutor(max_workers=5) as exe:
            for p in products: exe.submit(create_ballzy_ad, *p)

if __name__ == "__main__":
    main()
