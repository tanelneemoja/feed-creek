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

FORMATS = {
    "square": {"svg": "ballzy_layout.svg", "template": "ballzy_template.png", "suffix": "sq", "font_size": 55},
    "story": {"svg": "ballzy_layout_story.svg", "template": "ballzy_template_story.png", "suffix": "story", "font_size": 80}
}

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

# --- 2. THE RECURSIVE COORDINATE ENGINE ---

def get_layout_from_svg(svg_path):
    if not os.path.exists(svg_path): 
        print(f"Missing SVG: {svg_path}")
        return None
    
    tree = ET.parse(svg_path)
    root = tree.getroot()
    layout = {"slots": {}, "price": {}, "squiggly": None}

    def walk_svg(node, current_x=0, current_y=0):
        # Handle "transform" attributes found on groups <g>
        transform = node.get('transform', '')
        tx, ty = 0, 0
        if 'translate' in transform:
            match = re.search(r'translate\(([-0-9.]+)\s*[, ]\s*([-0-9.]+)\)', transform)
            if match:
                tx, ty = float(match.group(1)), float(match.group(2))
        
        # Cumulative position logic
        abs_x = current_x + tx
        abs_y = current_y + ty

        eid = (node.get('id') or '').lower()
        
        # Extract dimensions (handling potential floats from Figma)
        lx = float(node.get('x', 0))
        ly = float(node.get('y', 0))
        lw = float(node.get('width', 0))
        lh = float(node.get('height', 0))

        # Special logic for Path objects (the squiggly usually is a <path>)
        d = node.get('d')
        if d and lw == 0:
            nums = [float(n) for n in re.findall(r"[-+]?\d*\.\d+|\d+", d)]
            if nums:
                xs, ys = nums[0::2], nums[1::2]
                lx, ly, lw, lh = min(xs), min(ys), max(xs)-min(xs), max(ys)-min(ys)

        final_x, final_y = int(abs_x + lx), int(abs_y + ly)

        # Map IDs to our Layout Dictionary
        if 'squiggly' in eid and not layout["squiggly"]:
            layout["squiggly"] = {"x": final_x, "y": final_y}
        
        if 'price_border' in eid:
            layout["price"]["x"], layout["price"]["y"] = final_x, final_y
            
        if 'price_target' in eid:
            layout["price"]["center_x"] = final_x + (lw / 2)
            layout["price"]["center_y"] = final_y + (lh / 2)

        for idx in range(3):
            if f'slot_{idx}' in eid:
                layout["slots"][idx] = {"x": final_x, "y": final_y, "w": int(lw), "h": int(lh)}

        # Recursively visit children to handle nesting
        for child in node:
            walk_svg(child, abs_x, abs_y)

    walk_svg(root)
    return layout

# --- 3. CORE AD GENERATION ---

def create_ad(image_urls, price_text, product_id, color, data_hash, layout, fmt_key):
    cfg = FORMATS[fmt_key]
    out_path = os.path.join(OUTPUT_DIR, f"ad_{product_id}_{data_hash}_{cfg['suffix']}.jpg")
    
    try:
        # Create base
        template = Image.open(os.path.join(ASSETS_DIR, cfg['template'])).convert("RGBA")
        canvas = Image.new("RGBA", template.size, (255, 255, 255, 255))
        
        # 1. Paste Products UNDER the template
        for idx, url in enumerate(image_urls[:3]):
            if idx in layout["slots"]:
                s = layout["slots"][idx]
                img = Image.open(BytesIO(requests.get(url).content)).convert("RGBA")
                
                if fmt_key == "story":
                    # For Story, we center inside the slot without aggressive cropping
                    img.thumbnail((s['w'], s['h']), Image.Resampling.LANCZOS)
                    pos_x = s['x'] + (s['w'] - img.width) // 2
                    pos_y = s['y'] + (s['h'] - img.height) // 2
                    canvas.paste(img, (pos_x, pos_y), img)
                else:
                    # Square uses "Fit" to fill the slot
                    fitted = ImageOps.fit(img, (s['w'], s['h']), Image.Resampling.LANCZOS)
                    canvas.paste(fitted, (s['x'], s['y']), fitted)

        # 2. Paste the Main Frame Template
        canvas.paste(template, (0, 0), template)

        # 3. Paste Squiggly ON TOP of the frame
        if layout["squiggly"] and os.path.exists(SQUIGGLY_PATH):
            sq = Image.open(SQUIGGLY_PATH).convert("RGBA")
            canvas.paste(sq, (layout["squiggly"]["x"], layout["squiggly"]["y"]), sq)

        # 4. Draw Price Elements
        box_img = PRICE_BOX_SALE if color == SALE_PRICE_COLOR else PRICE_BOX_NORMAL
        if "x" in layout["price"] and os.path.exists(box_img):
            box = Image.open(box_img).convert("RGBA")
            canvas.paste(box, (layout["price"]["x"], layout["price"]["y"]), box)
            
            draw = ImageDraw.Draw(canvas)
            font = ImageFont.truetype(FONT_PATH, cfg['font_size'])
            tw, th = draw.textbbox((0, 0), price_text, font=font)[2:]
            draw.text((layout["price"]["center_x"] - tw/2, layout["price"]["center_y"] - th/2), 
                      price_text, fill=color, font=font)

        canvas.convert("RGB").save(out_path, "JPEG", quality=95)
    except Exception as e:
        print(f"Error generating {product_id} ({fmt_key}): {e}")

# --- 4. MAIN EXECUTION ---

def main():
    for d in [OUTPUT_DIR, TEMP_DIR]: os.makedirs(d, exist_ok=True)
    
    # Load layout definitions once
    layouts = {k: get_layout_from_svg(os.path.join(ASSETS_DIR, v['svg'])) for k, v in FORMATS.items()}
    
    for country, config in COUNTRY_CONFIGS.items():
        print(f"Fetching {country} feed...")
        r = requests.get(config['url'])
        xml_file = os.path.join(TEMP_DIR, f"{country}.xml")
        with open(xml_file, "wb") as f: f.write(r.content)
        
        root = ET.parse(xml_file).getroot()
        products = []
        for item in list(root.iter('item'))[:100]: # Max 100 products
            pid = item.find('g:id', NAMESPACES).text.strip()
            sale_p = item.find('g:sale_price', NAMESPACES)
            is_sale = sale_p is not None
            price_val = sale_p.text if is_sale else item.find('g:price', NAMESPACES).text
            display_price = price_val.split()[0].replace(".00", "") + config['currency']
            
            imgs = [item.find('g:image_link', NAMESPACES).text.strip()]
            for add in item.findall('g:additional_image_link', NAMESPACES)[:2]:
                imgs.append(add.text.strip())
            
            d_hash = hashlib.sha1(f"{pid}{display_price}".encode()).hexdigest()[:8]
            products.append({
                'id': pid, 'urls': imgs, 'price': display_price, 'hash': d_hash,
                'color': SALE_PRICE_COLOR if is_sale else NORMAL_PRICE_COLOR
            })

        print(f"Generating {len(products)} ads for {country}...")
        with ThreadPoolExecutor(max_workers=10) as executor:
            for p in products:
                executor.submit(create_ad, p['urls'], p['price'], p['id'], p['color'], p['hash'], layouts['square'], 'square')
                executor.submit(create_ad, p['urls'], p['price'], p['id'], p['color'], p['hash'], layouts['story'], 'story')

if __name__ == "__main__":
    main()
