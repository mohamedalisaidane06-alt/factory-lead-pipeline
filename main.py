import os
import re
import json
import feedparser
import requests
from groq import Groq

# 1. Environment Secrets
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
AIRTABLE_API_KEY = os.environ.get("AIRTABLE_API_KEY")
AIRTABLE_BASE_ID = os.environ.get("AIRTABLE_BASE_ID")

AIRTABLE_TABLE_NAME = "Factory Leads"

# 2. Targeted RSS Query (Brico, Jardin, Animalerie, Auto, Hardware in China & Taiwan)
RSS_URL = (
    "https://news.google.com/rss/search?q="
    "%22factory%22+OR+%22manufacturer%22+"
    "%22China%22+OR+%22Taiwan%22+"
    "%22gardening%22+OR+%22hardware%22+OR+%22pet+accessories%22+OR+%22tools%22+OR+%22sanitary%22+OR+%22auto+accessories%22"
    "+when:7d"
    "&hl=en-US&gl=US&ceid=US:en"
)

feed = feedparser.parse(RSS_URL)
if not feed.entries:
    print("No entries found matching current IFLS sourcing keywords.")
    exit(0)

# Extract top lead item
item = feed.entries[0]
title = item.get("title", "Unknown Supplier")
link = item.get("link", "")
summary = item.get("summary", "")

client = Groq(api_key=GROQ_API_KEY)

# 3. Prompt structured around your IFLS Taxonomy (Level 1 to Level 5)
prompt = f"""
You are an expert global sourcing specialist for European off-price/discount retail chains (e.g., NOZ, Action).
Your task is to analyze the following factory lead and extract structured metadata while mapping it into the official IFLS Product Taxonomy.

Title: {title}
Summary: {summary}

### Sourcing & Taxonomy Rules:
1. GEOGRAPHY: Direct manufacturers/factories located in mainland China or Taiwan ONLY.
2. SCOPE (BRICO / JARDIN-ANIMALERIE):
   - Level 1 Categories Allowed:
     * PERSONAL WELL-BEING (Level 2: DOMESTIC ANIMALS - Dog/Cat/Bird/Barnyard/Aquarium accessories)
     * HOME EQUIPMENT (Level 2: BATHROOM ACCESSORIES, WOODEN BUILDING, ELECTRICITY)
     * GARDENING (Level 2: WATERING, GARDEN CONTAINERS, EXTERIOR DESIGN, OUTDOOR GARDEN, VEGETABLE GARDEN, GARDEN FURNITURE, TOOLS, PUMPS)
     * HARDWARE (Level 2: GENERAL HARDWARE, FURNITURE HARDWARE)
     * FURNITURE (Level 2: FURNITURE TEXTILES - Chair cushions, covers, curtains)
     * WALL AND COVERINGS (Level 2: TILES, FLOOR COVERINGS, WALL COVERINGS)
     * TOOLS (Level 2: HAND TOOLS, PORTABLE ELECTRIC TOOLS)
     * PAINTING & DRUGSTORE (Level 2: PAINTING ACCESSORIES, ADHESIVES, GLUES, PAINTS/VARNISHES)
     * PLUMBING - SANITARY (Level 2: PLUMBING, TAPS, SANITARY, HEATING)
     * AUTOMOTIVE PRODUCTS (Level 3: AUTO SOUND, AIR FRESHENERS, AUTO ELEC, EXTERIOR/INTERIOR EQUIP, LUBRICANTS, AUTO TOOLS, CARE PRODUCTS)
3. STRICT EXCLUSIONS:
   - EXCLUDE B2B Heavy Machinery, Industrial Production Lines, and Raw Material/Fabric Processors.
   - EXCLUDE Sporting Goods and Kitchenware entirely.

Return ONLY a raw JSON object with NO markdown formatting or backticks:
{{
  "companyName": "Exact Factory Name",
  "iflsLevel1": "Personal Well-Being OR Home Equipment OR Gardening OR Hardware OR Furniture OR Wall & Coverings OR Tools OR Painting & Drugstore OR Plumbing-Sanitary OR Automotive Products",
  "iflsLevel2": "Exact Level 2 Category",
  "iflsLevel3": "Exact Level 3 Category",
  "mainProducts": "Finished consumer goods list",
  "locationAddress": "City / Province, China or Taiwan",
  "phoneNumber": "Landline Phone or N/A",
  "mobileNumber": "Mobile Contact or N/A",
  "emailQQ": "Email / QQ contact or N/A",
  "businessType": "Manufacturer",
  "certifications": "ISO / BSCI / CE or N/A"
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
    print(f"AI classification warning: {e}")
    data = {}

# 4. Push payload to Airtable
airtable_endpoint = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_TABLE_NAME}"
headers = {
    "Authorization": f"Bearer {AIRTABLE_API_KEY}",
    "Content-Type": "application/json"
}

# Construct taxonomy string for clear CRM organization
ifls_path = f"{data.get('iflsLevel1', 'N/A')} > {data.get('iflsLevel2', 'N/A')} > {data.get('iflsLevel3', 'N/A')}"

payload = {
    "fields": {
        "Company Name": data.get("companyName", title),
        "Main Products": f"[{ifls_path}] {data.get('mainProducts', 'Retail Consumer Goods')}",
        "Location": data.get("locationAddress", "China / Taiwan"),
        "Business Type": data.get("businessType", "Manufacturer"),
        "Source URL": link,
        "Phone Number": data.get("phoneNumber", "N/A")
    }
}

res = requests.post(airtable_endpoint, json=payload, headers=headers)
print(f"Airtable Push Status Code: {res.status_code}")
print(f"Airtable Response: {res.text}")

if res.status_code not in [200, 201]:
    raise Exception(f"Failed to push to Airtable: {res.text}")
