# FSQS Inspection Pro — Guide de déploiement

## Structure du projet
```
fsqs_app/
├── app.py                  # Backend Flask + API
├── generate_db.py          # Génère la base de données simulée
├── requirements.txt        # Dépendances Python
├── Procfile                # Configuration Render.com
├── data/
│   ├── inspections.db      # Base SQLite (2 mois de données)
│   └── items.json          # Items FSQS filtrés
└── templates/
    └── index.html          # Dashboard complet
```

## Déploiement sur Render.com (GRATUIT)

### Étape 1 — Préparer GitHub
1. Créez un compte GitHub (github.com)
2. Créez un nouveau dépôt privé : "fsqs-inspection"
3. Uploadez tous les fichiers du dossier fsqs_app/

### Étape 2 — Déployer sur Render
1. Allez sur render.com → "New" → "Web Service"
2. Connectez votre compte GitHub
3. Sélectionnez le dépôt "fsqs-inspection"
4. Configurez :
   - Name: fsqs-inspection-pro
   - Runtime: Python 3
   - Build Command: pip install -r requirements.txt
   - Start Command: gunicorn app:app --bind 0.0.0.0:$PORT
5. Ajoutez la variable d'environnement :
   - Key: ANTHROPIC_API_KEY
   - Value: votre clé depuis console.anthropic.com
6. Cliquez "Create Web Service"
→ Votre app sera live sur https://fsqs-inspection-pro.onrender.com

### Étape 3 — Obtenir la clé API Anthropic
1. Allez sur console.anthropic.com
2. Créez un compte
3. "API Keys" → "Create Key"
4. Copiez la clé (commence par "sk-ant-...")
→ Collez-la dans la variable ANTHROPIC_API_KEY sur Render

## Utilisation quotidienne

### Saisie des données
1. Ouvrez l'app → "Saisie inspection"
2. Sélectionnez la date et entrez le nom de l'inspecteur
3. Pour chaque item : cliquez A / B / C / D
4. Ajoutez un commentaire si notation C ou D
5. "Enregistrer inspection" → données sauvegardées en base

### Analyse IA
1. Onglet "Analyse IA"
2. Choisissez un bouton de requête prédéfinie OU tapez votre question
3. La réponse s'affiche en quelques secondes

### Exemples de questions IA
- "Quels sont les 5 items les plus souvent non-conformes ?"
- "Compare les scores de cette semaine vs la semaine dernière"
- "Génère le rapport mensuel complet"
- "Quelles activités sont en dégradation ?"
- "Plan d'action correctif prioritaire pour demain"

## Brancher vos vraies données (semaine prochaine)

Remplacez generate_db.py par un script de chargement depuis votre fichier Excel :

```python
import pandas as pd, sqlite3
df = pd.read_excel('votre_fichier.xlsx')
conn = sqlite3.connect('data/inspections.db')
# Insérez vos données dans la table 'resultats'
```

## Coûts estimés
- Hébergement Render (gratuit) : 0€/mois
- API Anthropic (~10 analyses/jour) : ~2-5€/mois
- Domaine custom (optionnel) : ~10€/an
```
