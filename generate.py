import requests
import os
import xml.etree.ElementTree as ET
from io import BytesIO
from PIL import Image, ImageOps, ImageDraw, ImageFont
import csv
import re
import html

# --- 1. CONFIGURATION ---

# 1.1. Feed Sources, Constants, and Country Configurations
OUTPUT_DIR = "generated_ads" 
MAX_PRODUCTS_TO_GENERATE = 50 
TEMP_DOWNLOAD_DIR = "temp_xml_feeds" # New directory for source XML downloads

# 🟢 IMPORTANT: Centralized configuration for all countries
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
GITHUB_PAGES_BASE_URL = "https://tanelneemoja.github.io/testing-somecool-stuff/generated_ads" 

# XML Namespaces
NAMESPACES = {
    'g': 'http://base.google.com/ns/1.0'
}
NS = NAMESPACES # Alias for cleaner use in contamination report

# Define color constants
NORMAL_PRICE_COLOR = "#0055FF" 
SALE_PRICE_COLOR = "#cc02d2" 
 
# 1.2. Figma Design Layout & Image Fitting
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

# --- 2. HELPER FUNCTIONS ---

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

def create_ballzy_ad(image_urls, price_text, product_id, price_color):
    """Generates the single stylized image based on the Ballzy layout."""
    
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
            print(f"Error processing image {url} for product {product_id}: {e}")

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
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    output_path = os.path.join(OUTPUT_DIR, f"ad_{product_id}.jpg")
    base.convert("RGB").save(output_path, format="JPEG", quality=95)
    return output_path

# --- 3. CONTAMINATION REPORT LOGIC (FINALIZED and Streamlined) ---

def create_estonian_contamination_report(xml_path):
    """
    Reads the full LT feed XML file and generates a CSV report of all products
    whose g:description contains Estonian markers.

    The report includes ID, Title, Description, and Link for tracking purposes.
    The output file is GUARANTEED to be created with headers, even if empty.
    """
    # Use the NAMESPACES alias defined globally in your script
    NS = {'g': 'http://base.google.com/ns/1.0'} 
    import xml.etree.ElementTree as ET # Ensure ET is available

    if not os.path.exists(xml_path):
        print(f"Error: XML file not found at {xml_path}")
        return

    REPORT_CSV_FILE = "LT_Estonian_Contamination_Report.csv"
    
    # 🟢 CORE DETECTION: Estonian-specific letters and strong indicator words
    # This list is used to check the description content only.
    ESTONIAN_MARKERS = ['ö', 'ä', 'ü', 'õ', 'eesti', 'saadaval', 'vaata', 'pood', 'ning', 'kohe']
    
    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
    except Exception as e:
        print(f"Error parsing XML file {xml_path}: {e}")
        return

    product_elements = root.findall('./channel/item')
    contaminated_products = []

    print(f"\n🔎 Starting final contamination check on {len(product_elements)} products in LT feed...")

    for item in product_elements:
        # --- Data Extraction (Used for Report Columns) ---
        product_id = item.find('g:id', NS).text if item.find('g:id', NS) is not None and item.find('g:id', NS).text else 'N/A'
        title_node = item.find('g:title')
        description_node = item.find('g:description', NS) 
        link_node = item.find('g:link') 

        title_text = title_node.text.strip() if title_node is not None and title_node.text else ''
        description_text = description_node.text.strip() if description_node is not None and description_node.text else ''
        link_text = link_node.text.strip() if link_node is not None and link_node.text else ''
        
        # --- Contamination Check Logic (Only uses description text) ---
        check_text = description_text.lower()
        
        # Check for any of the Estonian markers in the description text
        is_contaminated = any(marker in check_text for marker in ESTONIAN_MARKERS)

        if is_contaminated:
            contaminated_products.append({
                'ID': product_id,
                'Title': title_text,
                'Description': description_text.replace('\n', ' '), # Full contaminated description
                'Link': link_text # Link for tracking
            })

    # --- Write the Report CSV (GUARANTEED OUTPUT) ---
    import csv # Ensure CSV is imported
    with open(REPORT_CSV_FILE, 'w', newline='', encoding='utf-8') as csvfile:
        fieldnames = ['ID', 'Title', 'Description', 'Link']
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        
        writer.writeheader()
        
        if contaminated_products:
            writer.writerows(contaminated_products)
            print(f"⚠️ Successfully created contamination report: {REPORT_CSV_FILE} with {len(contaminated_products)} problematic products.")
        else:
            print(f"✅ Full report check completed. No highly contaminated products found. Report file created with headers only.")

