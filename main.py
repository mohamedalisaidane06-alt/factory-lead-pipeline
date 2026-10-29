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

all_raw_leads = []

# --- SOURCE 1: Google News RSS (English Global Trade Announcements) ---
try:
    google_url = (
        "https://news.google.com/rss/search?q="
        "%22factory%22+OR+%22manufacturer%22+"
        "%22China%22+OR+%22Taiwan%22+"
        "%22gardening%22+OR+%22hardware%22+OR+%22tools%22+OR+%22sanitary%22"
        "+when:7d&hl=en-US&gl=US&ceid=US:en"
    )
    feed = feedparser.parse(google_url)
    for entry in feed.entries[:2]:
        all_raw_leads.append({
            "source": "Google News",
            "title": entry.get("title", ""),
            "summary": entry.get("summary", ""),
            "url": entry.get("link", "")
        })
except Exception as e:
    print(f"Google News fetch error: {e}")

# --- SOURCE 2: DuckDuckGo (Global B2B & Supplier Index) ---
try:
    ddg_query = '"manufacturer" OR "factory" "China" OR "Taiwan" "hardware" OR "gardening" OR "tools"'
    ddg_results = DDGS().text(ddg_query, max_results=2)
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

# --- SOURCE 3: Baidu (Native Chinese Industrial Search Engine) ---
try:
    baidu_url = "https://www.baidu.com/s?wd=%22%E7%94%9F%E4%BA%A7%E5%8E%82%E5%AE%B6%22+%22%E4%B8%AD%E5%9B%BD%22+%22%E4%BA%94%E9%87%91%22+OR+%22%E5%9B%AD%E8%8B%B1%22"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"}
    res = requests.get(baidu_url, headers=headers, timeout=10)
    if res.status_code == 200:
        soup = BeautifulSoup(res.text, "html.parser")
        containers = soup.find_all("div", class_=re.compile("c-container"))
        for item in containers[:2]:
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
    print("No supplier leads retrieved across Google, DDG, and Baidu.")
    exit(0)

client = Groq(api_key=GROQ_API_KEY)

# Process extracted leads through Groq AI (Llama 3.1 8B)
for lead in all_raw_leads[:3]:
    title = lead["title"]
    summary = lead["summary"]
    source_engine = lead["source"]
    link = lead["url"]

    prompt = f"""
    You are an expert global sourcing specialist for European discount retail chains (e.g., NOZ, Action).
    Analyze this supplier lead retrieved from search engine: {source_engine}

    Title: {title}
    Summary: {summary}

    ### Sourcing & IFLS Taxonomy Rules:
    1. GEOGRAPHY: Direct manufacturers/factories in China or Taiwan ONLY.
    2. SCOPE (BRICO / JARDIN-ANIMALERIE):
       - Personal Well-Being (Pet Accessories / Barnyard / Dog & Cat)
       - Home Equipment (Bathroom Accessories, Wooden Building, Electricity)
       - Gardening (Watering, Garden Containers, Exterior Design, Outdoor Garden, Vegetable Garden, Garden Furniture, Tools, Pumps)
       - Hardware (General Hardware, Furniture Hardware)
       - Furniture (Furniture Textiles - Cushions, Covers, Curtains)
       - Wall & Coverings (Tiles, Floor/Wall Coverings)
       - Tools (Hand Tools, Portable Power Tools)
       - Painting & Drugstore (Painting Accessories, Glues, Adhesives, Paints)
       - Plumbing & Sanitary (Plumbing, Taps, Sanitary, Heating)
       - Automotive Products (Car Air Fresheners, Auto Elec, Interior/Exterior Equip, Care Products, Tools)
    3. EXCLUSIONS:
       - EXCLUDE Heavy Industrial Machinery, Equipment, Sporting Goods, and Kitchenware.
       - EXCLUDE Raw fabric-only processors and component-only suppliers. Must be finished retail consumer goods.

    Return ONLY a raw JSON object with NO markdown formatting or backticks:
    {{
      "companyName": "Exact Factory Name",
      "iflsLevel1": "Exact Level 1 Category",
      "iflsLevel2": "Exact Level 2 Category",
      "iflsLevel3": "Exact Level 3 Category",
      "mainProducts": "Finished consumer products description",
      "locationAddress": "City / Province, China or Taiwan",
      "phoneNumber": "Phone Number or N/A",
      "businessType": "Manufacturer"
    }}
    """

    try:
        response = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1
        )
        raw_output = response.choices[0].message.content
        json_match = re.search(r'\{[\s\S]*\}', raw_output)
        data = json.loads(json_match.group(0)) if json_match else {}
    except Exception as e:
        print(f"AI parsing warning: {e}")
        continue

    # Skip invalid or template results
    if not data or data.get("companyName") in ["Exact Factory Name", "Unknown Supplier", "N/A"]:
        continue

    ifls_path = f"{data.get('iflsLevel1', 'N/A')} > {data.get('iflsLevel2', 'N/A')} > {data.get('iflsLevel3', 'N/A')}"

    # Push to Airtable
    airtable_endpoint = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_TABLE_NAME}"
    headers = {
        "Authorization": f"Bearer {AIRTABLE_API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "fields": {
            "Company Name": data.get("companyName", title),
            "Main Products": f"[{ifls_path}] ({source_engine}) {data.get('mainProducts', 'Retail Consumer Goods')}",
            "Location": data.get("locationAddress", "China / Taiwan"),
            "Business Type": data.get("businessType", "Manufacturer"),
            "Source URL": link,
            "Phone Number": data.get("phoneNumber", "N/A")
        }
    }

    res = requests.post(airtable_endpoint, json=payload, headers=headers)
    print(f"Pushed '{data.get('companyName')}' via {source_engine}: Status {res.status_code}")
