import os
import re
import json
import requests
import feedparser
from bs4 import BeautifulSoup
from groq import Groq
from duckduckgo_search import DDGS

# 1. Environment Secrets
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
AIRTABLE_API_KEY = os.environ.get("AIRTABLE_API_KEY")
AIRTABLE_BASE_ID = os.environ.get("AIRTABLE_BASE_ID")

AIRTABLE_TABLE_NAME = "Factory Leads"

# 2. Fetch Existing Airtable Company Names (for Deduplication)
existing_companies = set()
try:
    airtable_get_url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_TABLE_NAME}?fields[]=Company+Name"
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

# --- SOURCE 1: Google News RSS (Expanded to 60 Days / 2 Months) ---
try:
    google_url = (
        "https://news.google.com/rss/search?q="
        "%22factory%22+OR+%22manufacturer%22+"
        "%22China%22+OR+%22Taiwan%22+"
        "%22shade+mesh%22+OR+%22privacy+screen%22+OR+%22shower+curtain%22+OR+%22garden+tools%22+OR+%22pet+accessories%22"
        "+when:60d&hl=en-US&gl=US&ceid=US:en"
    )
    feed = feedparser.parse(google_url)
    for entry in feed.entries[:3]:
        all_raw_leads.append({
            "source": "Google News",
            "title": entry.get("title", ""),
            "summary": entry.get("summary", ""),
            "url": entry.get("link", "")
        })
except Exception as e:
    print(f"Google News fetch error: {e}")

# --- SOURCE 2: DuckDuckGo ---
try:
    ddg_query = '"manufacturer" OR "factory" "China" OR "Taiwan" "privacy screen" OR "garden tools" OR "hardware" OR "pet accessories"'
    ddg_results = DDGS().text(ddg_query, max_results=3)
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

# --- SOURCE 3: Baidu ---
try:
    baidu_url = "https://www.baidu.com/s?wd=%22%E7%94%9F%E4%BA%A7%E5%8E%82%E5%AE%B6%22+%22%E4%B8%AD%E5%9B%BD%22+%22%E9%81%AE%E9%98%B3%E7%BD%91%22+OR+%22%E6%B5%B4%E5%B1%90%22+OR+%22%E4%BA%94%E9%87%91%22+-%E9%98%BF%E9%87%8C"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"}
    res = requests.get(baidu_url, headers=headers, timeout=10)
    if res.status_code == 200:
        soup = BeautifulSoup(res.text, "html.parser")
        containers = soup.find_all("div", class_=re.compile("c-container"))
        for item in containers[:3]:
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
for lead in all_raw_leads[:4]:
    title = lead["title"]
    summary = lead["summary"]
    source_engine = lead["source"]
    link = lead["url"]

    prompt = f"""
  You are an expert global sourcing specialist for European discount retail chains (e.g., NOZ, Action) specializing in Brico/Jardin-Animalerie categories.
    Analyze this supplier lead retrieved from search engine: {source_engine}

    Title: {title}
    Summary: {summary}

    ### Strict IFLS Taxonomy Rules (MANDATORY):
    You MUST classify the product into one of these exact IFLS Level 1 categories and provide appropriate Level 2 and Level 3 sub-categories:
    1. Personal Well-Being (Level 2: Pet Accessories, Dog & Cat, Barnyard)
    2. Home Equipment (Level 2: Bathroom Accessories, Wooden Building, Electricity)
    3. Gardening (Level 2: Watering, Garden Containers, Exterior Design, Outdoor Garden, Vegetable Garden, Garden Furniture, Tools, Pumps)
    4. Hardware (Level 2: General Hardware, Furniture Hardware)
    5. Furniture (Level 2: Furniture Textiles, Cushions, Covers, Curtains)
    6. Wall & Coverings (Level 2: Tiles, Floor & Wall Coverings)
    7. Tools (Level 2: Hand Tools, Portable Power Tools)
    8. Painting & Drugstore (Painting Accessories, Glues, Adhesives, Paints)
    9. Plumbing & Sanitary (Plumbing, Taps, Sanitary, Heating)
    10. Automotive Products (Car Air Fresheners, Auto Elec, Interior/Exterior Equip, Care Products)

    ### Exclusions:
    - EXCLUDE Heavy Industrial Machinery, Equipment, Sporting Goods, and Kitchenware.
    - EXCLUDE Raw fabric-only processors and component-only suppliers. Must be finished retail consumer goods.

    Return ONLY a raw JSON object with NO markdown formatting or backticks matching these exact fields:
    {{
      "companyName": "Exact Factory Name",
      "iflsLevel1": "Exact Level 1 Category from the list above",
      "iflsLevel2": "Exact Level 2 Sub-category",
      "iflsLevel3": "Specific product sub-type",
      "mainProducts": "Finished consumer products description",
      "location": "Province/Country (e.g., Zhejiang, China)",
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

    # Push to Airtable matching all columns
    airtable_endpoint = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_TABLE_NAME}"
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
