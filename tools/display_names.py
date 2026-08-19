"""Internal txt index -> in-game display name for unique items.

uniqueitems.txt 'index' keys are string-table keys, not what the game
shows: the tooltip says "Lenymo", the txt says "Lenyms Cord". OCR matches
against what the SCREEN shows, so every generated repository file must use
display names. Names identical in both are not listed.
"""

UNIQUE_DISPLAY = {
    "Lenyms Cord": "Lenymo",
    "Kerke's Sanctuary": "Gerke's Sanctuary",
    "Vampiregaze": "Vampire Gaze",
    "Wartraveler": "War Traveler",
    "Wisp": "Wisp Projector",
    "Bonesob": "Bonesnap",
    "Whichwild String": "Witchwild String",
    "Maelstromwrath": "Maelstrom",
    "Cerebus": "Cerebus' Bite",
    "The Cat's Eye": "Cat's Eye",
    "Ironpelt": "Iron Pelt",
    "Radimant's Sphere": "Radament's Sphere",
    "Thudergod's Vigor": "Thundergod's Vigor",
    "The Reedeemer": "The Redeemer",
    "Deaths's Web": "Death's Web",
    "Pus Spiter": "Pus Spitter",
    "Que-Hegan's Wisdon": "Que-Hegan's Wisdom",
    "Valkiry Wing": "Valkyrie Wing",
    "Peasent Crown": "Peasant Crown",
    "Steel Carapice": "Steel Carapace",
    "Skin of the Flayerd One": "Skin of the Flayed One",
    "Eschuta's temper": "Eschuta's Temper",
    "The Generals Tan Do Li Ga": "The General's Tan Do Li Ga",
    "Griswolds Edge": "Griswold's Edge",
    "Bul Katho's Wedding Band": "Bul-Kathos' Wedding Band",
    "Blinkbats Form": "Blinkbat's Form",
    "Dimoaks Hew": "Dimoak's Hew",
    "Culwens Point": "Culwen's Point",
    "Kinemils Awl": "Kinemil's Awl",
    "Rixots Keen": "Rixot's Keen",
    "Mosers Blessed Circle": "Moser's Blessed Circle",
    "Umes Lament": "Ume's Lament",
    "Victors Silk": "Victor's Silk",
    "The Atlantian": "The Atlantean",
    "The Chieftan": "The Chieftain",
    "Hell Forge Hammer": "Hellforge Hammer",
    "KhalimFlail": "Khalim's Flail",
    "SuperKhalimFlail": "Khalim's Will",
    "Fechmars Axe": "Fechmar's Axe",
    "Krintizs Skewer": "Krintiz's Skewer",
}


def display_name(index):
    return UNIQUE_DISPLAY.get(index, index)
