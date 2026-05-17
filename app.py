"""
FSQS Inspection Pro — Backend Flask
API + serveur web complet
"""
import os, json, sqlite3
from datetime import date, timedelta
from flask import Flask, render_template, jsonify, request, g
import anthropic

app = Flask(__name__)

DB_PATH = os.path.join(os.path.dirname(__file__), 'data', 'inspections.db')
ANTHROPIC_KEY = os.environ.get('ANTHROPIC_API_KEY', '')

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

# ── API — Score par activité ───────────────────────────────────────────────
@app.route('/api/scores_activites')
def api_scores_activites():
    periode = int(request.args.get('jours', 30))
    since = (date.today() - timedelta(periode)).isoformat()
    since_prev = (date.today() - timedelta(periode * 2)).isoformat()

    rows = q("""
        SELECT r.activite,
               ROUND(AVG(CASE r.notation WHEN 'A' THEN 100 WHEN 'B' THEN 66 WHEN 'C' THEN 33 WHEN 'D' THEN 0 END),1) as score,
               COUNT(CASE WHEN r.notation='D' AND r.item_type='KO' THEN 1 END) as ko_count
        FROM resultats r JOIN inspections i ON r.inspection_id=i.id
        WHERE i.date>=? AND r.notation NOT IN ('S/O','N/E')
        GROUP BY r.activite ORDER BY score ASC
    """, (since,))

    rows_prev = {row['activite']: row['score'] for row in q("""
        SELECT r.activite, ROUND(AVG(CASE r.notation WHEN 'A' THEN 100 WHEN 'B' THEN 66 WHEN 'C' THEN 33 WHEN 'D' THEN 0 END),1) as score
        FROM resultats r JOIN inspections i ON r.inspection_id=i.id
        WHERE i.date>=? AND i.date<? AND r.notation NOT IN ('S/O','N/E')
        GROUP BY r.activite
    """, (since_prev, since))}

    result = []
    for row in rows:
        s = row['score'] or 0
        p = rows_prev.get(row['activite'], s)
        result.append({'activite': row['activite'], 'score': s, 'delta': round(s - p, 1), 'ko_count': row['ko_count']})
    return jsonify(result)

# ── API — Tendance ─────────────────────────────────────────────────────────
@app.route('/api/tendance')
def api_tendance():
    rows = q("""
        SELECT date, ROUND(AVG(score_global),1) as score, SUM(nb_ko) as ko, SUM(nb_alertes) as alertes
        FROM inspections GROUP BY date ORDER BY date
    """)
    return jsonify([dict(r) for r in rows])

# ── API — Alertes récentes ─────────────────────────────────────────────────
@app.route('/api/alertes')
def api_alertes():
    rows = q("""
        SELECT * FROM alertes_ko ORDER BY date DESC LIMIT 20
    """)
    return jsonify([dict(r) for r in rows])

# ── API — Stats alertes ────────────────────────────────────────────────────
@app.route('/api/alertes_stats')
def api_alertes_stats():
    periode = int(request.args.get('jours', 30))
    since = (date.today() - timedelta(periode)).isoformat()
    stats = q1("""
        SELECT
            COUNT(CASE WHEN gravite='KO' THEN 1 END) as nb_ko,
            COUNT(CASE WHEN gravite='Alerte' THEN 1 END) as nb_alertes,
            COUNT(CASE WHEN statut='ouverte' THEN 1 END) as nb_ouvertes,
            COUNT(CASE WHEN statut='resolue' THEN 1 END) as nb_resolues
        FROM alertes_ko WHERE date>=?
    """, (since,))
    actions = q1("""
        SELECT
            COUNT(CASE WHEN ac.statut='realisee' THEN 1 END) as realisees,
            COUNT(CASE WHEN ac.statut='en_cours' THEN 1 END) as en_cours,
            COUNT(CASE WHEN ac.statut='planifiee' THEN 1 END) as planifiees
        FROM actions_correctives ac
        JOIN alertes_ko ak ON ac.alerte_id=ak.id
        WHERE ak.date>=?
    """, (since,))
    return jsonify({**dict(stats), **dict(actions)})

# ── API — Actions correctives ──────────────────────────────────────────────
@app.route('/api/actions')
def api_actions():
    rows = q("""
        SELECT ac.*, ak.activite, ak.item_label, ak.gravite, ak.date
        FROM actions_correctives ac
        JOIN alertes_ko ak ON ac.alerte_id=ak.id
        WHERE ac.statut != 'realisee'
        ORDER BY ac.priorite DESC, ak.date DESC LIMIT 10
    """)
    return jsonify([dict(r) for r in rows])

# ── API — Items critiques ──────────────────────────────────────────────────
@app.route('/api/items_critiques')
def api_items_critiques():
    periode = int(request.args.get('jours', 30))
    since = (date.today() - timedelta(periode)).isoformat()
    rows = q("""
        SELECT r.item_num, r.item_label, r.activite, r.item_type,
               COUNT(CASE WHEN r.notation IN ('C','D') THEN 1 END) as nb_nc,
               COUNT(*) as nb_total,
               ROUND(COUNT(CASE WHEN r.notation IN ('C','D') THEN 1 END)*100.0/COUNT(*),0) as pct_nc
        FROM resultats r JOIN inspections i ON r.inspection_id=i.id
        WHERE i.date>=? AND r.notation NOT IN ('S/O','N/E')
        GROUP BY r.item_num, r.item_label, r.activite
        HAVING nb_nc >= 3
        ORDER BY pct_nc DESC LIMIT 10
    """, (since,))
    return jsonify([dict(r) for r in rows])

