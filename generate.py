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
import glob # 🟢 NEW IMPORT for file searching

# --- 1. CONFIGURATION ---

# 1.1. Feed Sources, Constants, and Country Configurations
OUTPUT_DIR = "generated_ads"
MAX_PRODUCTS_TO_GENERATE = 5000 
TEMP_DOWNLOAD_DIR = "temp_xml_feeds" 

# 1.2. Figma Design Layout & Image Fitting
# ... (LAYOUT_CONFIG remains the same) ...
LAYOUT_CONFIG = {
    "canvas_size": (1200, 1200),
    "template_path": "assets/ballzy_template.png", 
    "slots": [
        {"x": 25, "y": 25, "w": 606, "h": 700, "center_y": 0.5},
        {"x": 656, "y": 305, "w": 522, "h": 624, "center_y": 0.6},
        {"x": 25, "y": 823, "w": 606, "h": 350, "center_y": 0.5}
    ],
    "price": {
        "x": 920,
        "y": 1050,
        "font_size": 80,
        "font_path": "assets/fonts/poppins.medium.ttf",
        "rect_x0": 656,
        "rect_y0": 950,
        "rect_x1": 1178,
        "rect_y1": 1175,
    }
}
# ... (COUNTRY_CONFIGS remain the same) ...
COUNTRY_CONFIGS = {
    "EE": {
        "feed_url": "https://backend.ballzy.eu/et/amfeed/feed/download?id=102&file=cropink_et.xml",
        "currency": "EUR",
        "google_feed_required": True,
        "language_code": "et"
    },
    "LV": {
        "feed_url": "https://backend.ballzy.eu/lv/amfeed/feed/download?id=104&file=cropink_lv.xml",
        "currency": "EUR",
        "google_feed_required": True,
        "language_code": "lv"
    },
    "LT": {
        "feed_url": "https://backend.ballzy.eu/lt/amfeed/feed/download?id=105&file=cropink_lt.xml",
        "currency": "EUR",
        "google_feed_required": True,
        "language_code": "lt"
    },
    "FI": {
        "feed_url": "https://backend.ballzy.eu/fi/amfeed/feed/download?id=103&file=cropink_fi.xml",
        "currency": "EUR",
        "google_feed_required": False,
        "language_code": "fi"
    }
}


# Public Hosting Configuration
GITHUB_PAGES_BASE_URL = "https://tanelneemoja.github.io/feed-creek/generated_ads"

# XML Namespaces
NAMESPACES = {
    'g': 'http://base.google.com/ns/1.0'
}
NS = NAMESPACES 

# Define color constants
NORMAL_PRICE_COLOR = "#0055FF"
SALE_PRICE_COLOR = "#cc02d2"


# --- 2. HELPER FUNCTIONS ---

def get_template_file_hash():
    """
    Reads the template file and returns its SHA1 hash.
    """
    template_path = LAYOUT_CONFIG["template_path"]
    if not os.path.exists(template_path):
        print(f"WARNING: Template file not found at {template_path}. Using fixed hash 'notfound'.")
        return "notfound" 
        
    hasher = hashlib.sha1()
    try:
        with open(template_path, 'rb') as f:
            while True:
                chunk = f.read(8192) 
                if not chunk:
                    break
                hasher.update(chunk)
        return hasher.hexdigest()[:8]
    except Exception as e:
        print(f"ERROR: Could not hash template file: {e}")
        return "error"

def clean_text(text):
    """Removes HTML tags and decodes HTML entities (like &hellip;) from a string."""
    if not text:
        return ""
        
    text = html.unescape(text)
    clean = re.sub('<[^>]*>', '', text)
    clean = clean.replace('Vaata lähemalt ballzy.eu.', '').strip()
    
    return clean

def download_feed_xml(country_code, url):
    """Downloads the XML feed and saves it to a temporary directory."""
    os.makedirs(TEMP_DOWNLOAD_DIR, exist_ok=True)
    filename = f"{country_code.lower()}_feed.xml"
    file_path = os.path.join(TEMP_DOWNLOAD_DIR, filename)
    
    print(f"Downloading feed for {country_code} from: {url}")
    try:
        feed_response = requests.get(url, timeout=30)
        feed_response.raise_for_status()
        with open(file_path, 'wb') as f:
            f.write(feed_response.content)
        return file_path
    except requests.exceptions.RequestException as e:
        print(f"FATAL ERROR: Could not download feed for {country_code}. {e}")
        return None

