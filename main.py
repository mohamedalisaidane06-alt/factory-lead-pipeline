import os
import re
import json
import requests
import feedparser
from bs4 import BeautifulSoup
from groq import Groq
from duckduckgo_search import DDGS

# 1. Environment Secrets & Airtable Configuration
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
AIRTABLE_API_KEY = os.environ.get("AIRTABLE_API_KEY")
AIRTABLE_BASE_ID = os.environ.get("AIRTABLE_BASE_ID")

AIRTABLE_TABLE_NAME = "Garden factory leads"

# Exact 50 Brico/Jardin Target Products
TARGET_PRODUCTS = [
    "Hand trowel", "Pruning shears", "Gardening gloves", "Leaf rake", "Weed puller",
    "Wheelbarrow", "Potting soil", "Organic fertilizer", "Flower seed packets", "Bamboo plant stakes",
    "Compost bags", "Weed killer spray", "Solar LED stakes", "Citronella candles", "Ceramic flower pots",
    "Plastic planters", "Decorative pebbles", "Outdoor string lights", "Expandable garden hose", "Multi-pattern spray nozzle",
    "Plastic watering can", "Oscillating lawn sprinkler", "Hose reel cart", "Drip irrigation kit", "Patio cleaner fluid",
    "Heavy-duty waste bags", "Fabric shade sail", "Folding bistro set", "Weatherproof seat cushions", "Winter plant fleece",
    "Plastic garden borders", "Wooden trellis panels", "Tool wall organizer", "Storage cushion box", "Greenhouse plastic covers",
    "Water butt tank", "Automated water timer", "Bird deterrent tape", "Insect hotel", "Slug copper tape",
    "Weed barrier fabric", "Artificial grass tiles", "Grass seed mix", "Lawn moss killer", "Solar fountain pump",
    "Macrame plant hangers", "Outdoor rug", "Garden kneeler pad", "Citronella incense sticks"
]

# 2. Fetch Existing Airtable Company Names (for Deduplication)
existing_companies = set()
try:
    airtable_get_url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{requests.utils.quote(AIRTABLE_TABLE_NAME)}?fields[]=Company+Name"
    headers = {"Authorization": f"Bearer {AIRTABLE_API_KEY}"}
    res_get = requests.get(airtable_get_url, headers=headers, timeout=10)
    if res_get.status_code == 200:
        records = res_get.json().get("records", [])
        for r in records:
            name = r.get("fields", {}).get("Company Name", "").strip().lower()
            if name:
                existing_companies.add(name)
    print(f"Loaded {len(existing_companies)} existing records for deduplication check.")
except Exception as e:
    print(f"Warning fetching existing Airtable records: {e}")

all_raw_leads = []

# --- SOURCE 1: Google News RSS (Expanded to 1 Year / when:1y with Target Products) ---
try:
    google_url = (
        "https://news.google.com/rss/search?q="
        "%22factory%22+OR+%22manufacturer%22+OR+%22producer%22+OR+%22production%22+"
        "%22China%22+OR+%22Taiwan%22+OR+%22Hong+Kong%22+"
        "%22Hand+trowel%22+OR+%22Pruning+shears%22+OR+%22Gardening+gloves%22+OR+%22Leaf+rake%22+OR+%22Wheelbarrow%22+OR+"
        "%22Solar+LED+stakes%22+OR+%22Plastic+planters%22+OR+%22Expandable+garden+hose%22+OR+%22Drip+irrigation+kit%22+OR+%22Fabric+shade+sail%22"
        "+when:1y&hl=en-US&gl=US&ceid=US:en"
    )
    feed = feedparser.parse(google_url)
    for entry in feed.entries[:10]:
        all_raw_leads.append({
            "source": "Google News",
            "title": entry.get("title", ""),
            "summary": entry.get("summary", ""),
            "url": entry.get("link", "")
        })
except Exception as e:
    print(f"Google News fetch error: {e}")

