"""Données de référence Tekken 8 : personnages et rangs.

Ajoute ici les nouveaux personnages DLC au fur et à mesure de leur sortie.
"""

CHARACTERS = sorted([
    # Roster de base
    "Alisa", "Asuka", "Azucena", "Bryan", "Claudio", "Devil Jin", "Dragunov",
    "Feng", "Hwoarang", "Jack-8", "Jin", "Jun", "Kazuya", "King", "Kuma",
    "Lars", "Law", "Lee", "Leo", "Leroy", "Lili", "Nina", "Panda", "Paul",
    "Raven", "Reina", "Shaheen", "Steve", "Victor", "Xiaoyu", "Yoshimitsu",
    "Zafina",
    # DLC
    "Eddy", "Lidia", "Heihachi", "Clive", "Anna", "Fahkumram", "Armor King",
    "Miary Zo", "Kunimitsu", "Bob", "Roger",
])

# Du plus bas au plus haut : l'index sert de "niveau" pour les graphiques.
RANKS = [
    "Beginner", "1st Dan", "2nd Dan", "Fighter", "Strategist", "Combatant",
    "Brawler", "Ranger", "Cavalry", "Warrior", "Assailant", "Dominator",
    "Vanquisher", "Destroyer", "Eliminator", "Garyu", "Shinryu", "Tenryu",
    "Mighty Ruler", "Flame Ruler", "Battle Ruler", "Fujin", "Raijin", "Kishin",
    "Bushin", "Tekken King", "Tekken Emperor", "Tekken God",
    "Tekken God Supreme", "God of Destruction",
    "God of Destruction I", "God of Destruction II", "God of Destruction III",
    "God of Destruction IV", "God of Destruction V", "God of Destruction VI",
    "God of Destruction VII", "God of Destruction ∞",
]


def rank_level(rank):
    """Retourne la position du rang (0 = Beginner), ou None si inconnu."""
    try:
        return RANKS.index(rank)
    except ValueError:
        return None
