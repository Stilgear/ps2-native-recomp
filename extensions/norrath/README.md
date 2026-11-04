# Extensions Spécifiques : Champions of Norrath (SLES_523.25)

Ce dossier documente les améliorations natives apportées au code C++ généré de *Champions of Norrath* (`generated/norrath/`), afin de les distinguer du moteur générique `ps2-native-recomp`.

## 1. Widescreen 16:9 Non-Déformant (Hor+)
- **[`generated/norrath/unit_0016.cpp`](../../generated/norrath/unit_0016.cpp)** (`func_0018E670`) :
  - Correction du ratio d'aspect caméra 3D (`aspect * 0.75f` en mode 16:9) pour élargir le champ de vision horizontal sans écraser ni étirer les personnages et l'interface.
- **[`generated/norrath/unit_001E.cpp`](../../generated/norrath/unit_001E.cpp)** (`func_001F3E68`) :
  - Ajustement du frustum de culling horizontal pour éviter la disparition prématurée des objets sur les bords gauche/droite de l'écran 16:9.

## 2. Sélecteur de Résolution HD Intégré au Menu Options du Jeu
- **[`generated/norrath/unit_0020.cpp`](../../generated/norrath/unit_0020.cpp)** : Synchronisation de l'échelle de rendu (`ps2::video_scale` / `ps2::set_video_scale`) au démarrage et lors des changements d'options.
- **[`generated/norrath/unit_0033.cpp`](../../generated/norrath/unit_0033.cpp)** & **[`generated/norrath/unit_0034.cpp`](../../generated/norrath/unit_0034.cpp)** : Ajout de la ligne **« Resolution / Résolution / Auflösung / Resolución / Risoluzione »** (`480p (Original)`, `720p (HD)`, `1080p (Full HD)`, `4K (UHD)`) directement dans le menu Options natif du jeu.
- **[`generated/norrath/unit_0025.cpp`](../../generated/norrath/unit_0025.cpp)** & **[`generated/norrath/unit_0026.cpp`](../../generated/norrath/unit_0026.cpp)** : Ajustement de la hauteur du cadre de fond du menu Options pour accueillir la nouvelle ligne.

## 3. Extraction ISO & Empaquetage Sans-ISO
Pour extraire `disc.iso` (DVD-9 double couche) et créer un dossier de jeu autonome :
```bash
# 1. Extraire les 1131 fichiers (Couche 0 + Couche 1) et le manifeste LBA :
python3 scripts/extract_disc.py extract games/norrath/disc.iso games/norrath/disc_files

# 2. Empaqueter le jeu natif autonome dans dist/ChampionsOfNorrath :
python3 scripts/package_game.py \
  --binary games/norrath/champions-of-norrath \
  --elf games/norrath/disc_files/layer0/SLES_523.25 \
  --disc games/norrath/disc_files \
  --keys keys.ini \
  --out dist/ChampionsOfNorrath
```
