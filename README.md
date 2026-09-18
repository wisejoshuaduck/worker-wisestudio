# Worker WiseStudio — YouTube (audio chunké + MP4)

## ⚠️ Avertissement légal — à lire avant de déployer

Ce worker utilise **yt-dlp** pour extraire l'audio ou la vidéo de liens
YouTube. **Cette pratique est contraire aux conditions d'utilisation de
YouTube** (interdiction de télécharger du contenu sans autorisation
explicite). Conséquences concrètes à anticiper :

- YouTube fait régulièrement évoluer ses contre-mesures anti-scraping :
  `yt-dlp` peut cesser de fonctionner du jour au lendemain et nécessite des
  mises à jour fréquentes (`pip install -U yt-dlp` régulièrement, voire à
  chaque déploiement).
- Les IP des hébergeurs datacenter (Render, Google Cloud Run, AWS...) sont
  parfois bloquées ou soumises à des CAPTCHA par YouTube, ce qui peut
  rendre le worker inutilisable sans préavis.
- C'est un choix à assumer consciemment, pas un détail d'implémentation :
  gardez un plan B (message d'erreur clair côté utilisateur si le worker
  échoue, pas de dépendance critique du produit sur cette fonctionnalité).

## Ce que fait le worker

Un seul endpoint `POST /tasks/youtube`, avec un champ `mode` :

- `mode: "audio"` — utilisé par la pipeline shorts/podcast de WiseStudio.
  Le worker télécharge l'audio, le découpe en tronçons de **10 minutes**
  (même convention que le chunking déjà en place côté navigateur dans
  `assets/js/pipeline.js` / `assets/js/social-format.js`, pour rester sous
  la limite de 24 Mo par requête Whisper/Groq), et envoie tous les
  tronçons à WiseStudio en un seul callback.
- `mode: "mp4"` — téléchargement direct, fonctionnalité indépendante de la
  génération de shorts (bouton "Télécharger en MP4"). Le worker télécharge
  la vidéo complète (vidéo+audio fusionnés) et l'envoie à WiseStudio.

Dans les deux cas, **la durée est vérifiée AVANT tout téléchargement**
(appel yt-dlp léger, métadonnées seules) : au-delà de `MAX_DURATION_SECONDS`
(1h par défaut), la requête est refusée immédiatement (HTTP 422) — aucun
projet n'est créé côté WiseStudio, aucune Note n'est débitée.

## Variables d'environnement

| Variable              | Description                                              | Défaut |
|------------------------|-----------------------------------------------------------|--------|
| `WORKER_SECRET_KEY`    | Clé partagée avec WiseStudio (header `X-Worker-Key`)      | (vide, **à définir obligatoirement**) |
| `MAX_DURATION_SECONDS` | Durée max acceptée pour une vidéo, en secondes             | `3600` (1h) |

Générez une clé forte : `openssl rand -hex 32`. Cette même valeur doit être
configurée côté WiseStudio (`WORKER_SECRET_KEY` dans l'environnement
Alwaysdata, jamais en dur dans le code).

## Déploiement — Render (Free Web Service)

1. Poussez ce dossier `worker-wisestudio/` sur un dépôt GitHub.
2. `dashboard.render.com` → **New +** → **Web Service**, liez le dépôt,
   environnement **Docker**, plan **Free**.
3. Dans *Environment Variables* : `WORKER_SECRET_KEY` (et éventuellement
   `MAX_DURATION_SECONDS` si vous voulez une autre limite).
4. **Deploy**.

L'instance Render Free s'endort après 15 min d'inactivité. Comme le worker
répond immédiatement `{"status": "queued", ...}` avant de traiter en tâche
de fond, il ne dépasse pas le timeout HTTP de Render. Un ping cron toutes
les 10 min (`GET /health`) depuis WiseStudio peut limiter les cold starts,
sans garantie à 100%.

## Déploiement — Google Cloud Run (Free Tier)

```bash
gcloud run deploy wisestudio-worker \
  --source . \
  --platform managed \
  --region us-central1 \
  --allow-unauthenticated \
  --memory 1Gi \
  --cpu 1 \
  --set-env-vars WORKER_SECRET_KEY="votre_cle_secrete",MAX_DURATION_SECONDS="3600"
```

Cloud Run renvoie une URL HTTPS (ex: `https://wisestudio-worker-xxxx.a.run.app`)
à renseigner dans `WORKER_URL` côté WiseStudio.
