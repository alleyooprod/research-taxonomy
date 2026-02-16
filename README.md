# Healthtech Taxonomy Builder

Automated web app for building and maintaining a living database of healthtech companies. Extracts company data via Claude Code, outputs structured markdown + JSON for visualization in FigJam/Claude.

## Features

- 🔗 **Smart link resolution**: Auto-resolves shortened URLs (bit.ly, linktr.ee, etc.)
- ✅ **Pre-flight validation**: Flags inaccessible/non-health links before processing
- 🤖 **Intelligent extraction**: Uses Claude Code for deep company analysis
- 📊 **Dual output**: Human-readable markdown + machine-queryable JSON
- ✏️ **Inline editing**: Correct data directly in webapp
- 📦 **Auto-batching**: Processes 5 links at a time to reduce errors
- 📈 **Progress tracking**: Visual progress through batch queue

## Requirements

- Python 3.9+
- VSCode with Claude Code installed and authenticated
- Flask (`pip install flask requests beautifulsoup4`)

## Installation
```bash
git clone <repo-url>
cd healthtech-taxonomy
pip install -r requirements.txt
python app.py  # Auto-opens browser at localhost:5000
```

## Usage Workflow

1. **Upload links**: Paste URLs or upload .csv/.xlsx/.txt/.md file
2. **Pre-flight check** (30-60 sec): App validates links, resolves shorteners
3. **Review flags**: Fix/skip/override any problematic links
4. **Start processing**: Batches of 5 → approve each in VSCode terminal
5. **View results**: Sortable table in webapp
6. **Edit inline**: Click any cell to correct data
7. **Export**: `taxonomy_master.md` + `taxonomy_data.json` auto-update

## File Structure
```
healthtech-taxonomy/
├── app.py                      # Flask webapp
├── taxonomy_master.md          # Human-readable output
├── taxonomy_data.json          # Machine-readable output
├── requirements.txt
├── templates/
│   └── index.html             # Webapp UI
├── static/
│   └── style.css              # Minimal styling
└── README.md
```

## Output Schema

### taxonomy_master.md
Hierarchical markdown organized by category with company details.

### taxonomy_data.json
```json
{
  "companies": [
    {
      "id": "company-slug",
      "name": "Company Name",
      "url": "https://...",
      "what": "Brief description",
      "target": "B2C/B2B/B2B2C",
      "products": ["Product 1", "Product 2"],
      "funding": "Seed/Series A/Growth",
      "geography": "UK/US/EU",
      "tam": "Market size estimate",
      "tags": ["competitor", "partner"],
      "category": "Diagnostics",
      "subcategory": "Blood Testing",
      "processed_date": "2026-02-16"
    }
  ],
  "metadata": {
    "last_updated": "2026-02-16T14:30:00Z",
    "total_companies": 127
  }
}
```

## Taxonomy Categories

See `taxonomy_master.md` for current category structure. Categories evolve as new companies are added.

## Using with FigJam/Claude

The JSON output enables flexible queries:
- "Show all B2C competitors in diagnostics"
- "Create 2x2 grid: B2B vs B2C, preventive vs reactive"
- "Generate FigJam cards for mental health companies"

Load `taxonomy_data.json` into Claude/Cowork and request visualizations.

## Development

- Edit extraction fields in `app.py` → `EXTRACTION_PROMPT` variable
- Modify categories in `TAXONOMY_CATEGORIES` list
- Adjust batch size in `BATCH_SIZE` constant (default: 5)

## License

MIT