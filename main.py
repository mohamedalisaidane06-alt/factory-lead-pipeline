import os
import re
import json
import feedparser
import requests
from groq import Groq

# 1. Environment Secrets (Set in GitHub Secrets)
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
AIRTABLE_API_KEY = os.environ.get("AIRTABLE_API_KEY")
AIRTABLE_BASE_ID = os.environ.get("AIRTABLE_BASE_ID")
AIRTABLE_TABLE_NAME = "Factory Leads"

# 2. RSS Feed URL
RSS_URL = "https://news.google.com/rss/search?q=%22factory%22+%22China%22&hl=en-US&gl=US&ceid=US:en"

# Fetch feed items
feed = feedparser.parse(RSS_URL)
if not feed.entries:
    print("No entries found in RSS feed.")
    exit()

item = feed.entries[0]
title = item.get("title", "")
link = item.get("link", "")
summary = item.get("summary", "")

# 3. Call Groq AI (Llama 3.3 70B Model)
client = Groq(api_key=GROQ_API_KEY)

prompt = f"""
Extract factory/supplier details from the following text:
Title: {title}
Summary: {summary}

Return ONLY a raw JSON object with NO markdown formatting or backticks:
{{
  "companyName": "{title.replace('"', '')}",
  "phoneNumber": "N/A",
  "mobileNumber": "N/A",
  "emailQQ": "N/A",
  "locationAddress": "China/Taiwan",
  "mainProducts": "Factory Products",
  "businessType": "Manufacturer",
  "certifications": "N/A"
}}
"""

response = client.chat.completions.create(
    model="llama-3.3-70b-versatile",
    messages=[{"role": "user", "content": prompt}],
    temperature=0.1
)

raw_output = response.choices[0].message.content
json_match = re.search(r'\{[\s\S]*\}', raw_output)

if json_match:
    data = json.loads(json_match.group(0))
    
    # 4. Push All 9 Mandatory Fields to Airtable
    airtable_endpoint = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_TABLE_NAME}"
    headers = {
        "Authorization": f"Bearer {AIRTABLE_API_KEY}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "fields": {
            "Company Name": data.get("companyName", title),
            "Phone Number": data.get("phoneNumber", "N/A"),
            "Mobile Number": data.get("mobileNumber", "N/A"),
            "Email / QQ": data.get("emailQQ", "N/A"),
            "Company Location Address": data.get("locationAddress", "China/Taiwan"),
            "Main Products": data.get("mainProducts", "Manufacturing"),
            "Business Type": data.get("businessType", "Manufacturer"),
            "Certifications": data.get("certifications", "N/A"),
            "Source URL": link
        }
    }
    
    res = requests.post(airtable_endpoint, json=payload, headers=headers)
    print(f"Airtable Push Status: {res.status_code}")
