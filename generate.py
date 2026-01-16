import requests
import os
import xml.etree.ElementTree as ET
from io import BytesIO
from PIL import Image, ImageOps, ImageDraw, ImageFont
import hashlib
import re
import csv
from concurrent.futures import ThreadPoolExecutor, as_completed

# --- 1. CONFIGURATION ---
GITHUB_PAGES_BASE_URL = "https://tanelneemoja.github.io/feed-creek"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ASSETS_DIR = os.path.join(BASE_DIR, "assets")
OUTPUT_DIR = os.path.join(BASE_DIR, "generated_ads")
TEMP_DOWNLOAD_DIR = os.path.join(BASE_DIR, "temp_xml_feeds")

FORMATS = {
    "square": {"svg": "ballzy_layout.svg", "template": "ballzy_template.png", "suffix": "sq", "font_size": 55},
    "story": {"svg": "ballzy_layout_story.svg", "template": "ballzy_template_story.png", "suffix": "story", "font_size": 80}
}

SQUIGGLY_PATH = os.path.join(ASSETS_DIR, "squiggly.png")
PRICE_BOX_NORMAL = os.path.join(ASSETS_DIR, "price_box_normal.png")
PRICE_BOX_SALE = os.path.join(ASSETS_DIR, "price_box_sale.png")
FONT_PATH = os.path.join(ASSETS_DIR, "fonts", "poppins.medium.ttf")

MAX_PRODUCTS_TO_GENERATE = 100
NORMAL_PRICE_COLOR = "#1267F3"
SALE_PRICE_COLOR = "#cc02d2"
NAMESPACES = {'g': 'http://base.google.com/ns/1.0'}

COUNTRY_CONFIGS = {
    "EE": {"url": "https://backend.ballzy.eu/et/amfeed/feed/download?id=102&file=cropink_et.xml", "currency": "€"},
    "LV": {"url": "https://backend.ballzy.eu/lv/amfeed/feed/download?id=104&file=cropink_lv.xml", "currency": "€"},
    "LT": {"url": "https://backend.ballzy.eu/lt/amfeed/feed/download?id=105&file=cropink_lt.xml", "currency": "€"},
    "FI": {"url": "https://backend.ballzy.eu/fi/amfeed/feed/download?id=103&file=cropink_fi.xml", "currency": "€"}
}

# --- 2. COORDINATE HELPERS ---

def get_coords_from_path(d_string):
    numbers = re.findall(r"[-+]?\d*\.\d+|\d+", d_string)
    if not numbers: return None
    coords = [float(n) for n in numbers]
    x_vals, y_vals = coords[0::2], coords[1::2]
    if not x_vals or not y_vals: return None
    return int(min(x_vals)), int(min(y_vals)), int(max(x_vals)-min(x_vals)), int(max(y_vals)-min(y_vals))

def extract_best_coords(elem):
    x, y, w, h = elem.get('x'), elem.get('y'), elem.get('width'), elem.get('height')
    if x is not None and y is not None:
        return int(float(x)), int(float(y)), int(float(w or 0)), int(float(h or 0))
    d = elem.get('d')
    if d:
        return get_coords_from_path(d)
    return None

def get_layout_from_svg(svg_path):
    if not os.path.exists(svg_path):
        print(f"!!! ERROR: File not found: {svg_path}")
        return None
    
    print(f"--- Parsing Layout: {os.path.basename(svg_path)} ---")
    tree = ET.parse(svg_path); root = tree.getroot()
    layout = {"slots": {}, "price": {}, "squiggly": None}
    
    for elem in root.iter():
        eid = (elem.get('id') or '').lower()
        if eid:
            print(f"  Found ID: {eid}") # This helps us see what Figma named things
        
        for idx in range(3):
            if f'slot_{idx}' in eid:
                c = extract_best_coords(elem)
                if c: layout["slots"][idx] = {"x": c[0], "y": c[1], "w": c[2], "h": c[3]}
        
        # Aggressive squiggly check
        if 'squiggly' in eid:
            c = extract_best_coords(elem) or next((extract_best_coords(ch) for ch in elem.iter() if extract_best_coords(ch)), None)
            if c: 
                layout["squiggly"] = {"x": c[0], "y": c[1]}
                print(f"  >> SUCCESS: Squiggly localized at {c[0]}, {c[1]}")

        if 'price_border' in eid:
            c = extract_best_coords(elem)
            if c: layout["price"]["x"], layout["price"]["y"] = c[0], c[1]
        if 'price_target' in eid:
            c = extract_best_coords(elem)
            if c: layout["price"]["center_x"], layout["price"]["center_y"] = c[0]+(c[2]/2), c[1]+(c[3]/2)
            
    return layout

