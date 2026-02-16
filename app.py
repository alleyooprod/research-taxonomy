import os
import json
import subprocess
import time
from datetime import datetime
from flask import Flask, render_template, request, jsonify
import requests
from bs4 import BeautifulSoup
import pandas as pd
from pathlib import Path
import re
import webbrowser
from threading import Timer

app = Flask(__name__)

# Configuration
BATCH_SIZE = 5
TAXONOMY_MD = "taxonomy_master.md"
TAXONOMY_JSON = "taxonomy_data.json"

# Shortened URL patterns
SHORTENER_PATTERNS = [
    r'bit\.ly', r'tinyurl\.com', r'linktr\.ee', r'linkin\.bio',
    r'beacons\.ai', r'msha\.ke', r'heylink\.me', r't\.co'
]

# Taxonomy categories (will evolve)
TAXONOMY_CATEGORIES = [
    "Diagnostics & Testing",
    "Mental Health",
    "Fitness & Recovery",
    "Nutrition & Gut Health",
    "Preventive Health & Longevity",
    "Digital Therapeutics",
    "Telehealth & Virtual Care",
    "Wearables & Monitoring",
    "Employee Benefits & EAP",
    "Health Insurance",
    "Clinical Infrastructure",
    "Wellness & Lifestyle"
]

# Extraction prompt template for Claude Code
EXTRACTION_PROMPT = """Research and extract detailed information about this company: {url}

Extract the following fields with specified word counts:

**name**: Company name (exact)

**url**: Primary company website URL

**what**: 50-100 words - Detailed value proposition. What do they do, how do they do it, what makes them different? Use specific details from their website, not generic descriptions.

**target**: 30-50 words - Specific customer segments. Who are their customers? Include context about market segment, demographics, use cases.

**products**: 50-80 words - Key offerings with features and differentiators. What are their main products/services? Include specific features, delivery methods, unique capabilities.

**funding**: 20-40 words - Funding stage, investors, amounts raised if available. Include founding year if relevant.

**geography**: 15-30 words - Markets served, HQ location, expansion plans or international presence.

**tam**: 40-60 words - Total addressable market estimate, market size, growth rates, addressable segments. Use industry data if available.

**tags**: Array of relevant tags from: ["competitor", "potential_partner", "adjacent_model", "infrastructure", "inspiration", "out_of_scope"]

**category**: Primary category from: {categories}

**subcategory**: Specific subcategory (create if needed)

OUTPUT FORMAT (JSON only, no markdown):
{{
  "name": "...",
  "url": "...",
  "what": "...",
  "target": "...",
  "products": "...",
  "funding": "...",
  "geography": "...",
  "tam": "...",
  "tags": ["..."],
  "category": "...",
  "subcategory": "..."
}}

CRITICAL: Do NOT use the full word count unless needed, but ensure substantive detail. Three-word answers are unacceptable. Extract real information from the company website.
"""


def resolve_shortened_url(url):
    """Resolve shortened URLs and link aggregators to actual destination."""
    try:
        # Check if it's a known shortener
        is_shortener = any(re.search(pattern, url) for pattern in SHORTENER_PATTERNS)
        
        if not is_shortener:
            return url, True  # Not a shortener, return as-is
        
        # For link aggregators (linktr.ee, linkin.bio, etc.), scrape the page
        if any(pattern in url for pattern in ['linktr.ee', 'linkin.bio', 'beacons.ai', 'msha.ke']):
            response = requests.get(url, timeout=10, headers={'User-Agent': 'Mozilla/5.0'})
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Find first meaningful link (usually company homepage)
            links = soup.find_all('a', href=True)
            for link in links:
                href = link['href']
                # Skip social media, focus on company domains
                if not any(social in href for social in ['instagram.com', 'twitter.com', 'facebook.com', 'linkedin.com', 'tiktok.com']):
                    if href.startswith('http'):
                        return href, True
            
            # Fallback: try to extract brand name and Google it
            title = soup.find('title')
            if title:
                brand = title.text.split('|')[0].strip()
                search_url = f"https://www.google.com/search?q={brand}+official+website"
                # Return the aggregator URL with a flag that it needs manual review
                return url, False
        
        # For simple redirects (bit.ly, tinyurl), follow the chain
        else:
            response = requests.head(url, allow_redirects=True, timeout=10)
            return response.url, True
    
    except Exception as e:
        print(f"Error resolving {url}: {str(e)}")
        return url, False


