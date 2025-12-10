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

# 🟢 IMPORTANT: Centralized configuration for all countries
COUNTRY_CONFIGS = {
    "EE": {
        # Assuming EE URL remains the same
        "feed_url": "https://backend.ballzy.eu/et/amfeed/feed/download?id=102&file=cropink_et.xml",
        "currency": "EUR",
        "google_feed_required": True,
        "language_code": "et"
    },
    "LV": {
        # 🟢 UPDATED LV URL
        "feed_url": "https://backend.ballzy.eu/lv/amfeed/feed/download?id=104&file=cropink_lv.xml",
        "currency": "EUR",
        "google_feed_required": True,
        "language_code": "lv"
    },
    "LT": {
        # 🟢 UPDATED LT URL
        "feed_url": "https://backend.ballzy.eu/lt/amfeed/feed/download?id=105&file=cropink_lt.xml",
        "currency": "EUR",
        "google_feed_required": True,
        "language_code": "lt"
    },
    "FI": {
        # 🟢 UPDATED FI URL
        "feed_url": "https://backend.ballzy.eu/fi/amfeed/feed/download?id=103&file=cropink_fi.xml",
        "currency": "EUR",
        "google_feed_required": False, # Google feed is still skipped for FI
        "language_code": "fi"
    }
}


# Public Hosting Configuration
GITHUB_PAGES_BASE_URL = "https://tanelneemoja.github.io/testing-somecool-stuff/generated_ads" 

# XML Namespaces
NAMESPACES = {
    'g': 'http://base.google.com/ns/1.0'
}
# Define color constants (you can adjust these hex codes)
NORMAL_PRICE_COLOR = "#0055FF" # Original Ballzy blue
SALE_PRICE_COLOR = "#cc02d2"   # A standard purple color  
# 1.2. Figma Design Layout & Image Fitting
# These coordinates are adjusted based on your latest feedback.
LAYOUT_CONFIG = {
    "canvas_size": (1200, 1200), 
    "template_path": "assets/ballzy_template.png", # Ensure this file is uploaded!
    "slots": [
        # Slot 1: Top Left - Adjusted up and larger
        {"x": 25, "y": 25, "w": 606, "h": 700, "center_y": 0.5}, 
        
        # Slot 2: Middle Right - Adjusted right and larger
        {"x": 656, "y": 305, "w": 522, "h": 624, "center_y": 0.6}, 
        
        # Slot 3: Bottom Left - Adjusted lower and left
        {"x": 25, "y": 823, "w": 606, "h": 350, "center_y": 0.5}
    ],
    "price": {
        "x": 920,   # Adjusted right
        "y": 1050,   # Adjusted lower
        "font_size": 80,
        "font_path": "assets/fonts/poppins.medium.ttf",
     # NEW: Rectangle Dimensions (Matches Slot 2 Width)
        "rect_x0": 656,  # Starting X (left edge of Slot 2)
        "rect_y0": 950,  # Starting Y (Adjusted for position below Slot 2)
        "rect_x1": 1178, # Ending X (656 + 522 = 1178, right edge of Slot 2)
        "rect_y1": 1175, # Ending Y (Bottom edge of canvas/price area)
    }
}
def clean_text(text):
    """Removes HTML tags and decodes HTML entities (like &hellip;) from a string."""
    if not text:
        return ""
    
    # 1. Decode HTML entities (e.g., &hellip; -> ...)
    text = html.unescape(text)
    
    # 2. Strip HTML/XML tags (e.g., <html>, <body>, <p>, <br/>)
    # This pattern matches anything between < and >
    clean = re.sub('<[^>]*>', '', text)
    
    # 3. Clean up the specific extra text observed in your example
    clean = clean.replace('Vaata lähemalt ballzy.eu.', '').strip()
    
    return clean
# --- 2. IMAGE GENERATION LOGIC (FINALIZED) ---

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

# --- 3. XML FEED PROCESSING LOGIC ---

def generate_meta_feed(processed_products, country_code):
    # 🟢 NEW: Dynamic Filename
    META_FEED_FILENAME = f"ballzy_{country_code.lower()}_ad_feed.xml"
    
    print(f"\nCreating final Meta Feed: {META_FEED_FILENAME}")
    
    # 1. Setup Root and Channel
    ET.register_namespace('', 'http://www.w3.org/2005/Atom')
    ET.register_namespace('g', 'http://base.google.com/ns/1.0')
    rss = ET.Element('rss', version="2.0")
    channel = ET.SubElement(rss, 'channel')
    
    ET.SubElement(channel, 'title').text = "Ballzy Dynamic Ads Feed"
    ET.SubElement(channel, 'link').text = GITHUB_PAGES_BASE_URL

    for product_data in processed_products:
        item = ET.SubElement(channel, 'item')
        
        # 2. Append all original nodes, excluding the old image link
        for node in product_data['nodes']:
            # Check the full tag name with namespace
            if node.tag == '{http://base.google.com/ns/1.0}image_link':
                continue 
            
            # Append the node
            item.append(node)

        # 3. Add the new image link node
        new_image_link = f"{GITHUB_PAGES_BASE_URL}/ad_{product_data['id']}.jpg"
        ET.SubElement(item, '{http://base.google.com/ns/1.0}image_link').text = new_image_link
        
        # 4. REMOVED: The problematic line adding <g:custom_label_4> is removed
        # (The original <custom_label_4> will be retained from the copied nodes)
    
    # 5. Save the resulting XML tree to a file
    tree = ET.ElementTree(rss)
    tree.write(META_FEED_FILENAME, encoding='utf-8', xml_declaration=True)
    
    print(f"Feed saved successfully: {META_FEED_FILENAME}")

