from flask import Flask, jsonify, request
import cloudscraper
from bs4 import BeautifulSoup
import re

app = Flask(__name__)

scraper = cloudscraper.create_scraper(
    browser={
        'browser': 'chrome',
        'platform': 'windows',
        'mobile': False
    }
)

BASE_URL = "https://wh40k.lexicanum.com"


def fetch_page(url):
    try:
        r = scraper.get(url, timeout=20, allow_redirects=True)
        r.raise_for_status()
        return r
    except Exception:
        return None


def clean_text(text):
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r'[ \t]{2,}', ' ', text)
    return text.strip()


@app.route("/")
def index():
    return jsonify({
        "status": "ok",
        "name": "Lexicanum API",
        "description": "Warhammer 40K lore search via Lexicanum wiki",
        "endpoints": {
            "/search?q=QUERY": "Search for articles by keyword",
            "/article?title=TITLE": "Get full article content by exact title"
        }
    })


@app.route("/search")
def search():
    query = request.args.get("q", "").strip()
    if not query:
        return jsonify({"error": "Missing ?q= parameter"}), 400

    search_url = f"{BASE_URL}/wiki/Special:Search?search={query}&ns0=1"
    response = fetch_page(search_url)

    if not response:
        return jsonify({"error": "Could not reach Lexicanum"}), 503

    final_url = response.url
    if "Special:Search" not in final_url and "/wiki/" in final_url:
        title = final_url.split("/wiki/")[-1].replace("_", " ")
        return jsonify({
            "query": query,
            "redirected_to": title,
            "results": [{"title": title, "url": final_url}]
        })

    soup = BeautifulSoup(response.content, "lxml")
    results = []

    for item in soup.select(".mw-search-result-heading")[:8]:
        link = item.find("a")
        if link:
            results.append({
                "title": link.get_text(strip=True),
                "url": BASE_URL + link["href"]
            })

    return jsonify({
        "query": query,
        "count": len(results),
        "results": results
    })


@app.route("/article")
def get_article():
    title = request.args.get("title", "").strip()
    if not title:
        return jsonify({"error": "Missing ?title= parameter"}), 400

    url = f"{BASE_URL}/wiki/{title.replace(' ', '_')}"
    response = fetch_page(url)

    if not response:
        return jsonify({"error": "Could not reach Lexicanum"}), 503

    soup = BeautifulSoup(response.content, "lxml")

    if soup.select_one(".disambig"):
        options = []
        for link in soup.select("#mw-content-text ul li a")[:12]:
            options.append({
                "text": link.get_text(strip=True),
                "title": link.get("title", link.get_text(strip=True))
            })
        return jsonify({
            "disambiguation": True,
            "message": f"'{title}' is ambiguous. Use one of the options below.",
            "options": options
        })

    for tag in soup.select(".toc, .navbox, .editsection, .ambox, script, style, .references, sup"):
        tag.decompose()

    content_div = soup.select_one("#mw-content-text")
    if not content_div:
        return jsonify({"error": f"Article '{title}' not found"}), 404

    h1 = soup.select_one("h1#firstHeading, h1.firstHeading")
    article_title = h1.get_text(strip=True) if h1 else title

    sections = []
    current = {"heading": "Overview", "text": ""}

    for el in content_div.children:
        if not hasattr(el, 'name'):
            continue
        if el.name in ('h2', 'h3'):
            heading_text = el.get_text(strip=True)
            if any(skip in heading_text for skip in ("Sources", "See also", "Development History", "Trivia")):
                break
            if current["text"].strip():
                sections.append(current)
            current = {"heading": heading_text, "text": ""}
        elif el.name in ('p', 'ul', 'ol', 'dl', 'blockquote'):
            current["text"] += el.get_text(separator=" ", strip=True) + "\n"

    if current["text"].strip():
        sections.append(current)

    full_text = ""
    for s in sections:
        if s["text"].strip():
            full_text += f"\n## {s['heading']}\n{s['text']}"

    full_text = clean_text(full_text)

    MAX_LENGTH = 12000
    truncated = False
    if len(full_text) > MAX_LENGTH:
        full_text = full_text[:MAX_LENGTH]
        truncated = True

    return jsonify({
        "title": article_title,
        "url": response.url,
        "sections": [s["heading"] for s in sections if s["text"].strip()],
        "content": full_text,
        "truncated": truncated,
        "source": "wh40k.lexicanum.com"
    })


if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)