# --- SOURCE 2: DuckDuckGo (Targeting Manufacturers & 50 Products) ---
try:
    ddg_query = '("factory" OR "manufacturer" OR "producer" OR "crafting") ("China" OR "Taiwan" OR "Hong Kong") ("Hand trowel" OR "Pruning shears" OR "Gardening gloves" OR "Wheelbarrow" OR "Solar LED stakes" OR "Plastic planters" OR "Expandable garden hose")'
    ddg_results = DDGS().text(ddg_query, max_results=8)
    if ddg_results:
        for r in ddg_results:
            all_raw_leads.append({
                "source": "DuckDuckGo",
                "title": r.get("title", ""),
                "summary": r.get("body", ""),
                "url": r.get("href", "")
            })
except Exception as e:
    print(f"DuckDuckGo fetch error: {e}")

# --- SOURCE 3: Baidu (Targeting Chinese Factory Domains / 1688 / .cn) ---
try:
    baidu_url = "https://www.baidu.com/s?wd=%22%E7%94%9F%E4%BA%A7%E5%8E%82%E5%AE%B6%22+%22%E4%B8%AD%E5%9B%BD%22+(%22%E5%9B%AD%E8%89%BA%E5%B7%A5%E5%85%B7%22+OR+%22%E8%8A%B1%E7%9B%86%22+OR+%22%E9%99%84%E4%BB%B6%22)+-%E9%98%BF%E9%87%8C"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"}
    res = requests.get(baidu_url, headers=headers, timeout=10)
    if res.status_code == 200:
        soup = BeautifulSoup(res.text, "html.parser")
        containers = soup.find_all("div", class_=re.compile("c-container"))
        for item in containers[:5]:
            title_tag = item.find("h3")
            abstract_tag = item.find("div", class_=re.compile("c-abstract|c-span"))
            link_tag = item.find("a")
            if title_tag:
                all_raw_leads.append({
                    "source": "Baidu",
                    "title": title_tag.get_text(strip=True),
                    "summary": abstract_tag.get_text(strip=True) if abstract_tag else "",
                    "url": link_tag.get("href", "https://www.baidu.com") if link_tag else "https://www.baidu.com"
                })
except Exception as e:
    print(f"Baidu fetch error: {e}")

if not all_raw_leads:
    print("No supplier leads retrieved.")
    exit(0)

client = Groq(api_key=GROQ_API_KEY)

# Helper function with active model fallback
def query_groq_with_fallback(prompt):
    models_to_try = [
        "openai/gpt-oss-20b",
        "openai/gpt-oss-120b"
    ]
    for model_name in models_to_try:
        try:
            response = client.chat.completions.create(
                model=model_name,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1
            )
            return response.choices[0].message.content
        except Exception as e:
            if "404" in str(e) or "model_not_found" in str(e) or "decommissioned" in str(e):
                print(f"Model '{model_name}' unavailable, trying next fallback...")
                continue
            else:
                raise e
    raise Exception("All fallback Groq models failed.")

# 3. Process Leads via Groq AI
products_list_str = ", ".join(TARGET_PRODUCTS)