def generate_tiktok_feed(processed_products, country_code):
     # 🟢 NEW: Dynamic Filename
    TIKTOK_FEED_FILENAME = f"ballzy_tiktok_{country_code.lower()}_ad_feed.xml"
    
    print(f"\nCreating final Meta Feed: {TIKTOK_FEED_FILENAME}")
    
    # 1. Setup Root and Channel
    ET.register_namespace('', 'http://www.w3.org/2005/Atom')
    ET.register_namespace('g', 'http://base.google.com/ns/1.0')
    rss = ET.Element('rss', version="2.0", attrib={'xmlns:g': NAMESPACES['g']}) # 💡 Note the namespace fix
    channel = ET.SubElement(rss, 'channel')
    
    ET.SubElement(channel, 'title').text = "Ballzy Dynamic TikTok Feed"
    ET.SubElement(channel, 'link').text = GITHUB_PAGES_BASE_URL

    # Required TikTok fields
    tiktok_required_tags = [
        'id', 'title', 'description', 'availability', 'condition', 
        'price', 'link', 'brand', 
        'item_group_id', 'google_product_category', 'product_type',
        'sale_price', 'sale_price_effective_date', 'color', 'gender', 'size'
    ]
    
    # Custom Labels
    tiktok_custom_labels = [f'custom_label_{i}' for i in range(5)]

    for product_data in processed_products:
        item = ET.SubElement(channel, 'item')
        
        # Helper to get the element from the stored dictionary
        def get_element(tag_name):
            return product_data['item_elements'].get(tag_name)

        # 2. Add Required and Recommended Nodes
        for tag_name in tiktok_required_tags + tiktok_custom_labels:
            node = get_element(tag_name)
            
            # Check if the node exists and has text content
            if node is not None and node.text and node.text.strip():
                # Recreate the element to ensure clean XML structure
                
                # Check if it's a Google tag (g:) or a standard tag
                prefix = 'g:' if tag_name in ['id', 'title', 'description', 'price', 'sale_price', 'link', 'image_link', 'brand'] or tag_name.startswith('custom_label') else ''
                
                # Use the clean text already applied in process_feed
                clean_text_content = node.text 
                
                if prefix == 'g:':
                    # Create g: tags with namespace
                    ET.SubElement(item, '{' + NAMESPACES['g'] + '}' + tag_name).text = clean_text_content
                else:
                    # Create standard tags (e.g., availability, condition)
                    ET.SubElement(item, tag_name).text = clean_text_content
        
        # 3. Add the NEW IMAGE LINK (Required)
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
     # 🟢 NEW: Dynamic Filename
    GOOGLE_FEED_FILENAME = f"ballzy_{country_code.lower()}_google_feed.csv"
    
    print(f"\nCreating final Meta Feed: {GOOGLE_FEED_FILENAME}")

    # Define the required Google Headers
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
            # Helper to quickly find a value by its Google/Custom tag
            def get_value(tag_name):
                # Search nodes for the tag (handle both g: and non-g: for custom labels)
                node = product_data['item_elements'].get(tag_name)
                return node.text.strip() if node is not None else ''

            # 1. Map Contextual Keywords
            keywords_list = []
            keywords_list.append(get_value('brand'))
            keywords_list.append(get_value('color'))
            
            # Custom labels (g:custom_label_0 -> custom_label_0)
            for i in range(5):
                 keywords_list.append(get_value(f'custom_label_{i}'))

            # Filter out empty strings and join with a comma
            contextual_keywords = ','.join(filter(None, keywords_list))
            
            # 2. Build the Row
            row = {
                "ID": get_value('id'),
                "ID2": "", # Empty
                "Item title": get_value('title'),
                "Final URL": get_value('link'),
                "Image URL": f"{GITHUB_PAGES_BASE_URL}/ad_{product_data['id']}.jpg", # Our new image link
                "Item subtitle": "", # Empty
                "Item Description": get_value('description'),
                "Item category": get_value('google_product_category'),
                "Price": get_value('price'),
                "Sale price": get_value('sale_price'), 
                "Contextual keywords": contextual_keywords,
                "Item address": "", # Empty
                "Tracking template": "", # Empty
                "Custom parameter": "", # Empty
                "Final mobile URL": "", # Empty
                "Android app link": "", # Empty
                "iOS app link": "", # Empty
                "iOS app store ID": "", # Empty
                # Format the prices to match your previous formatting
                "Formatted price": product_data['formatted_price'],
                "Formatted sale price": product_data['formatted_sale_price']
            }
            
            writer.writerow(row)
            
    print(f"CSV Feed saved successfully: {GOOGLE_FEED_FILENAME}")

