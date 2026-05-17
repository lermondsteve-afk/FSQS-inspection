"""
Génère une base de données d'inspection simulée sur 2 mois
Format SQLite — remplaçable par vraies données semaine prochaine
"""
import sqlite3, json, re, random
from datetime import date, timedelta

with open('/home/claude/fsqs_filtered.json', 'r', encoding='utf-8') as f:
    data = json.load(f)
matrix = data['matrix']

KO_RE   = re.compile(r'\(KO\)')
ALRT_RE = re.compile(r'\(Alerte\)')
MESURE_KW = ['Nombre de ', "Nombre d'", 'Écart constaté']

def item_type(label):
    if KO_RE.search(label):   return 'KO'
    if ALRT_RE.search(label): return 'Alerte'
    if any(k in label for k in MESURE_KW): return 'Mesure'
    return 'Standard'

items_flat = []
for act, steps in matrix.items():
    for step, step_items in steps.items():
        for it in step_items:
            items_flat.append({
                'activite': act, 'etape': step,
                'num': it['num'], 'label': it['label'],
                'type': item_type(it['label'])
            })

DB = '/home/claude/fsqs_app/data/inspections.db'
conn = sqlite3.connect(DB)
c = conn.cursor()

c.executescript("""
DROP TABLE IF EXISTS inspections;
DROP TABLE IF EXISTS resultats;
DROP TABLE IF EXISTS alertes_ko;
DROP TABLE IF EXISTS actions_correctives;

CREATE TABLE inspections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    magasin TEXT NOT NULL DEFAULT 'Magasin Principal',
    inspecteur TEXT NOT NULL,
    statut TEXT DEFAULT 'terminee',
    score_global REAL,
    nb_ko INTEGER DEFAULT 0,
    nb_alertes INTEGER DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE resultats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    inspection_id INTEGER REFERENCES inspections(id),
    activite TEXT NOT NULL,
    etape TEXT NOT NULL,
    item_num TEXT NOT NULL,
    item_label TEXT NOT NULL,
    item_type TEXT NOT NULL,
    notation TEXT,
    commentaire TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE alertes_ko (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    inspection_id INTEGER REFERENCES inspections(id),
    date TEXT NOT NULL,
    activite TEXT NOT NULL,
    etape TEXT NOT NULL,
    item_num TEXT NOT NULL,
    item_label TEXT NOT NULL,
    gravite TEXT NOT NULL,
    statut TEXT DEFAULT 'ouverte',
    commentaire TEXT,
    date_resolution TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE actions_correctives (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    alerte_id INTEGER REFERENCES alertes_ko(id),
    description TEXT NOT NULL,
    responsable TEXT,
    priorite TEXT DEFAULT 'normale',
    statut TEXT DEFAULT 'planifiee',
    date_echeance TEXT,
    date_realisation TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
""")

# ── Realistic score profiles per activity ──────────────────────────────────
INSPECTEURS = ['Martin L.', 'Sophie D.', 'Ahmed K.']
ACT_PROFILES = {
    'Direction et services d\'appui': {'base': 84, 'vol': 4},
    'Boucherie':                      {'base': 72, 'vol': 8},
    'Charcuterie, rôtisserie, traiteur sans fabrication': {'base': 70, 'vol': 7},
    'Fromage/Crémerie':               {'base': 80, 'vol': 5},
    'Atelier traiteur':               {'base': 75, 'vol': 6},
    'Restauration':                   {'base': 67, 'vol': 9},
    'Marée':                          {'base': 71, 'vol': 8},
    'Boulangerie viennoiserie':        {'base': 83, 'vol': 5},
    'Pâtisserie viennoiserie':         {'base': 78, 'vol': 5},
    'Fruits et légumes':              {'base': 74, 'vol': 7},
    'Produits industriels libre-service': {'base': 90, 'vol': 3},
    'PGC alimentaires':               {'base': 88, 'vol': 3},
    'Autre':                          {'base': 73, 'vol': 6},
}

SCORE_VALS = {'A': 100, 'B': 66, 'C': 33, 'D': 0, 'S/O': None, 'N/E': None}

COMMENTAIRES_C = [
    'Température légèrement hors limite, ajustement en cours',
    'Étiquetage incomplet sur 2 références',
    'Nettoyage insuffisant constaté sur plan de travail',
    'DLC dépassée sur 1 produit retiré immédiatement',
    'Procédure non suivie — rappel effectué',
    'Équipement en attente de maintenance',
    'Formation insuffisante observée chez opérateur',
    'Traces de souillures sur matériel contact aliments',
]
COMMENTAIRES_D = [
    'Non-conformité grave — action corrective immédiate déclenchée',
    'Produits retirés de la vente — responsable alerté',
    'Procédure totalement absente — mise en place urgente',
    'Risque sanitaire identifié — zone isolée',
]
COMMENTAIRES_KO = [
    'KO déclenché — direction informée — action corrective sous 24h',
    'Rupture constatée — produits retirés — traçabilité vérifiée',
    'KO confirmé — inspection complémentaire planifiée',
]

ACTIONS_TEMPLATES = {
    'KO': [
        'Vérifier et corriger immédiatement la non-conformité',
        'Isoler les produits concernés et tracer le retrait',
        'Former les opérateurs sur la procédure associée',
        'Planifier une inspection de suivi sous 48h',
    ],
    'D': [
        'Mettre en place la procédure manquante',
        'Nettoyer et désinfecter la zone concernée',
        'Contrôler les températures toutes les 2h',
    ],
    'C': [
        'Rappeler la procédure à l\'équipe',
        'Vérifier les DLC en début de journée',
    ]
}

