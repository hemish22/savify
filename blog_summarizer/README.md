# Blog Summarizer 📝

Paste a blog URL and get a structured AI-powered summary in seconds.

**Tech Stack:** Python · FastAPI · Gemini API · SQLite · Vanilla HTML/CSS/JS

---

## Quick Start

### 1. Install dependencies

```bash
cd blog_summarizer/backend
pip install -r requirements.txt
```

### 2. Set your Gemini API key

Create a `.env` file in the `backend/` directory:

```bash
echo "GEMINI_API_KEY=your_api_key_here" > blog_summarizer/backend/.env
```

> Get a free API key at [Google AI Studio](https://aistudio.google.com/apikey)

### 3. Run the server

```bash
cd blog_summarizer/backend
uvicorn main:app --reload
```

### 4. Open in browser

- **Homepage:** [http://localhost:8000](http://localhost:8000)
- **Dashboard:** [http://localhost:8000/dashboard](http://localhost:8000/dashboard)

---

## How It Works

1. Paste a blog URL on the homepage
2. Backend scrapes the article content (BeautifulSoup)
3. Cleaned text is sent to Gemini API for summarization
4. Structured summary is stored in SQLite
5. Summary is displayed immediately + saved to the dashboard

---

## Project Structure

```
blog_summarizer/
├── backend/
│   ├── main.py              # FastAPI app + routes
│   ├── scraper.py           # Article extraction
│   ├── gemini_service.py    # Gemini API integration
│   ├── database.py          # SQLite operations
│   ├── models.py            # Pydantic models
│   └── requirements.txt     # Python dependencies
├── frontend/
│   ├── index.html           # Homepage
│   ├── dashboard.html       # Summary dashboard
│   ├── styles.css           # Design system
│   └── script.js            # Frontend logic
└── README.md
```

---

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/` | Homepage |
| `GET` | `/dashboard` | Dashboard page |
| `POST` | `/summarize` | Summarize a blog URL |
| `GET` | `/summaries` | Get all saved summaries |

### POST /summarize

```json
{ "url": "https://example.com/blog-post" }
```

**Response:**
```json
{
    "title": "Article Title",
    "domain": "example.com",
    "difficulty": "Intermediate",
    "summary": "A concise summary...",
    "key_points": ["Point 1", "Point 2", "..."],
    "takeaway": "The main actionable insight.",
    "original_url": "https://example.com/blog-post"
}
```

---

## Error Handling

| Scenario | HTTP Code | Detail |
|----------|-----------|--------|
| Invalid URL | 422 | URL validation error |
| Empty article | 422 | Not enough content extracted |
| Network timeout | 504 | Request timed out |
| Connection error | 502 | Could not connect |
| Gemini API failure | 502 | Summarization error |

---

## License

MIT
