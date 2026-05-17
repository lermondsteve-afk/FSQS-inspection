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

# ── API — KPIs ─────────────────────────────────────────────────────────────
@app.route('/api/kpis')
def api_kpis():
    periode = int(request.args.get('jours', 30))
    since = (date.today() - timedelta(periode)).isoformat()
    since_prev = (date.today() - timedelta(periode * 2)).isoformat()

    cur = q1("SELECT ROUND(AVG(score_global),1) as s, SUM(nb_ko) as k, SUM(nb_alertes) as a, COUNT(*) as n FROM inspections WHERE date>=?", (since,))
    prev = q1("SELECT ROUND(AVG(score_global),1) as s FROM inspections WHERE date>=? AND date<?", (since_prev, since))

    score = cur['s'] or 0
    score_prev = prev['s'] or score
    delta = round(score - score_prev, 1)

    total_items = q1("SELECT COUNT(*) as n FROM resultats r JOIN inspections i ON r.inspection_id=i.id WHERE i.date>=?", (since,))['n']
    conf_items = q1("SELECT COUNT(*) as n FROM resultats r JOIN inspections i ON r.inspection_id=i.id WHERE i.date>=? AND r.notation='A'", (since,))['n']
    conf_rate = round(conf_items / total_items * 100) if total_items else 0

    return jsonify({
        'score_global': score,
        'score_delta': delta,
        'nb_ko': cur['k'] or 0,
        'nb_alertes': cur['a'] or 0,
        'nb_inspections': cur['n'] or 0,
        'conf_rate': conf_rate,
    })

# ── API — Analyse IA (Version Groq Gratuite) ───────────────────────────────
@app.route('/api/analyse_ia', methods=['POST'])
def api_analyse_ia():
    GROQ_KEY = os.environ.get('GROQ_API_KEY')
    if not GROQ_KEY:
        return jsonify({'error': 'Clé API GROQ non configurée'}), 500

    question = request.json.get('question', '')
    periode = int(request.json.get('jours', 30))
    since = (date.today() - timedelta(periode)).isoformat()

    # Build context from DB
    kpis = q1("SELECT ROUND(AVG(score_global),1) as score, SUM(nb_ko) as ko, SUM(nb_alertes) as alertes, COUNT(*) as inspections FROM inspections WHERE date>=?", (since,))
    scores_act = q("SELECT r.activite, ROUND(AVG(CASE r.notation WHEN 'A' THEN 100 WHEN 'B' THEN 66 WHEN 'C' THEN 33 WHEN 'D' THEN 0 END),1) as score FROM resultats r JOIN inspections i ON r.inspection_id=i.id WHERE i.date>=? AND r.notation NOT