def process_single_feed(country_code, config):
    """Downloads, processes, and generates all required feeds for a single country."""
    url = config['feed_url']
    
    # 🟢 FIX: Initialize variables at the start to prevent NameError
    product_count = 0
    products_for_feed = []
    
    print(f"Downloading feed for {country_code} from: {url}")
    try:
        feed_response = requests.get(url, timeout=30)
        feed_response.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"FATAL ERROR: Could not download feed for {country_code}. {e}")
        return

    try:
        root = ET.fromstring(feed_response.content)
    except ET.ParseError as e:
        print(f"FATAL ERROR: Could not parse XML feed for {country_code}. {e}")
        return

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    for item in root.iter('item'): 
        if product_count >= MAX_PRODUCTS_TO_GENERATE:
            break
            
        product_id_element = item.find('g:id', NAMESPACES)
        if product_id_element is None: continue
        product_id = product_id_element.text.strip()
        
        # --- PRODUCT FILTERING LOGIC ---
        category_element = item.find('g:google_product_category', NAMESPACES)
        is_correct_category = False
        if category_element is not None:
            category_text = category_element.text.strip().lower()
            if "street shoes" in category_text or "boots" in category_text:
                is_correct_category = True
        
        label_element = item.find('custom_label_0', NAMESPACES)
        is_lifestyle = False
        
        # 🟢 FIX: Check that label_element is not None AND its .text attribute is not None
        if label_element is not None and label_element.text is not None: 
            if label_element.text.strip() == "Lifestyle":
                is_lifestyle = True
            
        if not is_correct_category or not is_lifestyle:
            continue 
            
        # --- Price Extraction and Formatting ---
        sale_price_element = item.find('g:sale_price', NAMESPACES)
        price_element = item.find('g:price', NAMESPACES)

        # Determine price to display and color
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
            
        # Helper to extract and format a price element
        def format_price(element):
            if element is None: return ""
            raw_price_str = element.text.split()[0]
            try:
                price_value = float(raw_price_str)
                # Use the country's currency from the config (although currently hardcoded to EUR)
                currency_symbol = config['currency'].replace("EUR", "€") 
                return f"{int(price_value)}{currency_symbol}" if price_value == int(price_value) else f"{price_value:.2f}{currency_symbol}"
            except ValueError:
                return raw_price_str.replace(" EUR", "€") # Fallback

        formatted_display_price = format_price(display_price_element)
        
        # --- Image Link Extraction ---
        image_urls = []
        main_image = item.find('g:image_link', NAMESPACES)
        if main_image is not None:
            image_urls.append(main_image.text.strip())

        additional_images = item.findall('g:additional_image_link', NAMESPACES)
        # Take up to 2 additional images
        for i, img in enumerate(additional_images):
            if i < 2: image_urls.append(img.text.strip())
            
        if not image_urls: continue # Skip if no images found
        
        # Store all elements as a dictionary for easy CSV mapping and clean up nodes
        item_elements = {}
        for node in item:
            # Normalize tag names for dictionary keys (remove namespace prefix)
            tag_name = node.tag.split('}')[-1]
            item_elements[tag_name] = node
            
            # 🟢 APPLY CLEANING directly to the node's text for XML/CSV
            if tag_name in ['description', 'title', 'link']:
                node.text = clean_text(node.text)

        # Store all original nodes and critical data for the final feeds
        products_for_feed.append({
            'id': product_id,
            'price_state': price_state, 
            'formatted_price': format_price(price_element),
            'formatted_sale_price': format_price(sale_price_element),
            'item_elements': item_elements, # Dictionary of nodes for easy CSV lookup
            'nodes': list(item) # List of original nodes for XML copy (now cleaned)
        })

        # Generate Image 
        image_urls_for_ad = image_urls[:3] # Ensure only max 3 are used by the ad template
        create_ballzy_ad(image_urls_for_ad, formatted_display_price, product_id, final_price_color)
        product_count += 1
        
    # --- Execute Feed Generation (using the country code) ---
    if products_for_feed:
        # 1. Meta XML (Required for all)
        generate_meta_feed(products_for_feed, country_code)
        
        # 2. Google CSV (Conditional)
        if config['google_feed_required']:
            generate_google_feed(products_for_feed, country_code)
            
        # 3. TikTok XML (Required for all)
        generate_tiktok_feed(products_for_feed, country_code)
        
    else:
        print(f"No products matched filtering criteria for {country_code}. No feeds generated.")

def process_all_feeds(country_configs):
    """Main entry point to iterate and process all configured countries."""
    print("Starting Multi-Country Feed Generation...")
    for code, config in country_configs.items():
        process_single_feed(code, config)
        print("-" * 50)
    print("All Feeds Generated.")


# --- 4. EXECUTION ---

if __name__ == "__main__":
    process_all_feeds(COUNTRY_CONFIGS)
