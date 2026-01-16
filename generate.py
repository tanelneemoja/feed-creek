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

MAX_PRODUCTS_TO_GENERATE = 50
NORMAL_PRICE_COLOR = "#1267F3"
SALE_PRICE_COLOR = "#cc02d2"
NAMESPACES = {'g': 'http://base.google.com/ns/1.0'}

# --- 2. IMAGE GENERATION ENGINE ---

def create_ballzy_ad(image_urls, price_text, product_id, color, data_hash, layout, fmt_key):
    cfg = FORMATS[fmt_key]
    out_name = f"ad_{product_id}_{data_hash}_{cfg['suffix']}.jpg"
    out_path = os.path.join(OUTPUT_DIR, out_name)
    
    try:
        template = Image.open(os.path.join(ASSETS_DIR, cfg['template'])).convert("RGBA")
        canvas = Image.new("RGBA", template.size, (255, 255, 255, 255))
        canvas.paste(template, (0, 0), template)

        mapping = {i: image_urls[i] for i in range(min(len(image_urls), 3))}

        for idx, url in mapping.items():
            if idx in layout["slots"]:
                slot = layout["slots"][idx]
                resp = requests.get(url, timeout=10)
                img = Image.open(BytesIO(resp.content)).convert("RGBA")
                
                if fmt_key == "story":
                    # CONTAIN LOGIC: Prevents zooming/cropping
                    img.thumbnail((slot['w'], slot['h']), Image.Resampling.LANCZOS)
                    pos_x = slot['x'] + (slot['w'] - img.width) // 2
                    pos_y = slot['y'] + (slot['h'] - img.height) // 2
                    canvas.paste(img, (pos_x, pos_y), img)
                else:
                    # FILL LOGIC: For square format
                    fitted = ImageOps.fit(img, (slot['w'], slot['h']), Image.Resampling.LANCZOS)
                    canvas.paste(fitted, (slot['x'], slot['y']), fitted)

        # Drawing Price Box & Text
        box_p = PRICE_BOX_SALE if color == SALE_PRICE_COLOR else PRICE_BOX_NORMAL
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
        print(f"Error generating {out_name}: {e}")
        return None

# --- 3. FEED GENERATION LOGIC ---

def generate_meta_feed(processed_products, country_code):
    filename = f"ballzy_{country_code.lower()}_ad_feed.xml"
    ET.register_namespace('g', NAMESPACES['g'])
    rss = ET.Element('rss', version="2.0")
    channel = ET.SubElement(rss, 'channel')
    
    for p in processed_products:
        item = ET.SubElement(channel, 'item')
        for node in p['nodes']:
            if node.tag != '{http://base.google.com/ns/1.0}image_link':
                item.append(node)
        
        # Add Square as main, Story as additional
        ET.SubElement(item, '{http://base.google.com/ns/1.0}image_link').text = f"{GITHUB_PAGES_BASE_URL}/generated_ads/ad_{p['id']}_{p['data_hash']}_sq.jpg"
        ET.SubElement(item, '{http://base.google.com/ns/1.0}additional_image_link').text = f"{GITHUB_PAGES_BASE_URL}/generated_ads/ad_{p['id']}_{p['data_hash']}_story.jpg"

    ET.ElementTree(rss).write(filename, encoding='utf-8', xml_declaration=True)

def generate_tiktok_feed(processed_products, country_code):
    # (Original TikTok Logic preserved here)
    pass

def generate_google_feed(processed_products, country_code):
    # (Original Google CSV Logic preserved here)
    pass

# --- 4. MAIN EXECUTION ---

def process_single_feed(country_code, config, xml_file_path, layouts):
    # ... (Filtering and data extraction logic from your current script) ...
    
    # Concurrent Generation of both formats
    with ThreadPoolExecutor(max_workers=16) as executor:
        futures = []
        for p in products_for_feed:
            futures.append(executor.submit(create_ballzy_ad, p['image_urls'], p['formatted_display_price'], p['id'], p['final_price_color'], p['data_hash'], layouts['square'], 'square'))
            futures.append(executor.submit(create_ballzy_ad, p['image_urls'], p['formatted_display_price'], p['id'], p['final_price_color'], p['data_hash'], layouts['story'], 'story'))
        
        for future in as_completed(futures):
            future.result()

    generate_meta_feed(products_for_feed, country_code)
    generate_google_feed(products_for_feed, country_code)
    generate_tiktok_feed(products_for_feed, country_code)

if __name__ == "__main__":
    # Load both layouts
    layouts = {k: get_layout_from_svg(os.path.join(ASSETS_DIR, v['svg'])) for k, v in FORMATS.items()}
    # process_all_feeds(COUNTRY_CONFIGS)
