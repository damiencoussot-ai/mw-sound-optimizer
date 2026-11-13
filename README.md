<p align="center">
  <img src="assets/logo.png" width="160" alt="MW Sound Optimizer">
</p>

<h1 align="center">MW Sound Optimizer</h1>

<p align="center">
  Égaliseur et outils audio pour entendre mieux les pas dans <b>Call of Duty : Warzone / Modern Warfare</b>,
  avec des écouteurs. Pilote <b>Equalizer APO</b> et se connecte à <b>Voicemeeter</b>.
</p>

<p align="center">
  <a href="https://github.com/damiencoussot-ai/mw-sound-optimizer/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/damiencoussot-ai/mw-sound-optimizer/actions/workflows/ci.yml/badge.svg"></a>
  <img alt="Windows 10/11" src="https://img.shields.io/badge/Windows-10%20%7C%2011-0078D6">
  <img alt="Licence MIT" src="https://img.shields.io/badge/licence-MIT-green">
</p>

> Remplace `damiencoussot-ai/mw-sound-optimizer` dans les liens ci-dessus par le nom réel de ton dépôt.

## Ce que ça fait

- **Courbe d'égaliseur interactive** : 6 bandes, glisse les points (gain et fréquence), molette pour la finesse (Q).
- **Mode simple** : 4 profils en un clic (Compétitif, Équilibré, Pas extrême, Immersion) et un curseur de force.
- **Spectre en direct** de ta sortie audio, avec la zone des pas surlignée.
- **Outils** : largeur stéréo, coupe-explosions (passe-haut), balance, inversion gauche/droite, comparaison A/B, sons de test, mini HUD.
- **Auto Warzone** : l'EQ s'active quand le jeu tourne et se coupe quand il est fermé.
- **Raccourcis** : `Ctrl+Alt+F9` EQ on/off, `Ctrl+Alt+F10` preset suivant.
- **Voicemeeter** : détection de l'édition, VU-mètre du bus A1, lancer / afficher / redémarrer le moteur audio, EQ natif sur Banana et Potato.
- **Sortie Windows** : affichée en lecture seule. Le logiciel ne change **rien** dans les réglages son de Windows tant que tu n'actives pas « Modifier Windows : OUI ».

## Installation

1. Installe [Equalizer APO](https://sourceforge.net/projects/equalizerapo/), lance son *Configurator*, coche ta sortie audio (par exemple « Voicemeeter Input »), puis redémarre le PC.
2. Télécharge `MW_Sound_Optimizer.exe` depuis la page [Releases](../../releases/latest).
3. Lance-le. Pas d'installation, pas de droits administrateur.

Windows SmartScreen peut afficher un avertissement : l'exécutable n'est pas signé. « Informations complémentaires » puis « Exécuter quand même ».

## Utilisation avec Voicemeeter

| Édition | Que faire |
| --- | --- |
| **Standard** | Pas d'EQ intégré. Envoie le son du jeu vers « Voicemeeter Input », coche cette sortie dans le Configurator d'Equalizer APO, garde le mode **Equalizer APO**. |
| **Banana / Potato** | Mode **Voicemeeter natif** : l'EQ est envoyé aux bus A1 à A5 que tu coches. |

Le type de filtre et la conversion du Q pour le mode natif sont déduits de la documentation officielle de VB-Audio et n'ont pas été vérifiés sur Banana / Potato : contrôle le résultat dans la fenêtre EQ de Voicemeeter.

## Sécurité et jeu en ligne

- Le logiciel **ne lit pas, ne modifie pas et ne s'injecte pas dans le jeu**. Il lit seulement la liste des processus de Windows pour savoir si le jeu tourne.
- Il écrit un seul fichier dans le dossier d'Equalizer APO (`MW_optimizer.txt`) et ajoute une ligne `Include:` à `config.txt`.
- Aucune télémétrie, aucune connexion Internet.
- Réglages enregistrés dans `%APPDATA%\MWSoundOptimizer\settings.json`.

## Compiler soi-même

```powershell
py -m pip install -r requirements.txt -r requirements-dev.txt
./build.ps1
```

L'exécutable est créé dans `dist/`. Les tests :

```powershell
py -m unittest discover -s tests -v
```

Une release GitHub est construite automatiquement quand tu pousses un tag `vX.Y.Z` (voir `.github/workflows/release.yml`).

## Dépannage

| Problème | Piste |
| --- | --- |
| « Equalizer APO introuvable » | Installe Equalizer APO. |
| Aucun effet dans le jeu | La sortie utilisée n'est pas cochée dans le Configurator d'Equalizer APO. Le panneau « Sortie » indique la cible. |
| Effets trop forts | D'autres traitements (YouSound, HeSuVi, Peace) sont déjà actifs : ils se cumulent. Baisse la force de l'effet. |
| Son qui sature | Mets le niveau de sortie à 0 dB ou moins. |
| Spectre indisponible | Aucune sortie audio active, ou pilote sans capture de retour. |

## Avertissement

Projet indépendant, non affilié à Activision ni à Microsoft. *Call of Duty*, *Warzone* et *Modern Warfare* sont des marques de leurs propriétaires. Les logos fournis dans `assets/` sont originaux.

## Licence

[MIT](LICENSE)