def validate_link(url):
    """Quick validation: check if link is accessible and health-related."""
    try:
        # Resolve shortened URLs first
        resolved_url, success = resolve_shortened_url(url)
        
        if not success:
            return {
                'url': url,
                'resolved_url': resolved_url,
                'status': 'needs_review',
                'reason': 'Could not fully resolve link aggregator'
            }
        
        # Check if accessible
        response = requests.head(resolved_url, timeout=10, allow_redirects=True, headers={'User-Agent': 'Mozilla/5.0'})
        
        if response.status_code >= 400:
            return {
                'url': url,
                'resolved_url': resolved_url,
                'status': 'error',
                'reason': f'HTTP {response.status_code}'
            }
        
        # Quick health keyword check
        try:
            page_response = requests.get(resolved_url, timeout=10, headers={'User-Agent': 'Mozilla/5.0'})
            soup = BeautifulSoup(page_response.text, 'html.parser')
            
            text = soup.get_text().lower()
            title = soup.find('title').text.lower() if soup.find('title') else ''
            meta_desc = soup.find('meta', {'name': 'description'})
            meta_text = meta_desc['content'].lower() if meta_desc and 'content' in meta_desc.attrs else ''
            
            health_keywords = ['health', 'medical', 'wellness', 'fitness', 'nutrition', 'mental', 
                             'therapy', 'diagnostic', 'insurance', 'clinic', 'hospital', 'care',
                             'physio', 'pharmacy', 'doctor', 'patient', 'longevity', 'biomarker']
            
            combined_text = f"{title} {meta_text}"
            if any(keyword in combined_text for keyword in health_keywords):
                return {
                    'url': url,
                    'resolved_url': resolved_url,
                    'status': 'valid',
                    'reason': 'Health-related content detected'
                }
            else:
                return {
                    'url': url,
                    'resolved_url': resolved_url,
                    'status': 'suspect',
                    'reason': 'No health keywords found in title/meta'
                }
        
        except:
            # If can't parse, assume valid (will be caught in full extraction)
            return {
                'url': url,
                'resolved_url': resolved_url,
                'status': 'valid',
                'reason': 'Accessible but could not parse content'
            }
    
    except Exception as e:
        return {
            'url': url,
            'resolved_url': url,
            'status': 'error',
            'reason': str(e)
        }


def parse_input_file(file):
    """Parse various file formats to extract URLs."""
    urls = []
    file_ext = Path(file.filename).suffix.lower()
    
    try:
        if file_ext in ['.txt', '.md']:
            content = file.read().decode('utf-8')
            # Extract URLs using regex
            url_pattern = r'https?://[^\s<>"{}|\\^`\[\]]+'
            urls = re.findall(url_pattern, content)
        
        elif file_ext == '.csv':
            df = pd.read_csv(file)
            # Assume URLs are in first column or a column named 'url'/'link'
            if 'url' in df.columns:
                urls = df['url'].dropna().tolist()
            elif 'link' in df.columns:
                urls = df['link'].dropna().tolist()
            else:
                urls = df.iloc[:, 0].dropna().tolist()
        
        elif file_ext in ['.xlsx', '.xls']:
            df = pd.read_excel(file)
            if 'url' in df.columns:
                urls = df['url'].dropna().tolist()
            elif 'link' in df.columns:
                urls = df['link'].dropna().tolist()
            else:
                urls = df.iloc[:, 0].dropna().tolist()
    
    except Exception as e:
        print(f"Error parsing file: {str(e)}")
        return []
    
    # Clean URLs
    urls = [url.strip() for url in urls if url and isinstance(url, str) and url.startswith('http')]
    return list(set(urls))  # Deduplicate


def load_taxonomy_data():
    """Load existing taxonomy JSON."""
    if os.path.exists(TAXONOMY_JSON):
        with open(TAXONOMY_JSON, 'r') as f:
            return json.load(f)
    return {"companies": [], "metadata": {"last_updated": None, "total_companies": 0}}


def save_taxonomy_data(data):
    """Save taxonomy JSON."""
    data['metadata']['last_updated'] = datetime.now().isoformat()
    data['metadata']['total_companies'] = len(data['companies'])
    
    with open(TAXONOMY_JSON, 'w') as f:
        json.dump(data, f, indent=2)
    
    # Also update markdown
    generate_markdown(data)


