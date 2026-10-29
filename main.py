import os
import re
import json
import feedparser
import requests
from groq import Groq

GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
AIRTABLE_API_KEY = os.environ.get("AIRTABLE_API_KEY")
AIRTABLE_BASE_ID = os.environ.get("AIRTABLE_BASE_ID")

AIRTABLE_TABLE_NAME = "Factory Leads"

RSS_URL = "https://news.google.com/rss/search?q=%22factory%22+%22China%22&hl=en-US&gl=US&ceid=US:en"

feed = feedparser.parse(RSS_URL)
if not feed.entries:
    print("No entries found in RSS feed.")
    exit(0)

item = feed.entries[0]
title = item.get("title", "Unknown Supplier")
link = item.get("link", "")
summary = item.get("summary", "")

client = Groq(api_key=GROQ_API_KEY)

prompt = f"""
Extract factory/supplier details from:
Title: {title}
Summary: {summary}

Return ONLY raw JSON with keys: companyName, phoneNumber, mobileNumber, emailQQ, locationAddress, mainProducts, businessType, certifications
"""

try:
    response = client.chat.completions.create(
        model="llama-3.1-70b-versatile",  # Updated to active available model
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1
    )
    raw_output = response.choices[0].message.content
    json_match = re.search(r'\{[\s\S]*\}', raw_output)
    data = json.loads(json_match.group(0)) if json_match else {}
except Exception as e:
    print(f"AI parsing warning: {e}")
    data = {}

airtable_endpoint = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_TABLE_NAME}"
headers = {
    "Authorization": f"Bearer {AIRTABLE_API_KEY}",
    "Content-Type": "application/json"
}

payload = {
    "fields": {
        "Company Name": data.get("companyName", title),
        "Main Products": data.get("mainProducts", "Consumer Products"),
        "Location": data.get("locationAddress", "China/Taiwan"),
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
