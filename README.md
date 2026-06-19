# Local Lead Generation & SEO Audit Agent

An autonomous Python-based agent that discovers local businesses via the Geoapify Places API, crawls their websites to extract contact info, performs a technical/SEO audit (including Google PageSpeed performance), scores leads based on priority opportunity, and drafts personalized outreach emails using free LLM APIs (Gemini 2.0 Flash Lite with a Groq Llama-3.1-8b-instant fallback).

---

## Features

1. **Business Discovery**: Finds local businesses by geocoding a location and searching within a 10km radius using the **Geoapify Places API**.
2. **Website Enrichment**: Scrapes each business's homepage, `/contact`, and `/about` pages to extract email addresses (respecting `robots.txt` and using modern User-Agents).
3. **SEO & Technical Audit**:
   - Checks SSL validity
   - Inspects meta title and meta description tags
   - Scrapes for Google Analytics script tags
   - Checks presence of `/robots.txt` and `/sitemap.xml`
   - Queries **Google PageSpeed Insights API** for a mobile performance score.
4. **Weighted Prioritization Scoring**: Scores each lead out of 100 points. A lower score indicates more technical/SEO deficiencies (making them higher-priority outreach targets).
5. **AI Cold Outreach**: Generates a short (under 100 words), direct outreach email focused on the top 2 severe issues using `gemini-2.0-flash-lite` (or `llama-3.1-8b-instant` if Gemini hits a rate limit).
6. **Smart Caching & Database**: Stores all results in a local SQLite database (`leads.db`). Subsequent runs skip leads already marked as `status='processed'` to save APIs and crawl bandwidth, unless the `--force` flag is specified.

---

## Setup Instructions

### 1. Installation

Clone or download the project files into your desired workspace, and install the required Python packages:

```bash
pip install -r requirements.txt
```

### 2. Configure Environment Variables

Create a `.env` file in the root of the project. You can copy the template from `.env.example`:

```bash
cp .env.example .env
```

Edit the `.env` file to add your API keys:

```env
GEOAPIFY_API_KEY=your_geoapify_key_here
PAGESPEED_API_KEY=your_pagespeed_key_optional
GEMINI_API_KEY=your_gemini_key_here
GROQ_API_KEY=your_groq_key_here
```

### 3. Acquiring Your API Keys

- **Geoapify API Key**:
  1. Go to [myprojects.geoapify.com](https://myprojects.geoapify.com/).
  2. Create a free account (no credit card or billing configuration required).
  3. Create a new project and generate an API key. The free tier gives you 3,000 credits/day.
- **Google PageSpeed Insights API Key (Optional)**:
  - You can obtain a free key via the Google Cloud Console by enabling the PageSpeed Insights API. However, it is **completely optional**; if omitted, the agent will query the API without a key (which works fine for low-volume requests).
- **Gemini API Key**:
  - Get a free-tier API key from the Google AI Studio at [aistudio.google.com](https://aistudio.google.com/).
- **Groq API Key**:
  - Sign up and retrieve an API key from the Groq console at [console.groq.com](https://console.groq.com/).

---

## How to Run

Execute the pipeline orchestrator by specifying a niche and a location:

```bash
python lead_gen_agent/pipeline.py --niche "catering.restaurant" --location "Dallas, TX" --limit 3
```

### Arguments

- `--niche`: The business niche. Can be a Geoapify category (e.g. `catering.restaurant`, `healthcare.clinic.dentist`, `commercial.office`) or a plain-text term (e.g. `dentists`, `hotels`, `plumbers`), which will be mapped automatically.
- `--location`: The target city and state/country (e.g. `Dallas, TX`, `Seattle`, `London`).
- `--limit`: Maximum number of businesses to discover and audit (default: `10`).
- `--force`: Ignore database caching and force a complete re-run of enrichment, SEO audit, and email generation for all matching leads.

---

## Project Structure

```text
lead_gen_agent/
│
├── config.py         # Configures logging (outputs to console and lead_gen.log) and loads env keys
├── discovery.py      # Geocodes locations and queries Geoapify Places & Place Details APIs
├── enrichment.py     # Web crawler parsing homepage + contact + about for email extraction
├── analysis.py       # SEO meta-tag, Google Analytics, SSL, sitemap/robots, and PageSpeed auditor
├── scoring.py        # Implements weighted penalty rubrics for lead scoring
├── outreach.py       # Interacts with Gemini and Groq fallback to draft cold outreach drafts
├── storage.py        # Manages SQLite database creation, caching checks, and lead states
└── pipeline.py       # Orchestrates the execution sequence, exception handling, and logging
```