# --- 4. FEED GENERATION LOGIC ---

def generate_meta_feed(processed_products, country_code):
    """Creates the final Meta XML feed."""
    META_FEED_FILENAME = f"ballzy_{country_code.lower()}_ad_feed.xml"
    
    print(f"\nCreating final Meta Feed for {country_code}: {META_FEED_FILENAME}")
    
    # 1. Setup Root and Channel
    ET.register_namespace('', 'http://www.w3.org/2005/Atom')
    ET.register_namespace('g', 'http://base.google.com/ns/1.0')
    rss = ET.Element('rss', version="2.0")
    channel = ET.SubElement(rss, 'channel')
    
    ET.SubElement(channel, 'title').text = f"Ballzy Dynamic Ads Feed ({country_code})"
    ET.SubElement(channel, 'link').text = GITHUB_PAGES_BASE_URL

    for product_data in processed_products:
        item = ET.SubElement(channel, 'item')
        
        # 2. Append all original nodes, excluding the old image link
        for node in product_data['nodes']:
            if node.tag == '{http://base.google.com/ns/1.0}image_link':
                continue 
            item.append(node)

        # 3. Add the new image link node
        new_image_link = f"{GITHUB_PAGES_BASE_URL}/ad_{product_data['id']}.jpg"
        ET.SubElement(item, '{http://base.google.com/ns/1.0}image_link').text = new_image_link
        
    # 5. Save the resulting XML tree to a file
    tree = ET.ElementTree(rss)
    tree.write(META_FEED_FILENAME, encoding='utf-8', xml_declaration=True)
    
    print(f"Feed saved successfully: {META_FEED_FILENAME}")

def generate_tiktok_feed(processed_products, country_code):
    """Creates the final TikTok XML feed."""
    TIKTOK_FEED_FILENAME = f"ballzy_tiktok_{country_code.lower()}_ad_feed.xml"
    
    print(f"\nCreating TikTok XML Feed for {country_code}: {TIKTOK_FEED_FILENAME}")
    
    # 1. Setup Root and Channel
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
        
        # 3. Add the NEW IMAGE LINK
        new_image_link = f"{GITHUB_PAGES_BASE_URL}/ad_{product_data['id']}.jpg"
        ET.SubElement(item, '{' + NAMESPACES['g'] + '}' + 'image_link').text = new_image_link

        # 4. Add additional image links (Optional but useful)
        additional_images = product_data['item_elements'].get('additional_image_link')
        if additional_images is not None and additional_images.text:
            ET.SubElement(item, '{' + NAMESPACES['g'] + '}' + 'additional_image_link').text = additional_images.text

    # 5. Save the resulting XML tree to a file
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
                # Check for node and text existence to prevent AttributeError
                return node.text.strip() if node is not None and node.text is not None else '' 

            # 1. Map Contextual Keywords
            keywords_list = []
            keywords_list.append(get_value('brand'))
            keywords_list.append(get_value('color'))
            
            for i in range(5):
                 keywords_list.append(get_value(f'custom_label_{i}'))

            contextual_keywords = ','.join(filter(None, keywords_list))
            
            # 2. Build the Row
            row = {
                "ID": get_value('id'),
                "ID2": "", 
                "Item title": get_value('title'),
                "Final URL": get_value('link'),
                "Image URL": f"{GITHUB_PAGES_BASE_URL}/ad_{product_data['id']}.jpg",
                "Item subtitle": "", 
                "Item Description": get_value('description'),
                "Item category": get_value('google_product_category') or get_value('category'), # Handle g:category too
                "Price": get_value('price'),
                "Sale price": get_value('sale_price'), 
                "Contextual keywords": contextual_keywords,
                "Formatted price": product_data['formatted_price'],
                "Formatted sale price": product_data['formatted_sale_price'],
                # All other fields remain empty
                "Item address": "", "Tracking template": "", "Custom parameter": "", 
                "Final mobile URL": "", "Android app link": "", "iOS app link": "", 
                "iOS app store ID": ""
            }
            
            writer.writerow(row)
            
    print(f"CSV Feed saved successfully: {GOOGLE_FEED_FILENAME}")

