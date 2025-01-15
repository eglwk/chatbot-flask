# Definition der Stufen für die Haupteffekte
factors = {
    "Verbal": ["High", "Low", "No"],
    "Antwortlatenz": ["3 Sek.", "1 Sek."],
    "Emoji/Mimi": ["Mit Emoji", "Ohne Emoji"],
    "Blinking Dots": ["Mit Blinking Dots", "Ohne Blinking Dots"],
    "Identity": [
        "Low Anthropomorphism - Female",
        "Low Anthropomorphism - Male",
        "Middle Anthropomorphism - Female",
        "Middle Anthropomorphism - Male",
        "High Anthropomorphism - Female",
        "High Anthropomorphism - Male",
        "No Anthropomorphism"
    ]
}

import pandas as pd

# Erstellen eines DataFrames mit den Haupteffekten
main_effects = []
for factor, levels in factors.items():
    for level in levels:
        main_effects.append({"Faktor": factor, "Stufe": level})

df_main_effects = pd.DataFrame(main_effects)

# Datei speichern
file_path_main_effects = "/mnt/data/Pretest_Haupteffekte.xlsx"
df_main_effects.to_excel(file_path_main_effects, index=False)

file_path_main_effects