def create_ballzy_ad(image_urls, price_text, product_id, price_color, data_hash):
    """
    Generates the single stylized image based on the Ballzy layout.
    Uses hash in filename for robust caching and checks for existence.
    """
    
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    output_path = os.path.join(OUTPUT_DIR, f"ad_{product_id}_{data_hash}.jpg")
    
    # ROBUST CACHING CHECK: Skip generation if image with correct hash already exists
    if os.path.exists(output_path):
        return output_path

    try:
        base = Image.open(LAYOUT_CONFIG["template_path"]).convert("RGBA")
    except FileNotFoundError:
        base = Image.new('RGBA', LAYOUT_CONFIG["canvas_size"], (255, 255, 255, 255))
        
    for i, slot in enumerate(LAYOUT_CONFIG["slots"]):
        if i >= len(image_urls): continue
        url = image_urls[i]
        try:
            response = requests.get(url, timeout=10)
            img = Image.open(BytesIO(response.content)).convert("RGBA")
            target_size = (slot['w'], slot['h'])
            fitted_img = ImageOps.fit(
                img, target_size, method=Image.Resampling.LANCZOS, centering=(0.5, slot.get("center_y", 0.5))
            )
            base.paste(fitted_img, (slot['x'], slot['y']), fitted_img)
        except Exception as e:
            # Print minimal error for concurrent context
            print(f"  Error processing image for product {product_id} slot {i}.", flush=True)

    # 3. Draw the Price
    draw = ImageDraw.Draw(base)
    price_conf = LAYOUT_CONFIG["price"]
    
    # Draw the Colored Border (Outline only)
    rect_coords = [(price_conf["rect_x0"], price_conf["rect_y0"]), (price_conf["rect_x1"], price_conf["rect_y1"])]
    draw.rectangle(
        rect_coords,
        fill=None,
        outline=price_color,
        width=5
    )
    
    # Load Font
    try:
        font = ImageFont.truetype(price_conf["font_path"], price_conf["font_size"])
    except:
        font = ImageFont.load_default()

    # Draw the price text (using dynamic color)
    _, _, w, h = draw.textbbox((0, 0), price_text, font=font)
    text_x = price_conf["x"] - (w / 2)
    text_y = price_conf["y"] - (h / 2)
    draw.text((text_x, text_y), price_text, fill=price_color, font=font)

    # 4. Save Final Ad
    base.convert("RGB").save(output_path, format="JPEG", quality=95)
    return output_path

def cleanup_orphaned_ads(valid_filenames_set):
    """
    Deletes any file in OUTPUT_DIR that is an ad image but is NOT in the 
    set of currently generated, valid hash-based filenames.
    """
    print(f"\nStarting cleanup of orphaned ads in {OUTPUT_DIR}...", flush=True)
    
    # Search for all image files generated previously (pattern ad_*.jpg)
    all_ad_files = glob.glob(os.path.join(OUTPUT_DIR, "ad_*.jpg"))
    
    deleted_count = 0
    
    for file_path in all_ad_files:
        filename = os.path.basename(file_path)
        
        # Check if the file's exact name exists in our set of valid, up-to-date ads
        if filename not in valid_filenames_set:
            try:
                os.remove(file_path)
                deleted_count += 1
            except Exception as e:
                print(f"  Error deleting orphaned file {filename}: {e}", flush=True)
                
    print(f"Cleanup complete. Deleted {deleted_count} orphaned ad images.", flush=True)
    

# --- 4. FEED GENERATION LOGIC ---
# (Feed generation functions are unchanged but rely on the correct 'data_hash')

def generate_meta_feed(processed_products, country_code):
    """Creates the final Meta XML feed."""
    META_FEED_FILENAME = f"ballzy_{country_code.lower()}_ad_feed.xml"
    
    print(f"\nCreating final Meta Feed for {country_code}: {META_FEED_FILENAME}")
    
    ET.register_namespace('', 'http://www.w3.org/2005/Atom')
    ET.register_namespace('g', 'http://base.google.com/ns/1.0')
    rss = ET.Element('rss', version="2.0")
    channel = ET.SubElement(rss, 'channel')
    
    ET.SubElement(channel, 'title').text = f"Ballzy Dynamic Ads Feed ({country_code})"
    ET.SubElement(channel, 'link').text = GITHUB_PAGES_BASE_URL

    for product_data in processed_products:
        item = ET.SubElement(channel, 'item')
        
        for node in product_data['nodes']:
            if node.tag == '{http://base.google.com/ns/1.0}image_link':
                continue
            item.append(node)

        new_image_link = f"{GITHUB_PAGES_BASE_URL}/ad_{product_data['id']}_{product_data['data_hash']}.jpg" 
        ET.SubElement(item, '{http://base.google.com/ns/1.0}image_link').text = new_image_link
        
    tree = ET.ElementTree(rss)
    tree.write(META_FEED_FILENAME, encoding='utf-8', xml_declaration=True)
    
    print(f"Feed saved successfully: {META_FEED_FILENAME}")

