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
OUTPUT_DIR = os.path.join(BASE_DIR, "generated_ads")
TEMP_DOWNLOAD_DIR = os.path.join(BASE_DIR, "temp_xml_feeds")

# Replace this with your actual GitHub Pages or CDN base URL
BASE_PUBLIC_URL = "https://yourusername.github.io/feed-creek/generated_ads"

FORMATS = {
    "square": {
        "svg": "ballzy_layout.svg",
        "template": "ballzy_template.png",
        "suffix": "sq",
        "font_size": 55
    },
    "story": {
        "svg": "ballzy_layout_story.svg",
        "template": "ballzy_template_story.png",
        "suffix": "story",
        "font_size": 80  # Larger font for vertical mobile view
    }
}

SQUIGGLY_PATH = os.path.join(ASSETS_DIR, "squiggly.png")
PRICE_BOX_NORMAL = os.path.join(ASSETS_DIR, "price_box_normal.png")
PRICE_BOX_SALE = os.path.join(ASSETS_DIR, "price_box_sale.png")
FONT_PATH = os.path.join(ASSETS_DIR, "fonts", "poppins.medium.ttf")

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
ET.register_namespace('g', NAMESPACES['g'])

# --- 2. COORDINATE HELPERS ---

def get_coords_from_path(d_string):
    numbers = re.findall(r"[-+]?\d*\.\d+|\d+", d_string)
    if not numbers: return 0, 0, 0, 0
    coords = [float(n) for n in numbers]
    x_vals, y_vals = coords[0::2], coords[1::2]
    if not x_vals or not y_vals: return 0, 0, 0, 0
    return int(min(x_vals)), int(min(y_vals)), int(max(x_vals)-min(x_vals)), int(max(y_vals)-min(y_vals))

def extract_best_coords(elem):
    x, y, w, h, d = elem.get('x'), elem.get('y'), elem.get('width'), elem.get('height'), elem.get('d')
    if x is not None and y is not None:
        return int(float(x)), int(float(y)), int(float(w or 0)), int(float(h or 0))
    elif d:
        return get_coords_from_path(d)
    return None

def get_layout(svg_filename):
    svg_path = os.path.join(ASSETS_DIR, svg_filename)
    if not os.path.exists(svg_path): return None
    tree = ET.parse(svg_path)
    root = tree.getroot()
    layout = {"slots": {}, "price": {}, "squiggly": None}
    for elem in root.iter():
        eid = elem.get('id', '').lower()
        for idx in range(3):
            if f'slot_{idx}' in eid:
                c = extract_best_coords(elem)
                if c: layout["slots"][idx] = {"x": c[0], "y": c[1], "w": c[2], "h": c[3]}
        if 'squiggly' in eid:
            c = extract_best_coords(elem)
            if not c or c[0] == 0:
                for d in elem.iter():
                    dc = extract_best_coords(d)
                    if dc and dc[0] != 0: c = dc; break
            if c: layout["squiggly"] = {"x": c[0], "y": c[1]}
        if 'price_border' in eid:
            c = extract_best_coords(elem)
            if c: layout["price"]["x"], layout["price"]["y"] = c[0], c[1]
        if 'price_target' in eid:
            c = extract_best_coords(elem)
            if c: layout["price"]["center_x"], layout["price"]["center_y"] = c[0]+(c[2]/2), c[1]+(c[3]/2)
    return layout

# --- 3. GENERATION ENGINE ---

