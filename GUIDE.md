# 🧘 PostureAI V2 — Guide complet A → Z

PostureAI V2 est un outil local de **bien-être / ergonomie au poste de travail**.
Ce n'est **pas un dispositif médical** et ne remplace pas l'avis d'un
professionnel de santé (kiné, médecin) en cas de douleur persistante.

---

## 0. Ce qui a changé depuis la V1

| | V1 | V2 / V2.1 |
|---|---|---|
| Détection | 1 seul indicateur (CVA oreille/épaule), nécessitait une vue de profil | Score 0-100 combinant 4 indicateurs, **pensé pour une webcam quasi frontale et un utilisateur assis** — les hanches ne sont jamais requises |
| Seuils | Fixes, identiques pour tout le monde | **Calibration personnelle assise** (5-10s) → seuils relatifs à TA posture de référence |
| Stabilité | Un mouvement brusque = changement instantané de statut | Lissage + durée minimale avant tout changement de statut |
| Alertes | Bip uniquement si la fenêtre est au premier plan | Overlay toujours au-dessus de toutes les fenêtres + notification Windows + son natif + icône system tray |
| Historique | Rapport PNG à la fin de chaque session | Base SQLite + **dashboard web local**, focalisé sur la journée en cours (courbe + répartition + conseils) |
| Son | `simpleaudio` (parfois instable à l'installation) | `winsound`, natif Windows, zéro dépendance externe |
| Fenêtre | OpenCV simple | Overlay dark/moderne (rendu texte via Pillow, accents corrects), score animé, mini-courbe de tendance en direct, mini-barres par métrique, icônes vectorielles, liste des problèmes détectés, badges, messages de motivation, Smart Break, plein écran (F11), mode minimal (m) |
| Dashboard | — | Centré sur AUJOURD'HUI (pas d'historique multi-jours) : courbe du score en direct, anneau de répartition, conseils du jour. Se met à jour **en direct** pendant la session, indicateur "EN DIRECT", rafraîchissement automatique |

> **V2.1** : la détection a été recalibrée pour le cas d'usage réel le plus
> courant — développeur / gamer / étudiant / télétravailleur **assis**
> devant son écran, webcam intégrée en haut de l'écran. Il n'est plus
> nécessaire de montrer les hanches, se lever ou se placer de profil.

---

## 1. Comprendre le score de posture (méthodologie)

Le score (0-100) n'est **pas** un seul angle, mais une combinaison pondérée
de 4 métriques, chacune comparée à **ta propre calibration**, calculées à
partir des landmarks visibles sur une webcam quasi frontale (nez, yeux,
oreilles, épaules) — **les hanches ne sont jamais requises** :

1. **Forward Head (40%)** — tête projetée vers l'avant / rapprochement
   progressif de l'écran. Combine 3 signaux : décalage oreille-ou-œil/épaule
   en 2D (normalisé par la largeur des épaules, pas par les hanches), la
   profondeur 3D oreille/épaule ("world landmarks", toujours disponible
   même sans hanches visibles), et la largeur des épaules à l'écran
   (grandit quand tu te rapproches de la caméra).
2. **Trunk lean / Slouch (25%)** — affaissement du buste. Signal principal :
   ratio "longueur de cou" (distance verticale épaule → oreille/œil,
   normalisée par la largeur des épaules) — fonctionne sans les hanches.
   Si les hanches SONT visibles (webcam plus reculée), elles apportent un
   signal bonus, jamais obligatoire.
3. **Neck tilt (20%)** — la tête est-elle inclinée par rapport à l'axe
   épaules → nez ?
4. **Shoulder asymmetry (15%)** — combine la différence de hauteur des
   épaules ET la différence de hauteur oreilles/yeux gauche-droite, pour
   détecter aussi bien des épaules déséquilibrées qu'une tête penchée d'un
   côté (posture asymétrique, inclinaison latérale).

Formule du score global :
```
score = 0.40 * forward_head_score
      + 0.25 * trunk_lean_score
      + 0.20 * neck_tilt_score
      + 0.15 * shoulder_asym_score
```

Chaque métrique est convertie en sous-score 0-100 selon son écart à ta
baseline personnelle (calibrée au démarrage, assis), avec une tolérance
dérivée de la variabilité naturelle observée pendant la calibration. Le
score global est la moyenne pondérée des 4 sous-scores, lissée dans le
temps (moyenne mobile exponentielle) pour éviter les à-coups.

