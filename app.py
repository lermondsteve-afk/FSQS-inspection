"""
FSQS Inspection Pro — Backend Flask (Version Groq Gratuite)
"""
import os, json, sqlite3
from datetime import date, timedelta
from flask import Flask, render_template, jsonify, request, g
from groq import Groq

app = Flask(__name__)
DB_PATH = os.path.join(os.path.dirname(__file__), 'inspections.db')

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
    return open('index.html', encoding='utf-8').read()

# ── API — KPIs ─────────────────────────────────────────────────────────────
@app.route('/api/kpis')
def api_kpis():
    jours = int(request.args.get('jours', 30))
    since = (date.today() - timedelta(jours)).isoformat()
    prev_since = (date.today() - timedelta(jours * 2)).isoformat()

    cur = q1("""SELECT ROUND(AVG(score_global),1) as score,
                       SUM(nb_ko) as nb_ko,
                       SUM(nb_alertes) as nb_alertes,
                       COUNT(*) as nb_inspections
                FROM inspections WHERE date>=?""", (since,))

    prev = q1("""SELECT ROUND(AVG(score_global),1) as score
                 FROM inspections WHERE date>=? AND date<?""", (prev_since, since))

    # Taux de conformité : % de notations A
    conf = q1("""SELECT
                   ROUND(100.0 * SUM(CASE WHEN notation='A' THEN 1 ELSE 0 END)
                         / NULLIF(COUNT(*),0), 1) as conf_rate
                 FROM resultats r
                 JOIN inspections i ON r.inspection_id=i.id
                 WHERE i.date>=? AND r.notation NOT IN ('S/O','N/E')""", (since,))

    score_now = cur['score'] or 0
    score_prev = (prev['score'] or 0) if prev else 0
    delta = round(score_now - score_prev, 1)

    return jsonify({
        'score_global': score_now,
        'nb_ko': cur['nb_ko'] or 0,
        'nb_alertes': cur['nb_alertes'] or 0,
        'nb_inspections': cur['nb_inspections'] or 0,
        'conf_rate': conf['conf_rate'] or 0 if conf else 0,
        'score_delta': delta
    })

# ── API — Scores par activité ───────────────────────────────────────────────
@app.route('/api/scores_activites')
def api_scores_activites():
    jours = int(request.args.get('jours', 30))
    since = (date.today() - timedelta(jours)).isoformat()
    prev_since = (date.today() - timedelta(jours * 2)).isoformat()

    rows = q("""SELECT r.activite,
                       ROUND(AVG(CASE r.notation
                           WHEN 'A' THEN 100 WHEN 'B' THEN 66
                           WHEN 'C' THEN 33  WHEN 'D' THEN 0 END), 1) as score
                FROM resultats r
                JOIN inspections i ON r.inspection_id=i.id
                WHERE i.date>=? AND r.notation NOT IN ('S/O','N/E')
                GROUP BY r.activite ORDER BY score""", (since,))

    prev_rows = q("""SELECT r.activite,
                            ROUND(AVG(CASE r.notation
                                WHEN 'A' THEN 100 WHEN 'B' THEN 66
                                WHEN 'C' THEN 33  WHEN 'D' THEN 0 END), 1) as score
                     FROM resultats r
                     JOIN inspections i ON r.inspection_id=i.id
                     WHERE i.date>=? AND i.date<? AND r.notation NOT IN ('S/O','N/E')
                     GROUP BY r.activite""", (prev_since, since))

    prev_map = {r['activite']: r['score'] for r in prev_rows}

    result = []
    for r in rows:
        s = r['score'] or 0
        p = prev_map.get(r['activite'], s)
        result.append({
            'activite': r['activite'],
            'score': s,
            'delta': round(s - (p or s), 1)
        })
    return jsonify(result)

# ── API — Tendance ──────────────────────────────────────────────────────────
@app.route('/api/tendance')
def api_tendance():
    rows = q("""SELECT date,
                       ROUND(AVG(score_global),1) as score,
                       SUM(nb_ko) as ko,
                       SUM(nb_alertes) as alertes
                FROM inspections
                GROUP BY date ORDER BY date DESC LIMIT 60""")
    data = [{'date': r['date'], 'score': r['score'] or 0,
             'ko': r['ko'] or 0, 'alertes': r['alertes'] or 0}
            for r in reversed(rows)]
    return jsonify(data)

# ── API — Alertes ───────────────────────────────────────────────────────────
@app.route('/api/alertes')
def api_alertes():
    rows = q("""SELECT * FROM alertes_ko ORDER BY date DESC LIMIT 50""")
    return jsonify([dict(r) for r in rows])

@app.route('/api/alertes_stats')
def api_alertes_stats():
    jours = int(request.args.get('jours', 30))
    since = (date.today() - timedelta(jours)).isoformat()
    row = q1("""SELECT
                  SUM(CASE WHEN gravite='KO' THEN 1 ELSE 0 END) as nb_ko,
                  SUM(CASE WHEN gravite='Alerte' THEN 1 ELSE 0 END) as nb_alertes,
                  SUM(CASE WHEN statut!='resolue' THEN 1 ELSE 0 END) as nb_ouvertes,
                  SUM(CASE WHEN statut='resolue' THEN 1 ELSE 0 END) as nb_resolues
                FROM alertes_ko WHERE date>=?""", (since,))
    return jsonify(dict(row) if row else {})

# ── API — Actions correctives ───────────────────────────────────────────────
@app.route('/api/actions')
def api_actions():
    rows = q("""SELECT * FROM actions_correctives ORDER BY date_echeance ASC LIMIT 50""")
    return jsonify([dict(r) for r in rows])