# --- 3. AD GENERATION ---

def create_ballzy_ad(image_urls, price_text, product_id, color, data_hash, layout, fmt_key):
    cfg = FORMATS[fmt_key]
    out_name = f"ad_{product_id}_{data_hash}_{cfg['suffix']}.jpg"
    out_path = os.path.join(OUTPUT_DIR, out_name)
    try:
        template = Image.open(os.path.join(ASSETS_DIR, cfg['template'])).convert("RGBA")
        canvas = Image.new("RGBA", template.size, (255, 255, 255, 255))
        canvas.paste(template, (0, 0), template)

        # 1. Product Images
        mapping = {i: image_urls[i] for i in range(min(len(image_urls), 3))}
        for idx, url in mapping.items():
            if idx in layout["slots"]:
                slot = layout["slots"][idx]
                img = Image.open(BytesIO(requests.get(url).content)).convert("RGBA")
                # ImageOps.fit ensures the image stays in the SVG slot position
                fitted = ImageOps.fit(img, (slot['w'], slot['h']), Image.Resampling.LANCZOS)
                canvas.paste(fitted, (slot['x'], slot['y']), fitted)

        # 2. Squiggly (Pasted AFTER images)
        if layout.get("squiggly") and os.path.exists(SQUIGGLY_PATH):
            squig = Image.open(SQUIGGLY_PATH).convert("RGBA")
            canvas.paste(squig, (layout["squiggly"]["x"], layout["squiggly"]["y"]), squig)

        # 3. Price
        box_p = PRICE_BOX_SALE if color == SALE_PRICE_COLOR else PRICE_BOX_NORMAL
        if "x" in layout["price"] and os.path.exists(box_p):
            box = Image.open(box_p).convert("RGBA")
            canvas.paste(box, (layout["price"]["x"], layout["price"]["y"]), box)
            draw = ImageDraw.Draw(canvas); font = ImageFont.truetype(FONT_PATH, cfg['font_size'])
            p = layout["price"]
            _, _, w, h = draw.textbbox((0, 0), price_text, font=font)
            draw.text((p["center_x"] - w/2, p["center_y"] - h/2), price_text, fill=color, font=font)

        canvas.convert("RGB").save(out_path, "JPEG", quality=92)
    except Exception as e: pass

# --- 4. FEED GENERATORS ---

def generate_meta_feed(processed_products, country_code):
    filename = f"ballzy_{country_code.lower()}_ad_feed.xml"
    ET.register_namespace('g', NAMESPACES['g'])
    rss = ET.Element('rss', version="2.0"); channel = ET.SubElement(rss, 'channel')
    for p in processed_products:
        item = ET.SubElement(channel, 'item')
        for node in p['nodes']:
            if node.tag != '{http://base.google.com/ns/1.0}image_link': item.append(node)
        ET.SubElement(item, '{http://base.google.com/ns/1.0}image_link').text = f"{GITHUB_PAGES_BASE_URL}/generated_ads/ad_{p['id']}_{p['data_hash']}_sq.jpg"
        ET.SubElement(item, '{http://base.google.com/ns/1.0}additional_image_link').text = f"{GITHUB_PAGES_BASE_URL}/generated_ads/ad_{p['id']}_{p['data_hash']}_story.jpg"
    ET.ElementTree(rss).write(filename, encoding='utf-8', xml_declaration=True)