random.seed(42)
start = date(2025, 3, 17)

insp_id = 0
for day_i in range(61):
    d = start + timedelta(day_i)
    if d.weekday() == 6:  # skip Sundays
        continue

    insp_id += 1
    inspecteur = random.choice(INSPECTEURS)

    # Drift: scores slowly improve over time
    drift = day_i * 0.03

    resultats = []
    scores_by_act = {}
    ko_count = 0
    alerte_count = 0

    for item in items_flat:
        act = item['activite']
        prof = ACT_PROFILES.get(act, {'base': 75, 'vol': 6})
        base = min(95, prof['base'] + drift)

        # Notation probabilities based on base score
        r = random.random() * 100
        if item['type'] == 'KO':
            # KO items: mostly A, rare D
            if r < 2.5:   nota = 'D'
            elif r < 6:   nota = 'C'
            elif r < 14:  nota = 'B'
            else:          nota = 'A'
        elif item['type'] == 'S/O':
            nota = 'S/O'
        elif item['type'] == 'Mesure':
            nota = 'N/E' if random.random() < 0.1 else 'A'
        else:
            vol = prof['vol']
            if r < max(1, (100 - base) * 0.4):   nota = 'D'
            elif r < max(4, (100 - base) * 1.2): nota = 'C'
            elif r < max(12, (100 - base) * 2.8): nota = 'B'
            else:                                   nota = 'A'

        # Weekly pattern: Mondays slightly worse
        if d.weekday() == 0 and nota == 'B' and random.random() < 0.3:
            nota = 'C'

        commentaire = None
        if nota == 'C':
            commentaire = random.choice(COMMENTAIRES_C) if random.random() < 0.6 else None
        elif nota == 'D':
            commentaire = random.choice(COMMENTAIRES_D)
        elif nota in ('A', 'B') and item['type'] == 'KO':
            pass
        elif nota == 'D' and item['type'] == 'KO':
            commentaire = random.choice(COMMENTAIRES_KO)
            ko_count += 1
        elif nota == 'D' and item['type'] == 'Alerte':
            alerte_count += 1

        if item['type'] == 'KO' and nota == 'D':
            ko_count += 1
        if item['type'] == 'Alerte' and nota in ('C', 'D'):
            alerte_count += 1

        resultats.append((
            insp_id, act, item['etape'], item['num'],
            item['label'], item['type'], nota, commentaire
        ))

        v = SCORE_VALS.get(nota)
        if v is not None:
            scores_by_act.setdefault(act, []).append(v)

    # Global score
    all_scores = [s for lst in scores_by_act.values() for s in lst]
    score_global = round(sum(all_scores) / len(all_scores), 1) if all_scores else 0

    c.execute("""INSERT INTO inspections (id,date,magasin,inspecteur,statut,score_global,nb_ko,nb_alertes)
                 VALUES (?,?,?,?,?,?,?,?)""",
              (insp_id, d.isoformat(), 'Magasin Principal', inspecteur,
               'terminee', score_global, ko_count, alerte_count))

    c.executemany("""INSERT INTO resultats
                     (inspection_id,activite,etape,item_num,item_label,item_type,notation,commentaire)
                     VALUES (?,?,?,?,?,?,?,?)""", resultats)

    # Create alertes_ko for KO/D items
    for r_data in resultats:
        _, act, etape, num, label, itype, nota, comm = r_data
        if (itype == 'KO' and nota == 'D') or (itype == 'Alerte' and nota in ('C','D')):
            statut = 'resolue' if random.random() < 0.65 else 'ouverte'
            date_res = (d + timedelta(random.randint(1,5))).isoformat() if statut == 'resolue' else None
            c.execute("""INSERT INTO alertes_ko
                         (inspection_id,date,activite,etape,item_num,item_label,gravite,statut,commentaire,date_resolution)
                         VALUES (?,?,?,?,?,?,?,?,?,?)""",
                      (insp_id, d.isoformat(), act, etape, num, label,
                       itype, statut, comm, date_res))
            alerte_id = c.lastrowid
            # Action corrective
            actions = ACTIONS_TEMPLATES.get(nota if nota == 'KO' else nota, ACTIONS_TEMPLATES['C'])
            for action_desc in random.sample(actions, min(2, len(actions))):
                prio = 'urgente' if itype == 'KO' else 'normale'
                stat = 'realisee' if statut == 'resolue' else random.choice(['planifiee','en_cours'])
                d_ech = (d + timedelta(random.randint(1,3))).isoformat()
                d_real = date_res if stat == 'realisee' else None
                c.execute("""INSERT INTO actions_correctives
                             (alerte_id,description,responsable,priorite,statut,date_echeance,date_realisation)
                             VALUES (?,?,?,?,?,?,?)""",
                          (alerte_id, action_desc, inspecteur, prio, stat, d_ech, d_real))

conn.commit()

# Stats
print(f"Inspections: {c.execute('SELECT COUNT(*) FROM inspections').fetchone()[0]}")
print(f"Résultats:   {c.execute('SELECT COUNT(*) FROM resultats').fetchone()[0]}")
print(f"Alertes/KO:  {c.execute('SELECT COUNT(*) FROM alertes_ko').fetchone()[0]}")
print(f"Actions:     {c.execute('SELECT COUNT(*) FROM actions_correctives').fetchone()[0]}")
print(f"Score moyen: {c.execute('SELECT ROUND(AVG(score_global),1) FROM inspections').fetchone()[0]}")
print(f"KO total:    {c.execute('SELECT SUM(nb_ko) FROM inspections').fetchone()[0]}")

conn.close()
print("DB générée:", DB)