for lead in all_raw_leads:
    title = lead["title"]
    summary = lead["summary"]
    source_engine = lead["source"]
    link = lead["url"]

    prompt = f"""
You are an expert global sourcing specialist for European discount retail chains (e.g., NOZ) specializing in Brico/Jardin-Animalerie categories.
Analyze this supplier lead retrieved from search engine: {source_engine}

Title: {title}
Summary: {summary}

### Target Product Scope (STRICT MATCH ONLY):
[{products_list_str}]

### Strict Audit Rules:
1. MANUFACTURER / PRODUCER ONLY: Must be a direct factory, producer, crafting plant, OEM/ODM (Prioritize official domains like .cn, .com.cn, .tw, .hk, or 1688 factory storefronts). STRICTLY EXCLUDE trading companies, agents, wholesalers, or generic B2B directories.
2. GEOGRAPHY PRIORITY:
   - Primary Choice: Mainland China
   - Secondary Choice: Taiwan
   - Final/Last Choice: Hong Kong
3. IFLS TAXONOMY (MANDATORY CLASSIFICATION):
   - Personal Well-Being (Level 2: Pet Accessories, Dog & Cat, Barnyard)
   - Home Equipment (Level 2: Bathroom Accessories, Wooden Building, Electricity)
   - Gardening (Level 2: Watering, Garden Containers, Exterior Design, Outdoor Garden, Vegetable Garden, Garden Furniture, Tools, Pumps)
   - Hardware (Level 2: General Hardware, Furniture Hardware)
   - Furniture (Level 2: Furniture Textiles, Cushions, Covers, Curtains)
   - Wall & Coverings (Level 2: Tiles, Floor & Wall Coverings)
   - Tools (Level 2: Hand Tools, Portable Power Tools)
   - Painting & Drugstore (Painting Accessories, Glues, Adhesives, Paints)
   - Plumbing & Sanitary (Plumbing, Taps, Sanitary, Heating)
   - Automotive Products (Car Air Fresheners, Auto Elec, Interior/Exterior Equip, Care Products)
4. EXCLUSIONS:
   - EXCLUDE Heavy Industrial Machinery, Equipment, Sporting Goods, and Kitchenware.
   - EXCLUDE raw fabric-only processors or component-only suppliers. Must be finished retail consumer goods matching the 50 target products list.

Return ONLY a raw JSON object with NO markdown formatting or backticks matching these exact fields:
{{
  "companyName": "Exact Factory Name",
  "iflsLevel1": "Exact Level 1 Category from the list above",
  "iflsLevel2": "Exact Level 2 Sub-category",
  "iflsLevel3": "Specific product sub-type",
  "mainProducts": "Finished consumer products description matching the target list",
  "location": "Province/Country (China, Taiwan, or Hong Kong)",
  "companyLocationAddress": "Full City/Address if available or Province",
  "phoneNumber": "Landline Phone Number or N/A",
  "mobileNumber": "Mobile / WhatsApp Number or N/A",
  "emailQQ": "Email address or QQ number or N/A",
  "cert": "Factory Certifications e.g. ISO9001, BSCI, CE or N/A",
  "businessType": "Manufacturer"
}}
"""

    try:
        raw_output = query_groq_with_fallback(prompt)
        json_match = re.search(r'\{[\s\S]*\}', raw_output)
        data = json.loads(json_match.group(0)) if json_match else {}
    except Exception as e:
        print(f"AI parsing warning: {e}")
        continue

    extracted_company = data.get("companyName", "").strip()

    # Skip invalid or template results
    if not extracted_company or extracted_company in ["Exact Factory Name", "Unknown Supplier", "N/A"]:
        continue

    # Deduplication check against existing Airtable records
    if extracted_company.lower() in existing_companies:
        print(f"Skipping existing company: '{extracted_company}'")
        continue

    ifls_path = f"{data.get('iflsLevel1', 'N/A')} > {data.get('iflsLevel2', 'N/A')} > {data.get('iflsLevel3', 'N/A')}"

    # Push to Airtable matching your Garden factory leads table schema
    airtable_endpoint = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{requests.utils.quote(AIRTABLE_TABLE_NAME)}"
    headers = {
        "Authorization": f"Bearer {AIRTABLE_API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "fields": {
            "Company Name": extracted_company,
            "Main Products": f"[{ifls_path}] ({source_engine}) {data.get('mainProducts', 'Retail Consumer Goods')}",
            "Location": data.get("location", "China / Taiwan"),
            "Business Type": data.get("businessType", "Manufacturer"),
            "Source URL": link,
            "Phone Number": data.get("phoneNumber", "N/A"),
            "Mobile Number": data.get("mobileNumber", "N/A"),
            "Email / QQ": data.get("emailQQ", "N/A"),
            "Company Location Address": data.get("companyLocationAddress", "N/A"),
            "Cert": data.get("cert", "N/A")
        }
    }

    res = requests.post(airtable_endpoint, json=payload, headers=headers)
    print(f"Pushed NEW lead '{extracted_company}' via {source_engine}: Status {res.status_code}")
    
    existing_companies.add(extracted_company.lower())
