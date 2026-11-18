# Image de l'app Streamlit pour l'hébergement sur VPS (voir deploy/README.md).
#
# Version de Python épinglée exactement, comme les dépendances de
# requirements.txt (voir CLAUDE.md, "Historique des décisions",
# 2026-11-17) : une image qui change toute seule au prochain build peut
# casser l'app exactement comme selectolax 1.0.0 l'a fait.
FROM python:3.12.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
	PYTHONUNBUFFERED=1 \
	PIP_NO_CACHE_DIR=1 \
	PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Utilisateur non-root : si l'app est compromise, l'attaquant n'est pas root
# dans le conteneur.
RUN useradd --create-home --uid 1000 app

# Dépendances d'abord (couche mise en cache tant que requirements.txt ne
# change pas — un simple changement de code ne réinstalle rien).
# Playwright n'a besoin d'aucun navigateur ici : le projet n'utilise que
# `playwright.request` (client HTTP pur), dont le driver est inclus dans la
# wheel pip.
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY --chown=app:app . .
# /app lui-même doit appartenir à `app` (COPY --chown ne change que les
# fichiers copiés, pas WORKDIR, créé par root) : le chargement du jeu de
# démo écrit data_quality_report.json et sourcing_intel_demo.sqlite à la
# racine du projet — PermissionError en production sinon.
# sessions/ (données scrapées par visiteur) et logs/ sont montés en volumes
# par docker-compose ; les créer ici leur donne le bon propriétaire.
RUN chown app:app /app && mkdir -p sessions logs && chown app:app sessions logs

USER app
EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
	CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8501/_stcore/health', timeout=4)" || exit 1

CMD ["python", "-m", "streamlit", "run", "app.py", \
	"--server.port=8501", "--server.address=0.0.0.0", "--server.headless=true"]