Classification : **BONNE** (≥ 80), **LIMITE** (60-79), **MAUVAISE** (< 60).
Un changement de statut ne devient officiel qu'après ~1,3s de persistance
(anti-clignotement). Le HUD affiche aussi une liste "⚠ Problèmes détectés"
listant explicitement les métriques en dessous du seuil "LIMITE".

> Pourquoi une combinaison de signaux ? Un seul indicateur "correct" peut
> masquer un buste affaissé ou des épaules asymétriques. En combinant
> plusieurs signaux et en les rapportant à TA posture de référence,
> PostureAI V2 évite qu'une posture volontairement inconfortable soit
> classée "bonne" uniquement parce qu'un seul angle semblait correct.

---

## 2. Installation

### Prérequis
- Python 3.11 (Windows recommandé pour les notifications/tray/son natifs).
- Une webcam (PC intégrée/USB) ou un téléphone en caméra IP (voir §5).

### Étapes

```bat
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

Ou plus simplement, double-clique sur `run.bat` : il crée le venv, installe
les dépendances et lance l'application.

---

## 3. Premier lancement — calibration

1. **Assieds-toi normalement** devant ton écran, dans ta posture de travail
   habituelle, webcam en face de toi (webcam intégrée en haut de l'écran =
   configuration idéale). Pas besoin de te lever, de te mettre de profil ou
   de reculer : seuls le visage, les épaules (et parfois le haut du torse)
   doivent être visibles.
2. Reste immobile ~8 secondes en bonne posture assise : une barre de
   progression et un minuteur s'affichent.
3. Si le message "repositionne-toi" apparaît, corrige ton cadrage
   (visibilité du visage/épaules, distance à la caméra) puis reste stable
   jusqu'à la fin du minuteur.
4. Une fois la calibration terminée, le score en temps réel + les
   mini-barres par métrique + la liste des problèmes détectés apparaissent.

Tu peux recalibrer à tout moment avec la touche **`c`** (utile si tu changes
de chaise, d'éclairage, ou de position de caméra).

---

## 4. Fonctionnement en arrière-plan

- Réduis la fenêtre webcam : une icône apparaît dans la barre système
  (system tray) avec un menu **Pause / Reprendre / Ouvrir le dashboard /
  Quitter**.
- Si une mauvaise posture persiste au-delà du délai de grâce, une petite
  bulle **toujours au-dessus des autres fenêtres** apparaît en haut à
  droite de l'écran ("⚠️ Redresse-toi — ta posture se dégrade"), accompagnée
  d'une notification Windows et d'un son système. Elle disparaît
  automatiquement dès que tu te redresses.
- Un cooldown évite le spam d'alertes (au plus une toutes les 20s par
  défaut, ajustable dans `posture_ai/config.py`).

---

## 5. Utiliser ton téléphone comme caméra

### Option A — Android : app *IP Webcam*
1. Installe **"IP Webcam"** (Pavel Khlebovich) depuis le Play Store.
2. Ouvre l'app → **"Start server"**.
3. Téléphone et PC sur le **même réseau Wi-Fi**.
4. Note l'URL affichée, ex. `http://192.168.1.42:8080`.
5. Dans `posture_ai/config.py`, remplace :
   `CAMERA_SOURCE = "http://192.168.1.42:8080/video"`
6. Relance `python main.py`.