# ── API — Items critiques ───────────────────────────────────────────────────
@app.route('/api/items_critiques')
def api_items_critiques():
    jours = int(request.args.get('jours', 30))
    since = (date.today() - timedelta(jours)).isoformat()
    rows = q("""SELECT r.item_num, r.item_label, r.activite, r.type as item_type,
                       COUNT(CASE WHEN r.notation IN ('C','D') THEN 1 END) as nb_nc,
                       COUNT(*) as nb_total,
                       ROUND(COUNT(CASE WHEN r.notation IN ('C','D') THEN 1 END)*100.0/COUNT(*),0) as pct_nc
                FROM resultats r
                JOIN inspections i ON r.inspection_id=i.id
                WHERE i.date>=? AND r.notation NOT IN ('S/O','N/E')
                GROUP BY r.item_num, r.activite
                HAVING nb_nc>=3
                ORDER BY pct_nc DESC LIMIT 20""", (since,))
    return jsonify([dict(r) for r in rows])

# ── API — Saisie inspection ─────────────────────────────────────────────────
@app.route('/api/saisie', methods=['POST'])
def api_saisie():
    data = request.json
    db = get_db()
    try:
        cur = db.execute(
            """INSERT INTO inspections
               (date, inspecteur, score_global, nb_ko, nb_alertes)
               VALUES (?,?,?,?,?)""",
            (data['date'], data.get('inspecteur',''), data.get('score_global', 0),
             data.get('nb_ko', 0), data.get('nb_alertes', 0))
        )
        inspection_id = cur.lastrowid

        for r in data.get('resultats', []):
            db.execute(
                """INSERT INTO resultats
                   (inspection_id, item_num, item_label, activite, etape, type, notation, commentaire)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (inspection_id, r.get('num'), r.get('label'), r.get('activite'),
                 r.get('etape'), r.get('type'), r.get('notation'), r.get('commentaire',''))
            )

            # Auto-create alerte if KO or Alerte type with bad notation
            if r.get('type') in ('KO', 'Alerte') and r.get('notation') in ('C', 'D'):
                db.execute(
                    """INSERT INTO alertes_ko
                       (inspection_id, item_num, item_label, activite, etape, gravite, statut, date)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (inspection_id, r.get('num'), r.get('label'), r.get('activite'),
                     r.get('etape'), r.get('type'), 'ouverte', data['date'])
                )

        db.commit()
        return jsonify({'success': True, 'inspection_id': inspection_id})
    except Exception as e:
        db.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500

# ── API — Analyse IA ────────────────────────────────────────────────────────
@app.route('/api/analyse_ia', methods=['POST'])
def api_analyse_ia():
    GROQ_KEY = os.environ.get('GROQ_API_KEY')
    if not GROQ_KEY:
        return jsonify({'error': 'Clé API GROQ non configurée'}), 500

    question = request.json.get('question', '')
    periode = int(request.json.get('jours', 30))
    since = (date.today() - timedelta(periode)).isoformat()

    kpis = q1("""SELECT ROUND(AVG(score_global),1) as score,
                        SUM(nb_ko) as ko, SUM(nb_alertes) as alertes,
                        COUNT(*) as inspections
                 FROM inspections WHERE date>=?""", (since,))

    scores_act = q("""SELECT r.activite,
                             ROUND(AVG(CASE r.notation
                                 WHEN 'A' THEN 100 WHEN 'B' THEN 66
                                 WHEN 'C' THEN 33  WHEN 'D' THEN 0 END),1) as score
                      FROM resultats r JOIN inspections i ON r.inspection_id=i.id
                      WHERE i.date>=? AND r.notation NOT IN ('S/O','N/E')
                      GROUP BY r.activite ORDER BY score""", (since,))

    items_crit = q("""SELECT r.item_num, r.item_label, r.activite,
                             COUNT(CASE WHEN r.notation IN ('C','D') THEN 1 END) as nb_nc,
                             ROUND(COUNT(CASE WHEN r.notation IN ('C','D') THEN 1 END)*100.0/COUNT(*),0) as pct_nc
                      FROM resultats r JOIN inspections i ON r.inspection_id=i.id
                      WHERE i.date>=? AND r.notation NOT IN ('S/O','N/E')
                      GROUP BY r.item_num HAVING nb_nc>=3 ORDER BY pct_nc DESC LIMIT 8""", (since,))

    alertes_rec = q("""SELECT activite, item_label, gravite, statut, date
                       FROM alertes_ko WHERE date>=? ORDER BY date DESC LIMIT 8""", (since,))

    context = (f"KPIs période {periode}j: score={kpis['score']}%, "
               f"KO={kpis['ko']}, alertes={kpis['alertes']}, inspections={kpis['inspections']}. "
               f"Scores activités: {[dict(r) for r in scores_act]}. "
               f"Items critiques: {[dict(r) for r in items_crit]}. "
               f"Alertes récentes: {[dict(r) for r in alertes_rec]}.")

    client = Groq(api_key=GROQ_KEY)
    chat_completion = client.chat.completions.create(
        messages=[
            {"role": "system", "content": "Tu es un expert FSQS (Food Safety & Quality System). Analyse les données d'inspection et donne des recommandations concrètes, précises et actionnables."},
            {"role": "user", "content": f"{context}\n\nQuestion: {question}"}
        ],
        model="llama3-70b-8192",
    )
    return jsonify({'reponse': chat_completion.choices[0].message.content})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
