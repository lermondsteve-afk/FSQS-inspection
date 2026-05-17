"""
FSQS Inspection Pro — Backend Flask (Version Groq Gratuite)
"""
import os, json, sqlite3
from datetime import date, timedelta
from flask import Flask, render_template, jsonify, request, g
from groq import Groq

app = Flask(__name__)

DB_PATH = os.path.join(os.path.dirname(__file__), 'data', 'inspections.db')

# ── DB helpers ─────────────────────────────────────────────────────────────
def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(e=None):
    db = g.pop('db', None)
    if db: db.close()

def q(sql, args=()):
    return get_db().execute(sql, args).fetchall()

def q1(sql, args=()):
    row = get_db().execute(sql, args).fetchone()
    return dict(row) if row else None

# ── Pages ──────────────────────────────────────────────────────────────────
@app.route('/')
def index():
    return open('templates/index.html', encoding='utf-8').read()

# ── API — Analyse IA (Version Groq Gratuite) ───────────────────────────────
@app.route('/api/analyse_ia', methods=['POST'])
def api_analyse_ia():
    GROQ_KEY = os.environ.get('GROQ_API_KEY')
    if not GROQ_KEY:
        return jsonify({'error': 'Clé API GROQ non configurée'}), 500

    question = request.json.get('question', '')
    periode = int(request.json.get('jours', 30))
    since = (date.today() - timedelta(periode)).isoformat()

    # Build context
    kpis = q1("SELECT ROUND(AVG(score_global),1) as score, SUM(nb_ko) as ko, SUM(nb_alertes) as alertes, COUNT(*) as inspections FROM inspections WHERE date>=?", (since,))
    
    # Requête SQL corrigée et sur une seule ligne pour éviter les erreurs de coupure
    scores_act = q("SELECT r.activite, ROUND(AVG(CASE r.notation WHEN 'A' THEN 100 WHEN 'B' THEN 66 WHEN 'C' THEN 33 WHEN 'D' THEN 0 END),1) as score FROM resultats r JOIN inspections i ON r.inspection_id=i.id WHERE i.date>=? AND r.notation NOT IN ('S/O','N/E') GROUP BY r.activite ORDER BY score", (since,))
    
    items_crit = q("SELECT r.item_num, r.item_label, r.activite, COUNT(CASE WHEN r.notation IN ('C','D') THEN 1 END) as nb_nc, ROUND(COUNT(CASE WHEN r.notation IN ('C','D') THEN 1 END)*100.0/COUNT(*),0) as pct_nc FROM resultats r JOIN inspections i ON r.inspection_id=i.id WHERE i.date>=? AND r.notation NOT IN ('S/O','N/E') GROUP BY r.item_num HAVING nb_nc>=3 ORDER BY pct_nc DESC LIMIT 8", (since,))
    
    alertes_rec = q("SELECT activite, item_label, gravite, statut, date FROM alertes_ko WHERE date>=? ORDER BY date DESC LIMIT 8", (since,))

    context = f"KPIs: {kpis['score']}% score. Items NC: {items_crit}. Alertes: {alertes_rec}."

    client = Groq(api_key=GROQ_KEY)
    chat_completion = client.chat.completions.create(
        messages=[
            {"role": "system", "content": "Tu es un expert FSQS. Analyse les données et donne des recommandations concrètes."},
            {"role": "user", "content": f"{context}\n\nQuestion: {question}"}
        ],
        model="llama3-70b-8192",
    )

    return jsonify({'reponse': chat_completion.choices[0].message.content})

if __name__ == '__main__':
    app.run(debug=True, port=5000)
