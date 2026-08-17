import json, sys

sys.stdout.reconfigure(encoding='utf-8')

config_path = r"D:\mycroft-phoenix\audio_config.json"

# Lecture du fichier en binaire pour éviter les soucis d'encodage
with open(config_path, "rb") as f:
    raw = f.read()

# Décodage avec remplacement d'erreurs
text = raw.decode("utf-8", errors="replace")
cfg = json.loads(text)

# Nouveau périphérique (index 6, nom 'Haut-parleurs (SB Live! 24-bit)')
nouveau_idx = 6
nouveau_nom = "Haut-parleurs (SB Live! 24-bit)"

cfg["output"]["device_index"] = nouveau_idx
cfg["output"]["name"] = nouveau_nom

# Réécriture du fichier
with open(config_path, "w", encoding="utf-8") as f:
    # On écrit proprement en UTF-8
    f.write(json.dumps(cfg, indent=2, ensure_ascii=False))

# Confirmation simple (pas de print JSON)
print("✅ Configuration audio mise à jour avec succès.")
print(f"   - device_index : {nouveau_idx}")
print(f"   - name        : {nouveau_nom}")
print("🔊 Redémarre voice_loop.py pour prendre effet.")