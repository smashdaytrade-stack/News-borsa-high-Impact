
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import time
import json
import hashlib
import sqlite3
import logging
import html
from datetime import datetime, timezone, timedelta
from urllib.parse import quote_plus

import yaml
import requests
import feedparser
from bs4 import BeautifulSoup
from dateutil import parser as dateparser

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

def load_config(path="config.yml"):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def ensure_db(path="data/seen.db"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS seen (
            id TEXT PRIMARY KEY,
            url TEXT,
            title TEXT,
            ts DATETIME
        )
    """)
    conn.commit()
    return conn

def clean_html(text):
    if not text:
        return ""
    soup = BeautifulSoup(text, "html.parser")
    txt = soup.get_text(" ", strip=True)
    return re.sub(r"\s+", " ", txt)

def normalize(s):
    return re.sub(r"\s+", " ", s or "").strip().lower()

def sha(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

def parse_dt(entry):
    for k in ("published", "updated", "created"):
        if k in entry:
            try:
                return dateparser.parse(entry[k])
            except Exception:
                pass
    return datetime.now(timezone.utc)

def keyword_score(text, include, exclude):
    t = normalize(text)
    score = 0
    for w in include:
        if w.lower() in t:
            score += 1
    for w in exclude:
        if w.lower() in t:
            score -= 1
    return score

def company_boost(text, companies):
    t = normalize(text)
    boost = 0
    hits = []
    for c in companies or []:
        for tk in c.get("tickers", []):
            if tk.lower() in t:
                boost += c.get("boost", 1)
                hits.append(c["name"])
                break
    return boost, list(set(hits))

def categorize(text, cat_map):
    t = normalize(text)
    cats = []
    for cat, kws in (cat_map or {}).items():
        for kw in kws:
            if kw.lower() in t:
                cats.append(cat)
                break
    return sorted(list(set(cats)))[:3]

def format_hashtag(s):
    return "#" + re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_")

def make_telegram_message(item, source_name, cats, add_source_hashtag=True, add_time=True):
    title = html.escape(item["title"])
    url = item["link"]
    source_tag = f" #{re.sub(r'[^A-Za-z0-9]+','', source_name)}" if add_source_hashtag else ""
    cats_tags = " ".join(format_hashtag(c) for c in cats) if cats else ""
    time_str = ""
    if add_time and item.get("dt"):
        ts = item["dt"].astimezone(timezone(timedelta(hours=1)))
        time_str = f"
🕒 {ts.strftime('%Y-%m-%d %H:%M')}"
    msg = f"<b>{title}</b>
{url}
{cats_tags}{source_tag}{time_str}"
    return msg

def send_telegram(bot_token, chat_id, text, parse_mode="HTML", disable_web_page_preview=False, buttons=None):
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": disable_web_page_preview
    }
    if buttons:
        payload["reply_markup"] = json.dumps({"inline_keyboard": buttons})
    r = requests.post(url, data=payload, timeout=15)
    if r.status_code != 200:
        logging.error("Telegram error %s: %s", r.status_code, r.text)
    return r

def should_post(conn, uid):
    c = conn.cursor()
    c.execute("SELECT 1 FROM seen WHERE id=?", (uid,))
    return c.fetchone() is None

def mark_posted(conn, uid, url, title):
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO seen (id, url, title, ts) VALUES (?, ?, ?, ?)",
              (uid, url, title, datetime.utcnow().isoformat()))
    conn.commit()

def build_index_buttons(channel_username, cfg):
    base = f"https://t.me/s/{channel_username}"
    btns = []
    row = []
    for b in cfg.get("telegram", {}).get("index_message", {}).get("buttons", []):
        row.append({"text": b["text"], "url": f"{base}?q={b['url_query']}"})
        if len(row) == 3:
            btns.append(row)
            row = []
    if row:
        btns.append(row)
    return btns

def main():
    cfg = load_config("config.yml")
    conn = ensure_db("data/seen.db")

    include = cfg["filters"].get("include_keywords", [])
    exclude = cfg["filters"].get("exclude_keywords", [])
    min_score = cfg["filters"].get("min_score", 2)
    companies = cfg.get("companies", [])
    categories = cfg.get("categories", {})
    tg = cfg.get("telegram", {})

    bot_token = os.environ.get("BOT_TOKEN") or ""
    chat_id = tg.get("channel_chat_id")
    parse_mode = tg.get("parse_mode", "HTML")

    if not bot_token or not chat_id:
        raise RuntimeError("BOT_TOKEN (env) o channel_chat_id (config.yml) mancanti.")

    posted = 0
    for src in cfg.get("sources", []):
        name = src["name"]
        url = src["url"]
        logging.info("Leggo feed: %s", name)
        try:
            feed = feedparser.parse(url)
        except Exception as e:
            logging.error("Errore RSS %s: %s", name, e)
            continue
        for entry in feed.entries:
            title = clean_html(entry.get("title", ""))
            summary = clean_html(entry.get("summary", ""))
            link = entry.get("link") or ""
            dt = parse_dt(entry)

            text_for_score = f"{title} {summary}"
            score = keyword_score(text_for_score, include, exclude)
            boost, hits = company_boost(text_for_score, companies)
            total = score + boost

            uid = sha(link or title)
            if total >= min_score and should_post(conn, uid):
                cats = categorize(text_for_score, categories)
                msg = make_telegram_message(
                    {"title": title, "link": link, "dt": dt},
                    source_name=name,
                    cats=cats,
                    add_source_hashtag=tg.get("add_source_hashtag", True),
                    add_time=tg.get("add_time", True),
                )
                send_telegram(bot_token, chat_id, msg, parse_mode=parse_mode, disable_web_page_preview=False)
                mark_posted(conn, uid, link, title)
                posted += 1
                time.sleep(0.8)

    logging.info("Notizie postate: %s", posted)

    idx_cfg = tg.get("index_message", {})
    if idx_cfg.get("enabled"):
        channel_username = os.environ.get("CHANNEL_USERNAME")
        if channel_username:
            buttons = build_index_buttons(channel_username, cfg)
            title = "<b>Indice news per categoria</b>
Seleziona una categoria per filtrare le notizie per hashtag."
            send_telegram(bot_token, chat_id, title, parse_mode=parse_mode, buttons=buttons)

if __name__ == "__main__":
    main()