def generate_tiktok_feed(processed_products, country_code):
    filename = f"ballzy_tiktok_{country_code.lower()}_ad_feed.xml"
    ET.register_namespace('g', NAMESPACES['g'])
    rss = ET.Element('rss', version="2.0"); channel = ET.SubElement(rss, 'channel')
    for p in processed_products:
        item = ET.SubElement(channel, 'item')
        for node in p['nodes']:
            if node.tag != '{http://base.google.com/ns/1.0}image_link': item.append(node)
        ET.SubElement(item, '{http://base.google.com/ns/1.0}image_link').text = f"{GITHUB_PAGES_BASE_URL}/generated_ads/ad_{p['id']}_{p['data_hash']}_sq.jpg"
    ET.ElementTree(rss).write(filename, encoding='utf-8', xml_declaration=True)

def generate_google_feed(processed_products, country_code):
    filename = f"ballzy_{country_code.lower()}_google_feed.csv"
    headers = ["ID", "Item title", "Final URL", "Image URL", "Price", "Sale price"]
    with open(filename, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        for p in processed_products:
            writer.writerow({
                "ID": p['id'], "Item title": p['title'], "Final URL": p['link'],
                "Image URL": f"{GITHUB_PAGES_BASE_URL}/generated_ads/ad_{p['id']}_{p['data_hash']}_sq.jpg",
                "Price": p['formatted_price'], "Sale price": p['formatted_sale_price']
            })

# --- 5. MAIN ---

def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True); os.makedirs(TEMP_DOWNLOAD_DIR, exist_ok=True)
    layouts = {k: get_layout_from_svg(os.path.join(ASSETS_DIR, v['svg'])) for k, v in FORMATS.items()}
    
    for code, cfg in COUNTRY_CONFIGS.items():
        print(f"Processing {code}...")
        resp = requests.get(cfg['url']); xml_path = os.path.join(TEMP_DOWNLOAD_DIR, f"{code}.xml")
        with open(xml_path, 'wb') as f: f.write(resp.content)
        
        root = ET.parse(xml_path).getroot(); products_for_feed = []
        for item in list(root.iter('item'))[:MAX_PRODUCTS_TO_GENERATE]:
            pid = item.find('g:id', NAMESPACES).text.strip()
            sale_node = item.find('g:sale_price', NAMESPACES); is_sale = sale_node is not None
            raw_p = sale_node.text if is_sale else item.find('g:price', NAMESPACES).text
            price = raw_p.split()[0].replace(".00", "") + cfg['currency']
            
            imgs = [item.find('g:image_link', NAMESPACES).text.strip()]
            for add in item.findall('g:additional_image_link', NAMESPACES)[:2]: imgs.append(add.text.strip())
            
            d_hash = hashlib.sha1(f"{pid}{price}".encode()).hexdigest()[:8]
            products_for_feed.append({
                'id': pid, 'data_hash': d_hash, 'nodes': list(item), 'image_urls': imgs,
                'final_price_color': SALE_PRICE_COLOR if is_sale else NORMAL_PRICE_COLOR,
                'formatted_display_price': price, 'title': item.find('g:title', NAMESPACES).text,
                'link': item.find('g:link', NAMESPACES).text, 'formatted_price': price, 'formatted_sale_price': price if is_sale else ""
            })

        with ThreadPoolExecutor(max_workers=16) as exe:
            for p in products_for_feed:
                exe.submit(create_ballzy_ad, p['image_urls'], p['formatted_display_price'], p['id'], p['final_price_color'], p['data_hash'], layouts['square'], 'square')
                exe.submit(create_ballzy_ad, p['image_urls'], p['formatted_display_price'], p['id'], p['final_price_color'], p['data_hash'], layouts['story'], 'story')

        generate_meta_feed(products_for_feed, code)
        generate_tiktok_feed(products_for_feed, code)
        generate_google_feed(products_for_feed, code)

if __name__ == "__main__":
    main()