def process_single_feed(country_code, config, xml_file_path):
    """Downloads, processes, and generates all required feeds for a single country."""
    
    # 🟢 FIX: Initialize variables at the start to prevent NameError
    product_count = 0
    products_for_feed = []
    
    print(f"\nProcessing feed for {country_code} from local file: {xml_file_path}")

    try:
        # Load from the file path provided by the main function
        tree = ET.parse(xml_file_path)
        root = tree.getroot()
    except ET.ParseError as e:
        print(f"FATAL ERROR: Could not parse XML feed for {country_code}. {e}")
        return
    except FileNotFoundError:
        print(f"FATAL ERROR: XML file not found for {country_code}.")
        return

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    for item in root.iter('item'): 
        if product_count >= MAX_PRODUCTS_TO_GENERATE:
            break
            
        product_id_element = item.find('g:id', NAMESPACES)
        if product_id_element is None or product_id_element.text is None: continue
        product_id = product_id_element.text.strip()
        
        # --- PRODUCT FILTERING LOGIC ---
        is_correct_category = False
        category_element = None
        
        # 1. Try specific Google tag
        category_element = item.find('g:google_product_category', NAMESPACES)
        
        # 2. Try the general Google category tag (LV/LT/FI FIX)
        if category_element is None:
             category_element = item.find('g:category', NAMESPACES)

        # 3. Try the un-prefixed specific tag
        if category_element is None:
             category_element = item.find('google_product_category', NAMESPACES)
             
        if category_element is not None and category_element.text is not None:
            category_text = category_element.text.strip().lower()
            
            # Check for English terms
            if "street shoes" in category_text or "boots" in category_text:
                is_correct_category = True
        
        # 🟢 FIX: Use un-prefixed tag for custom_label_0 (Confirmed by client)
        label_element = item.find('custom_label_0', NAMESPACES) 
        is_lifestyle = False
        
        if label_element is not None and label_element.text is not None: 
            # Use the robust check (strip and lower()) to catch variations
            if label_element.text.strip().lower() == "lifestyle": 
                is_lifestyle = True
            
        if not is_correct_category or not is_lifestyle:
            continue
            
        # --- Price Extraction and Formatting ---
        sale_price_element = item.find('g:sale_price', NAMESPACES)
        price_element = item.find('g:price', NAMESPACES)

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

        products_for_feed.append({
            'id': product_id,
            'price_state': price_state, 
            'formatted_price': format_price(price_element),
            'formatted_sale_price': format_price(sale_price_element),
            'item_elements': item_elements,
            'nodes': list(item)
        })

        # Generate Image 
        image_urls_for_ad = image_urls[:3]
        create_ballzy_ad(image_urls_for_ad, formatted_display_price, product_id, final_price_color)
        product_count += 1
        
    # --- Execute Feed Generation (using the country code) ---
    if products_for_feed:
        # 1. Meta XML
        generate_meta_feed(products_for_feed, country_code)
        
        # 2. Google CSV
        if config['google_feed_required']:
            generate_google_feed(products_for_feed, country_code)
            
        # 3. TikTok XML
        generate_tiktok_feed(products_for_feed, country_code)
        
    else:
        print(f"No products matched filtering criteria for {country_code}. No feeds generated.")

def process_all_feeds(country_configs):
    """Main entry point to iterate and process all configured countries."""
    print("Starting Multi-Country Feed Generation...")
    
    # --- Step 1: Download all feeds first ---
    downloaded_files = {}
    for code, config in country_configs.items():
        file_path = download_feed_xml(code, config['feed_url'])
        if file_path:
            downloaded_files[code] = file_path
    
    print("-" * 50)

    # --- Step 2: Run Contamination Report for LT (on the full file) ---
    if 'LT' in downloaded_files:
        create_estonian_contamination_report(downloaded_files['LT'])
        print("-" * 50)
        
    # --- Step 3: Process individual feeds with filtering/limits ---
    for code, config in country_configs.items():
        if code in downloaded_files:
            process_single_feed(code, config, downloaded_files[code])
            print("-" * 50)
        else:
            print(f"Skipping processing for {code} due to previous download error.")
            print("-" * 50)

    print("All Feeds Generated.")


# --- 5. EXECUTION ---

if __name__ == "__main__":
    process_all_feeds(COUNTRY_CONFIGS)