def generate_markdown(data):
    """Generate human-readable markdown from JSON data."""
    md_content = ["# Healthtech Taxonomy\n"]
    md_content.append(f"*Last updated: {data['metadata']['last_updated']}*\n")
    md_content.append(f"*Total companies: {data['metadata']['total_companies']}*\n\n")
    
    # Group by category
    by_category = {}
    for company in data['companies']:
        cat = company.get('category', 'Uncategorized')
        if cat not in by_category:
            by_category[cat] = []
        by_category[cat].append(company)
    
    # Write by category
    for category in sorted(by_category.keys()):
        md_content.append(f"## {category}\n\n")
        
        for company in sorted(by_category[category], key=lambda x: x['name']):
            md_content.append(f"### {company['name']}\n\n")
            md_content.append(f"**URL**: {company['url']}\n\n")
            md_content.append(f"**What**: {company['what']}\n\n")
            md_content.append(f"**Target**: {company['target']}\n\n")
            md_content.append(f"**Products**: {company['products']}\n\n")
            md_content.append(f"**Funding**: {company['funding']}\n\n")
            md_content.append(f"**Geography**: {company['geography']}\n\n")
            md_content.append(f"**TAM**: {company['tam']}\n\n")
            md_content.append(f"**Tags**: {', '.join(company.get('tags', []))}\n\n")
            md_content.append(f"**Subcategory**: {company.get('subcategory', 'N/A')}\n\n")
            md_content.append("---\n\n")
    
    with open(TAXONOMY_MD, 'w') as f:
        f.writelines(md_content)


@app.route('/')
def index():
    """Main page."""
    return render_template('index.html')


@app.route('/api/validate', methods=['POST'])
def validate_links():
    """Pre-flight validation of links."""
    data = request.json
    urls = data.get('urls', [])
    
    results = []
    for url in urls:
        result = validate_link(url)
        results.append(result)
        time.sleep(0.5)  # Rate limiting
    
    return jsonify(results)


@app.route('/api/process_batch', methods=['POST'])
def process_batch():
    """Process a batch of links using Claude Code."""
    data = request.json
    urls = data.get('urls', [])
    batch_number = data.get('batch_number', 1)
    
    # Create prompt for Claude Code
    prompt = f"""Process this batch of {len(urls)} healthtech companies.

For each URL, extract detailed information following this schema:

{EXTRACTION_PROMPT.format(url='<URL>', categories=', '.join(TAXONOMY_CATEGORIES))}

URLs to process:
{chr(10).join(f"{i+1}. {url}" for i, url in enumerate(urls))}

After extraction, append results to taxonomy_data.json maintaining the existing structure.

Return a summary of companies processed.
"""
    
    # Write prompt to temp file
    prompt_file = f"batch_{batch_number}_prompt.txt"
    with open(prompt_file, 'w') as f:
        f.write(prompt)
    
    # Trigger Claude Code
    # Note: This requires user approval in VSCode terminal
    try:
        result = subprocess.run(
            ['claude-code', f'Execute the instructions in {prompt_file}'],
            capture_output=True,
            text=True,
            timeout=300  # 5 min timeout per batch
        )
        
        # Clean up
        os.remove(prompt_file)
        
        return jsonify({
            'status': 'success',
            'batch': batch_number,
            'message': 'Batch processed successfully'
        })
    
    except subprocess.TimeoutExpired:
        return jsonify({
            'status': 'error',
            'message': 'Batch processing timed out'
        }), 500
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500


@app.route('/api/data', methods=['GET'])
def get_data():
    """Get current taxonomy data."""
    data = load_taxonomy_data()
    return jsonify(data)


@app.route('/api/update', methods=['POST'])
def update_company():
    """Update a single company's data."""
    company_data = request.json
    
    data = load_taxonomy_data()
    
    # Find and update company
    company_id = company_data.get('id')
    for i, company in enumerate(data['companies']):
        if company.get('id') == company_id:
            data['companies'][i] = company_data
            break
    else:
        # New company
        data['companies'].append(company_data)
    
    save_taxonomy_data(data)
    return jsonify({'status': 'success'})


@app.route('/api/upload', methods=['POST'])
def upload_file():
    """Handle file upload and parse URLs."""
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    
    file = request.files['file']
    urls = parse_input_file(file)
    
    return jsonify({'urls': urls, 'count': len(urls)})


@app.route('/api/parse_text', methods=['POST'])
def parse_text():
    """Parse URLs from pasted text."""
    text = request.json.get('text', '')
    url_pattern = r'https?://[^\s<>"{}|\\^`\[\]]+'
    urls = list(set(re.findall(url_pattern, text)))
    
    return jsonify({'urls': urls, 'count': len(urls)})


def open_browser():
    """Open browser after short delay."""
    webbrowser.open('http://localhost:5000')


if __name__ == '__main__':
    # Initialize files if they don't exist
    if not os.path.exists(TAXONOMY_JSON):
        save_taxonomy_data({"companies": [], "metadata": {}})
    
    # Open browser automatically
    Timer(1, open_browser).start()
    
    app.run(debug=True, port=5000)