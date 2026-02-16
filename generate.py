import requests
import os
import xml.etree.ElementTree as ET
from io import BytesIO
from PIL import Image, ImageOps, ImageDraw, ImageFont
import hashlib
import re
from concurrent.futures import ThreadPoolExecutor

# --- 1. CONFIGURATION ---
ASSETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "generated_ads")
TEMP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "temp_xml")

# Single Format: Square
SVG_NAME = "ballzy_layout.svg"
TEMPLATE_NAME = "ballzy_template.png"
FONT_SIZE = 55

SQUIGGLY_PATH = os.path.join(ASSETS_DIR, "squiggly.png")
PRICE_BOX_NORMAL = os.path.join(ASSETS_DIR, "price_box_normal.png")
PRICE_BOX_SALE = os.path.join(ASSETS_DIR, "price_box_sale.png")
FONT_PATH = os.path.join(ASSETS_DIR, "fonts", "poppins.medium.ttf")

SALE_PRICE_COLOR = "#cc02d2"
NORMAL_PRICE_COLOR = "#1267F3"
NAMESPACES = {'g': 'http://base.google.com/ns/1.0'}

COUNTRY_CONFIGS = {
    "EE": {"url": "https://backend.ballzy.eu/et/amfeed/feed/download?id=102&file=cropink_et.xml", "currency": "€"},
    "LV": {"url": "https://backend.ballzy.eu/lv/amfeed/feed/download?id=104&file=cropink_lv.xml", "currency": "€"},
    "LT": {"url": "https://backend.ballzy.eu/lt/amfeed/feed/download?id=105&file=cropink_lt.xml", "currency": "€"},
    "FI": {"url": "https://backend.ballzy.eu/fi/amfeed/feed/download?id=103&file=cropink_fi.xml", "currency": "€"}
}

# --- 2. COORDINATE PARSER ---

def get_layout_from_svg(svg_path):
    if not os.path.exists(svg_path): return None
    tree = ET.parse(svg_path)
    root = tree.getroot()
    layout = {"slots": {}, "price": {}, "squiggly": None}

    # Find IDs regardless of nesting
    for node in root.iter():
        eid = (node.get('id') or '').lower()
        if not eid: continue

        # Standard Rect/Group attributes
        x, y = float(node.get('x', 0)), float(node.get('y', 0))
        w, h = float(node.get('width', 0)), float(node.get('height', 0))

        # Handle Path-based IDs (Squiggly)
        if 'squiggly' in eid or (w == 0 and node.get('d')):
            nums = [float(n) for n in re.findall(r"[-+]?\d*\.\d+|\d+", node.get('d', ''))]
            if nums:
                xs, ys = nums[0::2], nums[1::2]
                x, y, w, h = min(xs), min(ys), max(xs)-min(xs), max(ys)-min(ys)

        if 'squiggly' in eid:
            layout["squiggly"] = {"x": int(x), "y": int(y)}
        elif 'price_border' in eid:
            layout["price"]["x"], layout["price"]["y"] = int(x), int(y)
        elif 'price_target' in eid:
            layout["price"]["center_x"] = int(x + (w / 2))
            layout["price"]["center_y"] = int(y + (h / 2))
        elif 'slot_' in eid:
            match = re.search(r'slot_(\d+)', eid)
            if match:
                idx = int(match.group(1))
                layout["slots"][idx] = {"x": int(x), "y": int(y), "w": int(w), "h": int(h)}
    return layout

# --- 3. GENERATION ENGINE ---

def create_ad(image_urls, price_text, product_id, color, data_hash, layout):
    out_path = os.path.join(OUTPUT_DIR, f"ad_{product_id}_{data_hash}_sq.jpg")
    
    try:
        template = Image.open(os.path.join(ASSETS_DIR, TEMPLATE_NAME)).convert("RGBA")
        canvas = Image.new("RGBA", template.size, (255, 255, 255, 255))
        
        # 1. Shoes (Background)
        for idx, url in enumerate(image_urls[:3]):
            if idx in layout["slots"]:
                s = layout["slots"][idx]
                img = Image.open(BytesIO(requests.get(url).content)).convert("RGBA")
                # Square looks best when shoes fill the slot area (Fit)
                fitted = ImageOps.fit(img, (s['w'], s['h']), Image.Resampling.LANCZOS)
                canvas.paste(fitted, (s['x'], s['y']), fitted)

        # 2. Main Frame
        canvas.paste(template, (0, 0), template)

        # 3. Squiggly (On top of frame)
        if layout["squiggly"] and os.path.exists(SQUIGGLY_PATH):
            sq = Image.open(SQUIGGLY_PATH).convert("RGBA")
            canvas.paste(sq, (layout["squiggly"]["x"], layout["squiggly"]["y"]), sq)

        # 4. Price
        box_img = PRICE_BOX_SALE if color == SALE_PRICE_COLOR else PRICE_BOX_NORMAL
        if "x" in layout["price"] and os.path.exists(box_img):
            box = Image.open(box_img).convert("RGBA")
            canvas.paste(box, (layout["price"]["x"], layout["price"]["y"]), box)
            
            draw = ImageDraw.Draw(canvas)
            font = ImageFont.truetype(FONT_PATH, FONT_SIZE)
            tw, th = draw.textbbox((0, 0), price_text, font=font)[2:]
            draw.text((layout["price"]["center_x"] - tw/2, layout["price"]["center_y"] - th/2), 
                      price_text, fill=color, font=font)

        canvas.convert("RGB").save(out_path, "JPEG", quality=95)
    except Exception as e:
        print(f"Error on {product_id}: {e}")

# --- 4. MAIN ---

def main():
    for d in [OUTPUT_DIR, TEMP_DIR]: os.makedirs(d, exist_ok=True)
    layout = get_layout_from_svg(os.path.join(ASSETS_DIR, SVG_NAME))
    
    for country, config in COUNTRY_CONFIGS.items():
        print(f"Processing {country}...")
        r = requests.get(config['url'])
        root = ET.fromstring(r.content)
        
        products = []
        for item in list(root.iter('item'))[:100]:
            pid = item.find('g:id', NAMESPACES).text.strip()
            sale_p = item.find('g:sale_price', NAMESPACES)
            price_val = (sale_p.text if sale_p is not None else item.find('g:price', NAMESPACES).text).split()[0]
            display_price = price_val.replace(".00", "") + config['currency']
            
            imgs = [item.find('g:image_link', NAMESPACES).text.strip()]
            for add in item.findall('g:additional_image_link', NAMESPACES)[:2]:
                imgs.append(add.text.strip())
            
            products.append({
                'id': pid, 'urls': imgs, 'price': display_price, 
                'hash': hashlib.sha1(f"{pid}{display_price}".encode()).hexdigest()[:8],
                'color': SALE_PRICE_COLOR if sale_p is not None else NORMAL_PRICE_COLOR
            })

        with ThreadPoolExecutor(max_workers=10) as executor:
            for p in products:
                executor.submit(create_ad, p['urls'], p['price'], p['id'], p['color'], p['hash'], layout)

if __name__ == "__main__":
    main()
