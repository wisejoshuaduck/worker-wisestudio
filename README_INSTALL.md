# Installation — worker YouTube (shorts + téléchargement MP4)

## 1. Déployer le worker Python
Dossier `worker-wisestudio/` → suivre `worker-wisestudio/README.md`
(Render ou Cloud Run, variable d'env `WORKER_SECRET_KEY` obligatoire).
Notez l'URL HTTPS renvoyée par la plateforme (ex: `https://wisestudio-worker-xxxx.a.run.app`).

## 2. Configurer WiseStudio (Alwaysdata)
Définissez ces deux variables d'environnement côté Alwaysdata (panneau
"Environnement" du site, PAS dans le code) :
- `WORKER_URL` = l'URL du worker déployé à l'étape 1
- `WORKER_SECRET_KEY` = la MÊME clé secrète que celle donnée au worker

`config/app.php` les lit automatiquement via `getenv()`.

## 3. Uploader les fichiers PHP (dossier `php/`)
Écrasent les fichiers existants à l'identique de l'arborescence :
- `controllers/ProjectController.php`
- `models/Project.php`
- `config/app.php`
- `index.php`
- `views/dashboard/studio.php`
- `assets/js/youtube-worker.js` (nouveau fichier)

## 4. Vérifier
- Rendez-vous sur `/dashboard/studio`, collez un lien YouTube de moins de
  1h, cliquez "Analyser" : un projet doit apparaître après quelques
  minutes (selon durée de la vidéo) dans le sélecteur "Projet analysé par
  l'IA" une fois la page rechargée.
- Cliquez "Télécharger en MP4" sur un autre lien : un bouton de
  téléchargement doit apparaître une fois le traitement terminé.
- Testez une vidéo de plus d'1h : le message d'erreur de durée doit
  s'afficher immédiatement, sans débit de Notes ni projet créé.

## Rappel important
L'extraction YouTube via `yt-dlp` n'est pas conforme aux CGU de YouTube.
Voir `worker-wisestudio/README.md` pour le détail des risques et la
nécessité de mises à jour régulières de `yt-dlp`.
