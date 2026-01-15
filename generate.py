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
FONT_PATH = os.path.join(ASSETS_DIR, "fonts", "poppins.medium.ttf")

OUTPUT_DIR = os.path.join(BASE_DIR, "generated_ads")
TEMP_DOWNLOAD_DIR = os.path.join(BASE_DIR, "temp_xml_feeds")

LIMIT_PER_COUNTRY = 50 

NORMAL_PRICE_COLOR = "#0055FF"
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
    if not os.path.exists(svg_path):
        print(f"CRITICAL ERROR: SVG not found at {svg_path}")
        return None

    print(f"--- SVG Diagnostic ---")
    tree = ET.parse(svg_path)
    root = tree.getroot()
    
    layout = {"slots": [], "price": {}}
    for elem in root.iter():
        eid = elem.get('id', '').lower()
        
        # Match slots 0, 1, 2
        for i in range(3):
            if f'slot_{i}' in eid:
                layout["slots"].append({
                    "x": int(float(elem.get('x', 0))),
                    "y": int(float(elem.get('y', 0))),
                    "w": int(float(elem.get('width', 0))),
                    "h": int(float(elem.get('height', 0)))
                })

        # Match Price Box
        if 'price_border' in eid:
            bx, by = int(float(elem.get('x', 0))), int(float(elem.get('y', 0)))
            layout["price"].update({
                "rect_x0": bx, "rect_y0": by,
                "rect_x1": bx + int(float(elem.get('width', 0))),
                "rect_y1": by + int(float(elem.get('height', 0)))
            })

        # Match Price Target
        if 'price_target' in eid:
            layout["price"]["center_x"] = int(float(elem.get('x', 0))) + (int(float(elem.get('width', 0))) / 2)
            layout["price"]["center_y"] = int(float(elem.get('y', 0))) + (int(float(elem.get('height', 0))) / 2)

    print(f"  Mapped {len(layout['slots'])} image slots.")
    print(f"--- End Diagnostic ---\n")
    return layout

def create_ballzy_ad(image_urls, price_text, product_id, price_color, data_hash):
    output_path = os.path.join(OUTPUT_DIR, f"ad_{product_id}_{data_hash}.jpg")
    
    try:
        # Step A: Load Template and determine size
        template = Image.open(PNG_TEMPLATE_PATH).convert("RGBA")
        width, height = template.size
        
        # Step B: Create a fresh transparent canvas
        # This will be the "bottom" layer where images sit
        canvas = Image.new("RGBA", (width, height), (255, 255, 255, 255))
    except Exception as e:
        print(f"Error loading template: {e}")
        return

    # Step C: Paste Product Images onto Canvas (BACKGROUND LAYER)
    for i, slot in enumerate(DYNAMIC_LAYOUT["slots"]):
        if i >= len(image_urls): break
        try:
            resp = requests.get(image_urls[i], timeout=10)
            img = Image.open(BytesIO(resp.content)).convert("RGBA")
            fitted = ImageOps.fit(img, (slot['w'], slot['h']), Image.Resampling.LANCZOS)
            canvas.paste(fitted, (slot['x'], slot['y']), fitted)
        except: continue

    # Step D: Paste Template on top of everything (FOREGROUND LAYER)
    # This ensures the squiggly lines cover the image edges
    canvas.paste(template, (0, 0), template)

    # Step E: Draw Colored Price Box and Text (TOP LAYER)
    draw = ImageDraw.Draw(canvas)
    p = DYNAMIC_LAYOUT.get("price", {})
    if "rect_x0" in p:
        # Draw the rectangle after the template is pasted to ensure color is on top
        draw.rectangle([(p["rect_x0"], p["rect_y0"]), (p["rect_x1"], p["rect_y1"])], outline=price_color, width=6)
    
    try:
        # Smaller font size (50) to prevent wonkiness
        font = ImageFont.truetype(FONT_PATH, 50)
        if "center_x" in p:
            _, _, w, h = draw.textbbox((0, 0), price_text, font=font)
            draw.text((p["center_x"] - w/2, p["center_y"] - h/2), price_text, fill=price_color, font=font)
    except: pass

    # Save as final JPEG
    canvas.convert("RGB").save(output_path, "JPEG", quality=92)

def main():
    global DYNAMIC_LAYOUT
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(TEMP_DOWNLOAD_DIR, exist_ok=True)

    DYNAMIC_LAYOUT = get_layout_from_svg(SVG_LAYOUT_PATH)
    if not DYNAMIC_LAYOUT: return

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

            price_node = item.find('g:sale_price', NAMESPACES) or item.find('g:price', NAMESPACES)
            clean_price = price_node.text.split()[0].replace(".00", "") + "€"
            color = SALE_PRICE_COLOR if item.find('g:sale_price', NAMESPACES) is not None else NORMAL_PRICE_COLOR
            
            d_hash = hashlib.sha1(f"{pid}{clean_price}".encode()).hexdigest()[:8]
            products.append((image_urls, clean_price, pid, color, d_hash))

        with ThreadPoolExecutor(max_workers=5) as exe:
            for p in products: exe.submit(create_ballzy_ad, *p)

if __name__ == "__main__":
    main()