# ── API — Saisie nouvelle inspection ──────────────────────────────────────
@app.route('/api/saisie', methods=['POST'])
def api_saisie():
    data = request.json
    db = get_db()
    try:
        db.execute("""INSERT INTO inspections (date,magasin,inspecteur,statut,score_global,nb_ko,nb_alertes)
                      VALUES (?,?,?,?,?,?,?)""",
                   (data['date'], data.get('magasin','Magasin Principal'),
                    data['inspecteur'], 'terminee',
                    data.get('score_global',0), data.get('nb_ko',0), data.get('nb_alertes',0)))
        insp_id = db.execute('SELECT last_insert_rowid()').fetchone()[0]

        for r in data.get('resultats', []):
            db.execute("""INSERT INTO resultats (inspection_id,activite,etape,item_num,item_label,item_type,notation,commentaire)
                          VALUES (?,?,?,?,?,?,?,?)""",
                       (insp_id, r['activite'], r['etape'], r['item_num'],
                        r['item_label'], r['item_type'], r['notation'], r.get('commentaire','')))

        db.commit()
        return jsonify({'success': True, 'inspection_id': insp_id})
    except Exception as e:
        db.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500

# ── API — Analyse IA ───────────────────────────────────────────────────────
@app.route('/api/analyse_ia', methods=['POST'])
def api_analyse_ia():
    if not ANTHROPIC_KEY:
        return jsonify({'error': 'Clé API non configurée'}), 500

    question = request.json.get('question', '')
    periode = int(request.json.get('jours', 30))
    since = (date.today() - timedelta(periode)).isoformat()

    # Build context from DB
    kpis = q1("""SELECT ROUND(AVG(score_global),1) as score, SUM(nb_ko) as ko,
                        SUM(nb_alertes) as alertes, COUNT(*) as inspections
                 FROM inspections WHERE date>=?""", (since,))

    scores_act = q("""
        SELECT r.activite, ROUND(AVG(CASE r.notation WHEN 'A' THEN 100 WHEN 'B' THEN 66 WHEN 'C' THEN 33 WHEN 'D' THEN 0 END),1) as score
        FROM resultats r JOIN inspections i ON r.inspection_id=i.id
        WHERE i.date>=? AND r.notation NOT IN ('S/O','N/E') GROUP BY r.activite ORDER BY score
    """, (since,))

    items_crit = q("""
        SELECT r.item_num, r.item_label, r.activite,
               COUNT(CASE WHEN r.notation IN ('C','D') THEN 1 END) as nb_nc,
               ROUND(COUNT(CASE WHEN r.notation IN ('C','D') THEN 1 END)*100.0/COUNT(*),0) as pct_nc
        FROM resultats r JOIN inspections i ON r.inspection_id=i.id
        WHERE i.date>=? AND r.notation NOT IN ('S/O','N/E')
        GROUP BY r.item_num HAVING nb_nc>=3 ORDER BY pct_nc DESC LIMIT 8
    """, (since,))

    alertes_rec = q("SELECT activite, item_label, gravite, statut, date FROM alertes_ko WHERE date>=? ORDER BY date DESC LIMIT 8", (since,))

    tendance = q("SELECT date, ROUND(AVG(score_global),1) as score FROM inspections GROUP BY date ORDER BY date")

    context = f"""
DONNÉES FSQS — Magasin Principal — {periode} derniers jours (depuis {since})

=== KPIs GLOBAUX ===
Score global moyen : {kpis['score']}%
KO déclenchés : {kpis['ko']}
Alertes : {kpis['alertes']}
Inspections réalisées : {kpis['inspections']}

=== SCORES PAR ACTIVITÉ (du plus bas au plus haut) ===
{chr(10).join(f"- {r['activite']}: {r['score']}%" for r in scores_act)}

=== ITEMS LES PLUS NON-CONFORMES ===
{chr(10).join(f"- [{r['item_num']}] {r['item_label'][:60]} ({r['activite']}) — {r['pct_nc']}% NC sur {periode}j" for r in items_crit)}

=== ALERTES ET KO RÉCENTS ===
{chr(10).join(f"- {r['date']} | {r['gravite']} | {r['activite']} | {r['item_label'][:50]} | {r['statut']}" for r in alertes_rec)}

=== TENDANCE SCORES (dates clés) ===
{chr(10).join(f"{r['date']}: {r['score']}%" for r in tendance[::5])}
"""

    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    response = client.messages.create(
        model='claude-sonnet-4-20250514',
        max_tokens=1500,
        system="""Tu es un expert en sécurité alimentaire et en référentiels d'inspection FSQS (Food Store Quality Standard).
Tu analyses les données d'inspection d'un magasin de distribution alimentaire.
Ton rôle : donner des analyses précises, des recommandations concrètes et actionnables.
Format de réponse : structuré avec des sections claires, des chiffres précis, des actions prioritaires numérotées.
Langue : français professionnel. Sois direct et factuel.""",
        messages=[{'role': 'user', 'content': f"{context}\n\n=== QUESTION ===\n{question}"}]
    )

    return jsonify({'reponse': response.content[0].text})

if __name__ == '__main__':
    app.run(debug=True, port=5000)
