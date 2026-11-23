# Modèle de configuration locale.
#
# Copie ce fichier dans instance/config.py puis complète-le :
#     mkdir -p instance && cp config.example.py instance/config.py
#
# Le dossier instance/ n'est jamais commité : tes clés y sont en sécurité.

# Clé API ewgf.gg (facultative) : sert à récupérer tes rangs Dan.
# À créer sur https://ewgf.gg : compte > Paramètres > onglet Developer. Elle commence par "ewgf_".
EWGF_API_KEY = ""

# Token API start.gg (facultatif) : active la rubrique Tournois.
# À créer sur https://www.start.gg : profil > Developer Settings > Create new token.
# Un seul token sert à tout le site ; chaque joueur lie ensuite son profil start.gg.
STARTGG_TOKEN = ""

# Rubriques « Matchs » et « Matchups » (liste des matchs, saisie manuelle, notes par
# matchup) : en pause pour l'instant. Mets True pour les réactiver.
# ENABLE_MATCHES_PAGES = False

# Clé qui signe les cookies (identification du joueur). Inutile de la définir :
# elle est générée automatiquement dans instance/secret_key au premier lancement.
# SECRET_KEY = ""
