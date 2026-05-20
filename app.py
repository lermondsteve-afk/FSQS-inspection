--- app.py (原始)
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
        model="llama-3.3-70b-versatile",
    )
    return jsonify({'reponse': chat_completion.choices[0].message.content})

@app.route('/api/ping')
def ping():
    return jsonify({'status': 'ok'})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)

+++ app.py (修改后)
"""
FSQS Inspection Pro — Backend Flask (Version Groq Gratuite)
UPGRADE: Added security, error handling, and robustness improvements
"""
import os, json, sqlite3, logging, time
from datetime import date, timedelta
from functools import wraps
from flask import Flask, render_template, jsonify, request, g
from groq import Groq
from dotenv import load_dotenv
import bleach

# Load environment variables from .env file
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
DB_PATH = os.path.join(os.path.dirname(__file__), 'inspections.db')

# Rate limiting configuration
RATE_LIMIT_REQUESTS = 10  # Max requests per minute for AI endpoint
RATE_LIMIT_WINDOW = 60  # Time window in seconds

# Simple in-memory rate limiter (for production, use Redis)
rate_limit_store = {}

def rate_limit(max_requests=RATE_LIMIT_REQUESTS, window=RATE_LIMIT_WINDOW):
    """Rate limiting decorator to prevent API abuse"""
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            client_ip = request.remote_addr or 'unknown'
            current_time = time.time()

            if client_ip not in rate_limit_store:
                rate_limit_store[client_ip] = []

            # Clean old requests outside the window
            rate_limit_store[client_ip] = [
                t for t in rate_limit_store[client_ip]
                if current_time - t < window
            ]

            if len(rate_limit_store[client_ip]) >= max_requests:
                logger.warning(f"Rate limit exceeded for IP: {client_ip}")
                return jsonify({'error': 'Trop de requêtes. Veuillez réessayer plus tard.'}), 429

            rate_limit_store[client_ip].append(current_time)
            return f(*args, **kwargs)
        return wrapped
    return decorator

def sanitize_input(text, max_length=5000):
    """Sanitize user input to prevent XSS attacks"""
    if text is None:
        return None
    if not isinstance(text, str):
        text = str(text)
    # Truncate to max length
    text = text[:max_length]
    # Remove potentially dangerous HTML tags
    return bleach.clean(text, tags=[], strip=True)

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
    """Execute SQL query with parameterized inputs to prevent SQL injection"""
    try:
        return get_db().execute(sql, args).fetchall()
    except sqlite3.Error as e:
        logger.error(f"Database error in q(): {e}")
        raise

def q1(sql, args=()):
    """Execute SQL query and return single row"""
    try:
        row = get_db().execute(sql, args).fetchone()
        return dict(row) if row else None
    except sqlite3.Error as e:
        logger.error(f"Database error in q1(): {e}")
        raise

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
    """UPGRADE: Added input validation and sanitization"""
    data = request.json
    if not data:
        return jsonify({'success': False, 'error': 'Données invalides'}), 400

    db = get_db()
    try:
        # Validate and sanitize inputs
        inspection_date = sanitize_input(data.get('date', ''))
        if not inspection_date:
            return jsonify({'success': False, 'error': 'Date requise'}), 400

        inspecteur = sanitize_input(data.get('inspecteur', ''), max_length=200)
        score_global = float(data.get('score_global', 0))
        nb_ko = int(data.get('nb_ko', 0))
        nb_alertes = int(data.get('nb_alertes', 0))

        cur = db.execute(
            """INSERT INTO inspections
               (date, inspecteur, score_global, nb_ko, nb_alertes)
               VALUES (?,?,?,?,?)""",
            (inspection_date, inspecteur or '', score_global, nb_ko, nb_alertes)
        )
        inspection_id = cur.lastrowid

        for r in data.get('resultats', []):
            # Sanitize each result field
            item_num = sanitize_input(r.get('num', ''), max_length=50)
            item_label = sanitize_input(r.get('label', ''), max_length=500)
            activite = sanitize_input(r.get('activite', ''), max_length=200)
            etape = sanitize_input(r.get('etape', ''), max_length=200)
            item_type = sanitize_input(r.get('type', ''), max_length=50)
            notation = sanitize_input(r.get('notation', ''), max_length=10)
            commentaire = sanitize_input(r.get('commentaire', ''), max_length=2000)

            db.execute(
                """INSERT INTO resultats
                   (inspection_id, item_num, item_label, activite, etape, type, notation, commentaire)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (inspection_id, item_num, item_label, activite, etape, item_type, notation, commentaire or '')
            )

            # Auto-create alerte if KO or Alerte type with bad notation
            if item_type in ('KO', 'Alerte') and notation in ('C', 'D'):
                db.execute(
                    """INSERT INTO alertes_ko
                       (inspection_id, item_num, item_label, activite, etape, gravite, statut, date)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (inspection_id, item_num, item_label, activite, etape, item_type, 'ouverte', inspection_date)
                )

        db.commit()
        logger.info(f"Inspection created successfully: ID {inspection_id}")
        return jsonify({'success': True, 'inspection_id': inspection_id})
    except ValueError as e:
        db.rollback()
        logger.error(f"Validation error in saisie: {e}")
        return jsonify({'success': False, 'error': f'Données invalides: {str(e)}'}), 400
    except Exception as e:
        db.rollback()
        logger.error(f"Error in saisie: {e}")
        return jsonify({'success': False, 'error': 'Erreur serveur lors de la sauvegarde'}), 500