def generate_tiktok_feed(processed_products, country_code):
    """Creates the final TikTok XML feed."""
    TIKTOK_FEED_FILENAME = f"ballzy_tiktok_{country_code.lower()}_ad_feed.xml"
    
    print(f"\nCreating TikTok XML Feed for {country_code}: {TIKTOK_FEED_FILENAME}")
    
    ET.register_namespace('', 'http://www.w3.org/2005/Atom')
    ET.register_namespace('g', 'http://base.google.com/ns/1.0')
    rss = ET.Element('rss', version="2.0", attrib={'xmlns:g': NAMESPACES['g']})
    channel = ET.SubElement(rss, 'channel')
    
    ET.SubElement(channel, 'title').text = f"Ballzy Dynamic TikTok Feed ({country_code})"
    ET.SubElement(channel, 'link').text = GITHUB_PAGES_BASE_URL

    tiktok_required_tags = [
        'id', 'title', 'description', 'availability', 'condition',
        'price', 'link', 'brand',
        'item_group_id', 'google_product_category', 'product_type',
        'sale_price', 'sale_price_effective_date', 'color', 'gender', 'size'
    ]
    
    tiktok_custom_labels = [f'custom_label_{i}' for i in range(5)]

    for product_data in processed_products:
        item = ET.SubElement(channel, 'item')
        
        def get_element(tag_name):
            return product_data['item_elements'].get(tag_name)

        for tag_name in tiktok_required_tags + tiktok_custom_labels:
            node = get_element(tag_name)
            
            if node is not None and node.text and node.text.strip():
                prefix = 'g:' if tag_name in ['id', 'title', 'description', 'price', 'sale_price', 'link', 'image_link', 'brand'] or tag_name.startswith('custom_label') else ''
                clean_text_content = node.text
                
                if prefix == 'g:':
                    ET.SubElement(item, '{' + NAMESPACES['g'] + '}' + tag_name).text = clean_text_content
                else:
                    ET.SubElement(item, tag_name).text = clean_text_content
        
        new_image_link = f"{GITHUB_PAGES_BASE_URL}/ad_{product_data['id']}_{product_data['data_hash']}.jpg"
        ET.SubElement(item, '{' + NAMESPACES['g'] + '}' + 'image_link').text = new_image_link

        additional_images = product_data['item_elements'].get('additional_image_link')
        if additional_images is not None and additional_images.text:
            ET.SubElement(item, '{' + NAMESPACES['g'] + '}' + 'additional_image_link').text = additional_images.text

    tree = ET.ElementTree(rss)
    tree.write(TIKTOK_FEED_FILENAME, encoding='utf-8', xml_declaration=True)
    
    print(f"Feed saved successfully: {TIKTOK_FEED_FILENAME}")

def generate_google_feed(processed_products, country_code):
    """Creates the final Google Merchant Center CSV feed."""
    GOOGLE_FEED_FILENAME = f"ballzy_{country_code.lower()}_google_feed.csv"
    
    print(f"\nCreating Google CSV Feed for {country_code}: {GOOGLE_FEED_FILENAME}")

    HEADERS = [
        "ID", "ID2", "Item title", "Final URL", "Image URL", "Item subtitle",
        "Item Description", "Item category", "Price", "Sale price",
        "Contextual keywords", "Item address", "Tracking template",
        "Custom parameter", "Final mobile URL", "Android app link",
        "iOS app link", "iOS app store ID", "Formatted price", "Formatted sale price"
    ]

    with open(GOOGLE_FEED_FILENAME, 'w', newline='', encoding='utf-8') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=HEADERS)
        writer.writeheader()

        for product_data in processed_products:
            
            def get_value(tag_name):
                node = product_data['item_elements'].get(tag_name)
                return node.text.strip() if node is not None and node.text is not None else ''

            keywords_list = []
            keywords_list.append(get_value('brand'))
            keywords_list.append(get_value('color'))
            
            for i in range(5):
                 keywords_list.append(get_value(f'custom_label_{i}'))

            contextual_keywords = ','.join(filter(None, keywords_list))
            
            row = {
                "ID": get_value('id'),
                "ID2": "",
                "Item title": get_value('title'),
                "Final URL": get_value('link'),
                "Image URL": f"{GITHUB_PAGES_BASE_URL}/ad_{product_data['id']}_{product_data['data_hash']}.jpg",
                "Item subtitle": "",
                "Item Description": get_value('description'),
                "Item category": get_value('google_product_category') or get_value('category'), 
                "Price": get_value('price'),
                "Sale price": get_value('sale_price'),
                "Contextual keywords": contextual_keywords,
                "Formatted price": product_data['formatted_price'],
                "Formatted sale price": product_data['formatted_sale_price'],
                "Item address": "", "Tracking template": "", "Custom parameter": "",
                "Final mobile URL": "", "Android app link": "", "iOS app link": "",
                "iOS app store ID": ""
            }
            
            writer.writerow(row)
            
    print(f"CSV Feed saved successfully: {GOOGLE_FEED_FILENAME}")