### Option B — iOS / multiplateforme : *DroidCam* ou *Iriun Webcam*
1. Installe l'app sur le téléphone **et** le logiciel correspondant sur PC.
2. Connecte les deux au même réseau (ou câble USB selon l'app).
3. Une webcam virtuelle apparaît, reconnue directement par le PC.
4. Laisse `CAMERA_SOURCE = 0` (ou essaie `1`, `2`…).

---

## 6. Dashboard local

Le serveur du dashboard démarre **automatiquement dès le lancement de
PostureAI** (plus besoin de cliquer sur quoi que ce soit pour qu'il tourne).
Pour l'ouvrir dans le navigateur :

- touche **`d`** dans la fenêtre webcam, ou
- menu du system tray → **"Ouvrir le dashboard"**, ou
- directement à l'adresse : **http://127.0.0.1:5057**

Le dashboard est volontairement centré sur **la journée en cours** (pas
d'historique multi-jours à parcourir) :

- score du jour, % de bonne posture, alertes, streak de jours consécutifs
- **courbe du score d'aujourd'hui** : chaque point est une mesure réelle de
  la webcam, colorée selon le statut du moment (Bonne / Limite / Mauvaise) —
  le même principe que l'ancien rapport de fin de session
- **anneau de répartition** de la journée (% Bonne/Limite/Mauvaise)
- objectif quotidien (minutes en bonne posture visées) et conseil du jour,
  basé sur ce qui s'est passé aujourd'hui
- meilleure session du jour

**Mise à jour en direct** : pendant que tu utilises PostureAI, la session en
cours écrit ses statistiques en base toutes les ~3 secondes (et pas
seulement à la fermeture). Le dashboard affiche un badge **"EN DIRECT"** et
se rafraîchit automatiquement (résumé toutes les 4s, courbe/anneau toutes
les 6s) — pas besoin de recharger la page.

Toutes les données restent **en local** dans `data/postureai.db` (SQLite).
Aucune image ni vidéo n'est jamais enregistrée.

> Note technique : les deux graphiques (courbe + anneau) sont générés
> **côté serveur avec matplotlib** et servis comme de simples images PNG
> (`/api/today_evolution.png`, `/api/today_donut.png`). Contrairement à
> une librairie JS chargée depuis un CDN, ceci fonctionne **entièrement
> hors ligne**, sans dépendre d'une connexion internet ni être bloqué par
> un pare-feu d'entreprise.

---

## 7. Raccourcis clavier (fenêtre webcam active)

| Touche | Action |
|---|---|
| `q` / `ESC` | Quitter et clôturer la session (résumé + écriture en base) |
| `c` | Relancer une calibration |
| `p` | Mettre en pause / reprendre |
| `F11` (ou `f`) | Basculer le mode plein écran — utile pour une démo |
| `m` | Basculer le mode minimal (HUD réduit : juste score + statut) |
| `d` | Ouvrir le dashboard local dans le navigateur |

---

## 8. Dépannage

| Symptôme | Cause probable | Solution |
|---|---|---|
| `Impossible d'ouvrir la source vidéo` | Mauvais index de caméra | Essaie `CAMERA_SOURCE = 1` ou `2` dans `posture_ai/config.py` |
| "Repositionne-toi" en continu | Cadrage trop large/proche, mauvais éclairage | Ajoute de la lumière, ajuste la distance à la caméra |
| Pas de notification Windows | `plyer` indisponible sur la config | L'app continue de fonctionner (overlay + son restent actifs) |
| Pas d'icône system tray | `pystray` non installé/pris en charge | Vérifie `pip install -r requirements.txt` ; l'app reste utilisable sans tray |
| Aucun son | Volume système coupé | L'alerte utilise le son système Windows ("Exclamation") |
| `ModuleNotFoundError` | venv non activé | `venv\Scripts\activate` puis `pip install -r requirements.txt` |

---

## 9. Structure du projet

```
PostureAI_V2/
├── main.py                      # point d'entrée
├── requirements.txt
├── run.bat
├── README.md / GUIDE.md
├── data/                        # base SQLite (créée automatiquement)
├── output/                      # dossier de sortie (rapports optionnels)
└── posture_ai/
    ├── config.py                # toute la configuration ajustable
    ├── posture_engine.py        # calibration + scoring multi-métriques
    ├── camera_worker.py         # boucle OpenCV + UI moderne
    ├── session_stats.py         # agrégation, Smart Break, streaks
    ├── database.py              # persistance SQLite
    ├── alerts.py                # overlay always-on-top + notifications
    ├── sound_utils.py           # son natif Windows (winsound)
    ├── tray_icon.py             # icône system tray (pystray)
    ├── app_controller.py        # orchestration des threads
    └── dashboard/
        ├── server.py            # API Flask (JSON + routes PNG)
        ├── charts.py            # génération matplotlib des graphiques
        └── templates/index.html # UI dark/moderne (images <img>, pas de JS externe)
```

Bon prototypage — et bonne posture ! 🧘‍♂️