# ── API — Analyse IA ────────────────────────────────────────────────────────
@app.route('/api/analyse_ia', methods=['POST'])
@rate_limit(max_requests=10, window=60)  # UPGRADE: Rate limiting
def api_analyse_ia():
    """UPGRADE: Added retry logic, timeout control, and better error handling"""
    GROQ_KEY = os.environ.get('GROQ_API_KEY')
    if not GROQ_KEY:
        logger.error("GROQ_API_KEY not configured")
        return jsonify({'error': 'Clé API GROQ non configurée. Vérifiez votre fichier .env'}), 500

    # Validate API key format (basic check)
    if not GROQ_KEY.startswith('gsk_'):
        logger.warning("GROQ_API_KEY may be invalid (should start with 'gsk_')")

    data = request.json or {}
    question = sanitize_input(data.get('question', ''), max_length=2000)
    if not question:
        return jsonify({'error': 'Question requise'}), 400

    periode = int(data.get('jours', 30))
    if periode < 1 or periode > 365:
        periode = 30  # Default to 30 days if out of range

    since = (date.today() - timedelta(periode)).isoformat()

    try:
        # Fetch context data with error handling
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

        # Build optimized context (token-efficient)
        context_parts = []
        if kpis:
            context_parts.append(f"KPIs ({periode}j): score={kpis['score']}%, KO={kpis['ko']}, alertes={kpis['alertes']}, inspections={kpis['inspections']}")
        if scores_act:
            scores_summary = ', '.join([f"{r['activite']}:{r['score']}" for r in scores_act[:5]])
            context_parts.append(f"Scores activités: {scores_summary}")
        if items_crit:
            items_summary = ', '.join([f"{r['item_num']}:{r['pct_nc']}%" for r in items_crit[:4]])
            context_parts.append(f"Items critiques: {items_summary}")
        if alertes_rec:
            alertes_count = len(alertes_rec)
            context_parts.append(f"Alertes récentes: {alertes_count}")

        context = '. '.join(context_parts) if context_parts else "Aucune donnée disponible."

        # Retry logic with exponential backoff
        max_retries = 3
        base_delay = 2  # seconds
        last_error = None

        for attempt in range(max_retries):
            try:
                client = Groq(api_key=GROQ_KEY, timeout=30)  # UPGRADE: Timeout control

                chat_completion = client.chat.completions.create(
                    messages=[
                        {"role": "system", "content": "Tu es un expert FSQS (Food Safety & Quality System). Analyse les données d'inspection et donne des recommandations concrètes, précises et actionnables. Réponds en français."},
                        {"role": "user", "content": f"{context}\n\nQuestion: {question}"}
                    ],
                    model="llama-3.3-70b-versatile",
                    temperature=0.7,
                    max_tokens=1500
                )

                response_content = chat_completion.choices[0].message.content
                logger.info(f"AI analysis completed successfully (attempt {attempt + 1})")
                return jsonify({'reponse': response_content, 'context_used': context})

            except Exception as e:
                last_error = e
                error_msg = str(e)

                # Check for specific error types
                if 'authentication' in error_msg.lower() or 'unauthorized' in error_msg.lower():
                    logger.error("Authentication failed with Groq API")
                    return jsonify({'error': 'Clé API invalide. Vérifiez votre clé GROQ.'}), 401
                elif 'rate limit' in error_msg.lower():
                    logger.warning("Groq rate limit hit")
                    if attempt < max_retries - 1:
                        delay = base_delay * (2 ** attempt)
                        time.sleep(delay)
                        continue
                    return jsonify({'error': 'Limite de débit API atteinte. Réessayez dans quelques minutes.'}), 429
                elif 'timeout' in error_msg.lower():
                    logger.warning("Groq API timeout")
                    if attempt < max_retries - 1:
                        delay = base_delay * (2 ** attempt)
                        time.sleep(delay)
                        continue
                    return jsonify({'error': "Délai d'attente API dépassé. Réessayez."}), 504
                else:
                    logger.warning(f"Groq API error (attempt {attempt + 1}): {error_msg}")
                    if attempt < max_retries - 1:
                        delay = base_delay * (2 ** attempt)
                        time.sleep(delay)
                        continue

        # All retries failed
        logger.error(f"All retries failed for AI analysis: {last_error}")
        return jsonify({
            'error': "Erreur de connexion à l'IA après plusieurs tentatives.",
            'details': str(last_error) if app.debug else None
        }), 503

    except sqlite3.Error as e:
        logger.error(f"Database error in analyse_ia: {e}")
        return jsonify({'error': 'Erreur de base de données'}), 500
    except Exception as e:
        logger.error(f"Unexpected error in analyse_ia: {e}")
        return jsonify({'error': 'Erreur interne du serveur'}), 500

@app.route('/api/ping')
def ping():
    return jsonify({'status': 'ok'})

# UPGRADE: Health check endpoint for monitoring
@app.route('/api/health')
def health_check():
    """UPGRADE: Comprehensive health check endpoint"""
    try:
        # Check database connection
        db = get_db()
        db.execute("SELECT 1").fetchone()
        db_status = "connected"
    except Exception as e:
        db_status = f"error: {str(e)}"

    # Check API key configuration
    api_key_configured = bool(os.environ.get('GROQ_API_KEY'))

    return jsonify({
        'status': 'healthy',
        'timestamp': date.today().isoformat(),
        'database': db_status,
        'api_key_configured': api_key_configured,
        'version': '2.0.0'
    })

if __name__ == '__main__':
    # UPGRADE: Load port from environment variable
    port = int(os.environ.get('PORT', 10000))
    logger.info(f"Starting FSQS Inspection Pro on port {port}")
    app.run(host='0.0.0.0', port=port, debug=os.environ.get('FLASK_ENV', 'development') == 'development')
