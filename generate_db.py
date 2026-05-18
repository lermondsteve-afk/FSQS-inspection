"""
generate_db.py — Crée et initialise la base de données FSQS
Lancer une seule fois : python generate_db.py
"""
import sqlite3
import os
from datetime import date, timedelta
import random

DB_PATH = os.path.join(os.path.dirname(__file__), 'inspections.db')

def create_db():
    # Supprime l'ancienne DB si elle existe
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
        print("Ancienne DB supprimée.")

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # ── Créer les tables ────────────────────────────────────────────────────
    c.executescript("""
    CREATE TABLE IF NOT EXISTS inspections (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT NOT NULL,
        inspecteur TEXT,
        score_global REAL DEFAULT 0,
        nb_ko INTEGER DEFAULT 0,
        nb_alertes INTEGER DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS resultats (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        inspection_id INTEGER,
        item_num TEXT,
        item_label TEXT,
        activite TEXT,
        etape TEXT,
        type TEXT,
        notation TEXT,
        commentaire TEXT,
        FOREIGN KEY(inspection_id) REFERENCES inspections(id)
    );

    CREATE TABLE IF NOT EXISTS alertes_ko (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        inspection_id INTEGER,
        item_num TEXT,
        item_label TEXT,
        activite TEXT,
        etape TEXT,
        gravite TEXT,
        statut TEXT DEFAULT 'ouverte',
        date TEXT,
        FOREIGN KEY(inspection_id) REFERENCES inspections(id)
    );

    CREATE TABLE IF NOT EXISTS actions_correctives (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        description TEXT,
        activite TEXT,
        responsable TEXT,
        priorite TEXT DEFAULT 'normale',
        statut TEXT DEFAULT 'en_cours',
        date TEXT,
        date_echeance TEXT
    );
    """)

    print("Tables créées.")

    # ── Insérer des données de démonstration ────────────────────────────────
    import json
    with open('items.json', encoding='utf-8') as f:
        items = json.load(f)

    inspecteurs = ['Martin Dupont', 'Sophie Leclerc', 'Ahmed Benali']
    activites = list(set(i['activite'] for i in items))

    today = date.today()

    for day_offset in range(60, 0, -1):
        inspection_date = (today - timedelta(days=day_offset)).isoformat()

        # 1 inspection tous les 3 jours environ
        if day_offset % 3 != 0:
            continue

        inspecteur = random.choice(inspecteurs)
        notations = ['A', 'A', 'A', 'B', 'B', 'C', 'D', 'S/O']
        resultats_inseres = []
        nb_ko = 0
        nb_alertes = 0
        scores = []

        for item in items:
            nota = random.choice(notations)
            score_map = {'A': 100, 'B': 66, 'C': 33, 'D': 0}
            if nota not in ('S/O', 'N/E'):
                scores.append(score_map[nota])

            resultats_inseres.append((
                item['num'], item['label'], item['activite'],
                item.get('etape', ''), item['type'], nota, ''
            ))

            # Compter KO et alertes
            if item['type'] == 'KO' and nota == 'D':
                nb_ko += 1
            if item['type'] == 'Alerte' and nota in ('C', 'D'):
                nb_alertes += 1

        score_global = round(sum(scores) / len(scores), 1) if scores else 0

        # Insérer inspection
        cur = conn.execute(
            "INSERT INTO inspections (date, inspecteur, score_global, nb_ko, nb_alertes) VALUES (?,?,?,?,?)",
            (inspection_date, inspecteur, score_global, nb_ko, nb_alertes)
        )
        inspection_id = cur.lastrowid

        # Insérer résultats
        for r in resultats_inseres:
            conn.execute(
                "INSERT INTO resultats (inspection_id, item_num, item_label, activite, etape, type, notation, commentaire) VALUES (?,?,?,?,?,?,?,?)",
                (inspection_id,) + r
            )

        # Insérer alertes_ko pour les mauvaises notations
        for item in items:
            nota = random.choice(['A', 'A', 'B', 'C', 'D'])
            if item['type'] == 'KO' and nota == 'D':
                statut = random.choice(['ouverte', 'ouverte', 'resolue'])
                conn.execute(
                    "INSERT INTO alertes_ko (inspection_id, item_num, item_label, activite, etape, gravite, statut, date) VALUES (?,?,?,?,?,?,?,?)",
                    (inspection_id, item['num'], item['label'], item['activite'],
                     item.get('etape',''), 'KO', statut, inspection_date)
                )
            elif item['type'] == 'Alerte' and nota in ('C', 'D'):
                statut = random.choice(['ouverte', 'resolue'])
                conn.execute(
                    "INSERT INTO alertes_ko (inspection_id, item_num, item_label, activite, etape, gravite, statut, date) VALUES (?,?,?,?,?,?,?,?)",
                    (inspection_id, item['num'], item['label'], item['activite'],
                     item.get('etape',''), 'Alerte', statut, inspection_date)
                )

    print("Inspections et résultats insérés.")

    # ── Actions correctives de démonstration ────────────────────────────────
    actions = [
        ('Renforcer le nettoyage des surfaces de découpe', 'Boucherie', 'Martin Dupont', 'urgente', 'en_cours'),
        ('Vérifier les thermomètres zone marée', 'Marée', 'Sophie Leclerc', 'urgente', 'en_cours'),
        ('Former les opérateurs au lavage des mains', 'Direction et services d\'appui', 'Ahmed Benali', 'normale', 'planifiee'),
        ('Réviser le protocole de décontamination végétaux', 'Fruits et légumes', 'Martin Dupont', 'normale', 'en_cours'),
        ('Mise à jour des durées de vie Charcuterie', 'Charcuterie, rôtisserie, traiteur sans fabrication', 'Sophie Leclerc', 'normale', 'realisee'),
        ('Contrôle DLC produits libre-service', 'Produits industriels libre-service', 'Ahmed Benali', 'urgente', 'en_cours'),
    ]

    for i, (desc, act, resp, prio, statut) in enumerate(actions):
        action_date = (today - timedelta(days=random.randint(1, 20))).isoformat()
        echeance = (today + timedelta(days=random.randint(3, 14))).isoformat()
        conn.execute(
            "INSERT INTO actions_correctives (description, activite, responsable, priorite, statut, date, date_echeance) VALUES (?,?,?,?,?,?,?)",
            (desc, act, resp, prio, statut, action_date, echeance)
        )

    print("Actions correctives insérées.")

    conn.commit()
    conn.close()
    print(f"\n✅ Base de données créée avec succès : {DB_PATH}")
    print("Vous pouvez maintenant lancer : gunicorn app:app")

if __name__ == '__main__':
    create_db()