def create_image(image_urls, price_text, product_id, is_sale, data_hash, layout, fmt_key):
    cfg = FORMATS[fmt_key]
    out_name = f"ad_{product_id}_{data_hash}_{cfg['suffix']}.jpg"
    out_path = os.path.join(OUTPUT_DIR, out_name)
    color = SALE_PRICE_COLOR if is_sale else NORMAL_PRICE_COLOR

    try:
        tmp_path = os.path.join(ASSETS_DIR, cfg['template'])
        template = Image.open(tmp_path).convert("RGBA")
        canvas = Image.new("RGBA", template.size, (255, 255, 255, 255))
        canvas.paste(template, (0, 0), template)

        mapping = {0: image_urls[0]}
        if len(image_urls) == 2: mapping[1] = image_urls[1]
        elif len(image_urls) >= 3: mapping[1], mapping[2] = image_urls[1], image_urls[2]

        for idx, url in mapping.items():
            if idx in layout["slots"]:
                s = layout["slots"][idx]
                img = Image.open(BytesIO(requests.get(url).content)).convert("RGBA")
                canvas.paste(ImageOps.fit(img, (s['w'], s['h']), Image.Resampling.LANCZOS), (s['x'], s['y']))

        if layout["squiggly"] and os.path.exists(SQUIGGLY_PATH):
            sq = Image.open(SQUIGGLY_PATH).convert("RGBA")
            canvas.paste(sq, (layout["squiggly"]["x"], layout["squiggly"]["y"]), sq)

        box_p = PRICE_BOX_SALE if is_sale else PRICE_BOX_NORMAL
        if os.path.exists(box_p) and "x" in layout["price"]:
            box = Image.open(box_p).convert("RGBA")
            canvas.paste(box, (layout["price"]["x"], layout["price"]["y"]), box)
            draw = ImageDraw.Draw(canvas)
            font = ImageFont.truetype(FONT_PATH, cfg['font_size'])
            p = layout["price"]
            _, _, w, h = draw.textbbox((0, 0), price_text, font=font)
            draw.text((p["center_x"] - w/2, p["center_y"] - h/2), price_text, fill=color, font=font)

        canvas.convert("RGB").save(out_path, "JPEG", quality=92)
        return out_name
    except Exception as e:
        print(f"Error {fmt_key} for {product_id}: {e}")
        return None

# --- 4. MAIN ---

def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(TEMP_DOWNLOAD_DIR, exist_ok=True)
    
    layouts = {k: get_layout(v['svg']) for k, v in FORMATS.items()}
    if not layouts["square"] or not layouts["story"]:
        print("Missing SVG layouts. Check assets folder."); return

    for code, cfg in COUNTRY_CONFIGS.items():
        print(f"Processing {code}...")
        resp = requests.get(cfg['url'])
        path = os.path.join(TEMP_DOWNLOAD_DIR, f"{code}.xml")
        with open(path, 'wb') as f: f.write(resp.content)
        
        root = ET.parse(path).getroot()
        channel = root.find('channel')
        items = channel.findall('item') if channel is not None else root.findall('item')
        
        new_items = []
        for item in items[:LIMIT_PER_COUNTRY]:
            pid = item.find('g:id', NAMESPACES).text.strip()
            imgs = [item.find('g:image_link', NAMESPACES).text.strip()]
            for add in item.findall('g:additional_image_link', NAMESPACES)[:2]:
                imgs.append(add.text.strip())

            sale_node = item.find('g:sale_price', NAMESPACES)
            is_sale = sale_node is not None
            raw_p = sale_node.text if is_sale else item.find('g:price', NAMESPACES).text
            price = raw_p.split()[0].replace(".00", "") + "€"
            d_hash = hashlib.sha1(f"{pid}{price}".encode()).hexdigest()[:8]

            # Generate Images
            sq_file = create_image(imgs, price, pid, is_sale, d_hash, layouts["square"], "square")
            st_file = create_image(imgs, price, pid, is_sale, d_hash, layouts["story"], "story")

            if sq_file and st_file:
                item.find('g:image_link', NAMESPACES).text = f"{BASE_PUBLIC_URL}/{sq_file}"
                # Prepend the Story image as the first additional image for Meta/Google
                new_story_tag = ET.Element('{http://base.google.com/ns/1.0}additional_image_link')
                new_story_tag.text = f"{BASE_PUBLIC_URL}/{st_file}"
                item.insert(2, new_story_tag) 

        # Save the optimized Dual-Image Feed
        feed_output = os.path.join(BASE_DIR, f"ballzy_dual_feed_{code}.xml")
        ET.ElementTree(root).write(feed_output, encoding='utf-8', xml_declaration=True)
        print(f"Saved: {feed_output}")

if __name__ == "__main__":
    main()
