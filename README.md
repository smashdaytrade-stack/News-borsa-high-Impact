
# Price Sensitive News Bot (Telegram)

Bot gratuito che legge feed RSS (ANSA, Investing, ecc.), filtra news price-sensitive e le pubblica su Telegram.

## Setup rapido
1. Imposta i **Secrets** del repo:
   - `BOT_TOKEN` (BotFather)
   - `GH_PAT` (Personal Access Token, scope `repo`) — per committare `data/seen.db`
   - `CHANNEL_USERNAME` (senza `@`) — opzionale, per pulsanti Indice
2. Modifica `config.yml` con **fonti**, **filtri**, **categorie** e il tuo `channel_chat_id`.
3. Il workflow (`.github/workflows/run.yml`) esegue ogni 5 minuti.

## Test locale
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export BOT_TOKEN="<TOKEN>"
export CHANNEL_USERNAME="<canale>"
python newsbot.py
```

## Note
- Il bot pubblica **titolo + link** e hashtag categorie.
- Dedup su SQLite: `data/seen.db` viene committato dal workflow....
