import requests
import os
import xml.etree.ElementTree as ET
from io import BytesIO
from PIL import Image, ImageOps, ImageDraw, ImageFont
import hashlib
import re
from concurrent.futures import ThreadPoolExecutor

# --- CONFIG ---
ASSETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "generated_ads")
SVG_NAME = "ballzy_layout.svg"
TEMPLATE_NAME = "ballzy_template.png"
SQUIGGLY_PATH = os.path.join(ASSETS_DIR, "squiggly.png")
FONT_PATH = os.path.join(ASSETS_DIR, "fonts", "poppins.medium.ttf")
# Price boxes and colors from your setup
PRICE_BOX_NORMAL = os.path.join(ASSETS_DIR, "price_box_normal.png")
PRICE_BOX_SALE = os.path.join(ASSETS_DIR, "price_box_sale.png")
SALE_PRICE_COLOR = "#cc02d2"
NORMAL_PRICE_COLOR = "#1267F3"

def get_layout_from_svg(svg_path):
    tree = ET.parse(svg_path)
    root = tree.getroot()
    layout = {"slots": {}, "price": {}, "squiggly": None}

    for node in root.iter():
        eid = (node.get('id') or '').lower()
        if not eid: continue

        # 1. Try to get direct X/Y/W/H
        x = float(node.get('x', 0))
        y = float(node.get('y', 0))
        w = float(node.get('width', 0))
        h = float(node.get('height', 0))

        # 2. If it's a PATH (like your Squiggly), extract bounds from 'd'
        d_attr = node.get('d', '')
        if d_attr:
            nums = [float(n) for n in re.findall(r"[-+]?\d*\.\d+|\d+", d_attr)]
            if nums:
                xs, ys = nums[0::2], nums[1::2]
                # If the node had no x/y, use the path's minimums
                if x == 0: x = min(xs)
                if y == 0: y = min(ys)
                if w == 0: w = max(xs) - min(xs)
                if h == 0: h = max(ys) - min(ys)

        # 3. Assign by ID
        if 'slot_' in eid:
            idx = int(re.search(r'slot_(\d+)', eid).group(1))
            layout["slots"][idx] = {"x": int(x), "y": int(y), "w": int(w), "h": int(h)}
        elif 'squiggly' in eid:
            # For the squiggly, we use the first valid path position found inside the group
            if layout["squiggly"] is None or x > 0:
                layout["squiggly"] = {"x": int(x), "y": int(y)}
        elif 'price_border' in eid:
            layout["price"]["x"], layout["price"]["y"] = int(x), int(y)
        elif 'price_target' in eid:
            layout["price"]["center_x"] = int(x + (w / 2))
            layout["price"]["center_y"] = int(y + (h / 2))

    return layout

def create_ad(image_urls, price_text, product_id, color, data_hash, layout):
    out_path = os.path.join(OUTPUT_DIR, f"ad_{product_id}_{data_hash}_sq.jpg")
    try:
        template = Image.open(os.path.join(ASSETS_DIR, TEMPLATE_NAME)).convert("RGBA")
        canvas = Image.new("RGBA", (1200, 1200), (255, 255, 255, 255))
        
        # Layer 0: Products
        for idx, url in enumerate(image_urls[:3]):
            if idx in layout["slots"]:
                s = layout["slots"][idx]
                img = Image.open(BytesIO(requests.get(url).content)).convert("RGBA")
                # Ensure image fills the slot exactly
                fitted = ImageOps.fit(img, (s['w'], s['h']), Image.Resampling.LANCZOS)
                canvas.paste(fitted, (s['x'], s['y']), fitted)

        # Layer 1: Template Frame
        canvas.paste(template, (0, 0), template)

        # Layer 2: Squiggly (Pasted at the calculated Path coordinates)
        if layout["squiggly"] and os.path.exists(SQUIGGLY_PATH):
            sq = Image.open(SQUIGGLY_PATH).convert("RGBA")
            canvas.paste(sq, (layout["squiggly"]["x"], layout["squiggly"]["y"]), sq)

        # Layer 3: Price
        box_img = PRICE_BOX_SALE if color == SALE_PRICE_COLOR else PRICE_BOX_NORMAL
        if "x" in layout["price"]:
            box = Image.open(box_img).convert("RGBA")
            canvas.paste(box, (layout["price"]["x"], layout["price"]["y"]), box)
            draw = ImageDraw.Draw(canvas)
            font = ImageFont.truetype(FONT_PATH, 55)
            tw, th = draw.textbbox((0, 0), price_text, font=font)[2:]
            draw.text((layout["price"]["center_x"] - tw/2, layout["price"]["center_y"] - th/2), 
                      price_text, fill=color, font=font)

        canvas.convert("RGB").save(out_path, "JPEG", quality=95)
        print(f"Done: {product_id}")
    except Exception as e:
        print(f"Failed {product_id}: {e}")

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