def process_single_feed(country_code, config, xml_file_path, template_hash):
    """Downloads, processes, and generates all required feeds for a single country."""

    print(f"\n--- 🚀 Starting Processing for {country_code} ---", flush=True)

    product_count = 0
    products_for_feed = [] 
    
    # 🟢 NEW: Set to store the exact filenames of currently valid images
    valid_ad_filenames = set()

    print(f"Processing feed for {country_code} from local file: {xml_file_path}", flush=True)

    try:
        tree = ET.parse(xml_file_path)
        root = tree.getroot()
    except ET.ParseError as e:
        print(f"FATAL ERROR: Could not parse XML feed for {country_code}. {e}", flush=True)
        print(f"--- 🛑 Processing Finished for {country_code} (Error) ---", flush=True)
        return
    except FileNotFoundError:
        print(f"FATAL ERROR: XML file not found for {country_code}.", flush=True)
        print(f"--- 🛑 Processing Finished for {country_code} (Error) ---", flush=True)
        return
        
    # ----------------------------------------------------------------------
    # 1. SYNCHRONOUS DATA EXTRACTION & FILTERING LOOP (Fast)
    # ----------------------------------------------------------------------
    for item in root.iter('item'):
        if product_count >= MAX_PRODUCTS_TO_GENERATE:
            break
            
        product_id_element = item.find('g:id', NAMESPACES)
        if product_id_element is None or product_id_element.text is None: continue
        product_id = product_id_element.text.strip()
        
        # --- PRODUCT FILTERING LOGIC ---
        is_correct_category = False
        category_element = None
        
        category_element = item.find('g:google_product_category', NAMESPACES)
        
        if category_element is None:
             category_element = item.find('g:category', NAMESPACES)

        if category_element is None:
             category_element = item.find('google_product_category', NAMESPACES)
             
        if category_element is not None and category_element.text is not None:
            category_text = category_element.text.strip().lower()
            
            if "street shoes" in category_text or "boots" in category_text:
                is_correct_category = True
        
        label_element = item.find('custom_label_0', NAMESPACES)
        is_lifestyle = False
        
        if label_element is not None and label_element.text is not None:
            if label_element.text.strip().lower() == "lifestyle":
                is_lifestyle = True
            
        if not is_correct_category or not is_lifestyle:
            continue
            
        # --- Price Extraction and Formatting ---
        sale_price_element = item.find('g:sale_price', NAMESPACES)
        price_element = item.find('g:price', NAMESPACES)
        
        raw_sale_price = sale_price_element.text if sale_price_element is not None else ""
        raw_price = price_element.text if price_element is not None else ""


        if sale_price_element is not None:
            display_price_element = sale_price_element
            final_price_color = SALE_PRICE_COLOR
            price_state = "sale"
        elif price_element is not None:
            display_price_element = price_element
            final_price_color = NORMAL_PRICE_COLOR
            price_state = "normal"
        else:
            continue
            
        def format_price(element):
            if element is None or element.text is None: return ""
            raw_price_str = element.text.split()[0]
            try:
                price_value = float(raw_price_str)
                currency_symbol = config['currency'].replace("EUR", "€")
                return f"{int(price_value)}{currency_symbol}" if price_value == int(price_value) else f"{price_value:.2f}{currency_symbol}"
            except ValueError:
                return raw_price_str.replace(" EUR", "€")

        formatted_display_price = format_price(display_price_element)
        
        # --- Image Link Extraction ---
        image_urls = []
        main_image = item.find('g:image_link', NAMESPACES)
        if main_image is not None and main_image.text:
            image_urls.append(main_image.text.strip())

        additional_images = item.findall('g:additional_image_link', NAMESPACES)
        for i, img in enumerate(additional_images):
            if i < 2 and img.text: image_urls.append(img.text.strip())
            
        if not image_urls: continue
        
        # Store all elements as a dictionary for easy CSV mapping and clean up nodes
        item_elements = {}
        for node in item:
            tag_name = node.tag.split('}')[-1]
            item_elements[tag_name] = node
            
            if tag_name in ['description', 'title', 'link']:
                node.text = clean_text(node.text)

        # 🟢 Hashing Logic - Now includes the dynamic template_hash
        data_string = "|".join([
            product_id,
            raw_sale_price,
            raw_price,
            str(image_urls),
            template_hash 
        ]).encode('utf-8')
        
        data_hash = hashlib.sha1(data_string).hexdigest()[:8]
        
        # 🟢 Add the final, correct filename to the set of valid files
        valid_ad_filenames.add(f"ad_{product_id}_{data_hash}.jpg")

        # GATHER ALL DATA FOR CONCURRENT IMAGE GENERATION
        products_for_feed.append({
            'id': product_id,
            'price_state': price_state,
            'formatted_price': format_price(price_element),
            'formatted_sale_price': format_price(sale_price_element),
            'item_elements': item_elements,
            'nodes': list(item),
            'image_urls': image_urls[:3], 
            'final_price_color': final_price_color, 
            'formatted_display_price': formatted_display_price,
            'data_hash': data_hash 
        })
        product_count += 1
        
    
    # ----------------------------------------------------------------------
    # 2. CONCURRENT IMAGE GENERATION (Fastest step)
    # ----------------------------------------------------------------------
    if products_for_feed:
        print(f"Starting concurrent image generation for {product_count} products...", flush=True)
        
        with ThreadPoolExecutor(max_workers=16) as executor:
            futures = []
            for product in products_for_feed:
                futures.append(executor.submit(
                    create_ballzy_ad,
                    product['image_urls'], 
                    product['formatted_display_price'], 
                    product['id'], 
                    product['final_price_color'],
                    product['data_hash'] 
                ))
            
            processed_images = 0
            for i, future in enumerate(as_completed(futures)):
                processed_images += 1
                try:
                    future.result() 
                    if processed_images % 50 == 0 or processed_images == len(futures):
                        print(f"  Images processed: {processed_images}/{len(futures)}", flush=True)
                except Exception as exc:
                    print(f"  Image generation failed: {exc}", flush=True)

        print("Concurrent image generation complete.", flush=True)
    
    # ----------------------------------------------------------------------
    # 3. SYNCHRONOUS FEED GENERATION
    # ----------------------------------------------------------------------
    if products_for_feed:
        # Generate feeds first to ensure the final output is ready
        generate_meta_feed(products_for_feed, country_code)
        if config['google_feed_required']:
            generate_google_feed(products_for_feed, country_code)
        generate_tiktok_feed(products_for_feed, country_code)
        
        # 🟢 NEW: CLEANUP STEP
        cleanup_orphaned_ads(valid_ad_filenames)
        
    else:
        print(f"No products matched filtering criteria for {country_code}. No feeds generated.", flush=True)

    print(f"--- ✅ Processing Finished for {country_code} ---", flush=True)


def process_all_feeds(country_configs):
    """Main entry point to iterate and process all configured countries."""
    print("Starting Multi-Country Feed Generation...", flush=True)
    
    # Calculate Template Hash ONCE
    template_hash = get_template_file_hash()
    print(f"Current Template Hash: {template_hash}")
    
    # --- Step 1: Download all feeds first ---
    downloaded_files = {}
    for code, config in country_configs.items():
        file_path = download_feed_xml(code, config['feed_url'])
        if file_path:
            downloaded_files[code] = file_path
    
    print("-" * 50, flush=True)

    # --- Step 2: Process individual feeds with filtering/limits ---
    for code, config in country_configs.items():
        if code in downloaded_files:
            # Pass the template_hash to the single feed processor
            process_single_feed(code, config, downloaded_files[code], template_hash)
            print("-" * 50, flush=True)
        else:
            print(f"Skipping processing for {code} due to previous download error.", flush=True)
            print("-" * 50, flush=True)

    print("All Feeds Generated.", flush=True)


# --- 5. EXECUTION ---

if __name__ == "__main__":
    process_all_feeds(COUNTRY_CONFIGS)
