# Testing Guide

Trois niveaux de test, à faire dans l'ordre :

1. **Local** — orchestrateur + postgres en Docker, migrations alembic, simulation d'un run via l'API
2. **Provisioning** — terraform crée la VM GPU, orchestrateur démarre dessus
3. **End-to-end** — pipeline CI complète, bench réel, leaderboard dans S3

## Clés SSH — qui sert à quoi

Il y a **deux contextes de VM** distincts, donc deux jeux de clés. Ne pas mélanger.

| Variable | Type | Sert à | Utilisé dans |
|---|---|---|---|
| `SSH_PUBLIC_KEYS` | env `.env` (orchestrateur) | Accès SSH aux **VMs GPU éphémères** spawnées à chaque run (utilisateur : `root`) | Test 0 |
| `DEPLOY_SSH_PUBLIC_KEY` | secret GitHub | Accès SSH à la **VM hôte longue-durée** qui héberge l'orchestrateur (utilisateur : `deploy`) | Tests 1 & 2 |
| `DEPLOY_SSH_KEY` | secret GitHub | Clé **privée** que la CI utilise pour push/rsync vers la VM hôte | Test 2 (CI) |

Les VMs GPU et la VM hôte ont des cycles de vie indépendants ; les clés ne sont donc pas partagées entre les deux contextes.

---

## Test 0 — Orchestrateur en local

Valide que la stack démarre, que les migrations passent, et que l'orchestrateur
peut piloter Terraform depuis son conteneur.

> ⚠️ L'orchestrateur **provisionne une vraie VM GPU Scaleway** dès qu'un run est
> créé via `POST /runs` (boucle de polling → `provision_node`). Cela engendre des
> coûts réels. Pour le smoke test pur (stack + /health), ne créez pas de run.
> Pour un vrai bench en local, voir l'étape 4.

### Prérequis

- Docker + Docker Compose
- Python 3.12 + `uv` (pour alembic en local)
- `jq` (pour les commandes curl)
- Un postgres local éventuellement déjà sur le port 5432 → le dev expose sur **5433**
- Credentials Scaleway (access key, secret key, project id) **si** vous comptez
  créer un run depuis le local

### 1. Configurer l'environnement

```bash
cp .env.example .env
```

Remplir `.env` (valeurs minimales) :

```env
POSTGRES_USER=llmgrill
POSTGRES_PASSWORD=changeme
POSTGRES_HOST=postgres
POSTGRES_DB=llmgrill

ORCHESTRATOR_URL=http://localhost:8000
API_KEY=local
HF_TOKEN=                       # requis pour un vrai bench (download HF)
SCW_ACCESS_KEY=                 # requis dès qu'un run est créé (terraform provisionne une VM)
SCW_SECRET_KEY=
SCW_DEFAULT_PROJECT_ID=         # ID du projet Scaleway (Console → Projets)
SCW_DEFAULT_ORGANIZATION_ID=    # ID de l'organisation
SCW_BUCKET=llmgrill-results
SCW_REGION=fr-par
GPU_ZONE=fr-par-2
SSH_PUBLIC_KEYS=                # optionnel : `cat ~/.ssh/id_ed25519.pub` (séparer par virgule si plusieurs)
RUN_RUNNING_TIMEOUT_MINUTES=60  # force-destroy si un run reste bloqué en running
DEBUG=true                      # active /docs et /redoc
```

Copier et adapter `orchestrator/.env` pour le dev local (postgres sur localhost:5433) :

```bash
cp orchestrator/.env.example orchestrator/.env
```

```env
# orchestrator/.env — doit avoir les mêmes credentials que .env
POSTGRES_USER=llmgrill
POSTGRES_PASSWORD=changeme
POSTGRES_HOST=localhost:5433   # port 5433 si postgres local déjà sur 5432
POSTGRES_DB=llmgrill

POLL_INTERVAL_SECONDS=10
```

### 2. Démarrer postgres et appliquer les migrations

```bash
# Démarrer uniquement postgres (exposé sur 5433 via docker-compose.dev.yml)
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d postgres

# Attendre que postgres soit healthy
docker compose -f docker-compose.yml -f docker-compose.dev.yml ps

# Appliquer les migrations alembic depuis la machine locale
cd orchestrator
set -a && source .env && set +a
alembic upgrade head
cd ..
```

### 3. Démarrer la stack complète

```bash
make up
# postgres + migrations + orchestrator démarrent
# logs en direct : make up-debug
```

Vérifier :

```bash
curl http://localhost:8000/health
# → {"status":"ok"}

# Swagger UI (disponible uniquement si DEBUG=true)
open http://localhost:8000/docs
```

### 4. (Optionnel) Lancer un vrai run depuis le local

> ⚠️ Cette étape provisionne une VM GPU Scaleway facturée. Sauter cette étape
> pour un simple smoke test.

#### 4.a — Exposer l'orchestrateur sur Internet (ngrok)

La VM GPU exécute `runner.sh` qui POST le résultat sur `${ORCHESTRATOR_URL}/runs/<id>/complete`.
Si `ORCHESTRATOR_URL=http://localhost:8000`, **`localhost` depuis la VM = la VM elle-même** :
le POST échoue et le run reste bloqué en `running`. Il faut un endpoint joignable depuis l'extérieur.

Le plus rapide : [ngrok](https://ngrok.com/download) (gratuit, compte requis).

```bash
# Dans un terminal séparé, expose le port 8000
ngrok http 8000
# → Forwarding  https://xxxxx-xxx-xx-xx-xx.ngrok-free.app -> http://localhost:8000
```

Mettre à jour `.env` avec l'URL publique **avant** de créer un run :

```env
ORCHESTRATOR_URL=https://xxxxx-xxx-xx-xx-xx.ngrok-free.app
```

Recréer le conteneur orchestrateur pour qu'il prenne la nouvelle URL (le
`runner.sh` sera téléchargé via cette URL par cloud-init) :

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --force-recreate orchestrator
```

Vérifier que l'URL ngrok sert bien l'orchestrateur :

```bash
curl https://xxxxx-xxx-xx-xx-xx.ngrok-free.app/health
# → {"status":"ok"}
```

> Alternatives : `cloudflared tunnel`, ou pointer `ORCHESTRATOR_URL` sur ton IP
> publique avec un port-forward 8000 sur la box. ngrok reste le plus simple.

#### 4.b — Créer le run

Vérifier que le conteneur orchestrateur embarque bien Terraform :

```bash
docker exec llmgrill-orchestrator terraform version
docker exec llmgrill-orchestrator ls /app/terraform
```

Créer un run. La boucle de polling de l'orchestrateur va le claim et invoquer
`terraform init` + `apply` dans `/app/terraform/workspaces/<run_id>/` :

```bash
API_KEY=local

curl -s -X POST http://localhost:8000/runs \
  -H "Content-Type: application/json" \
  -H "X-Api-Key: ${API_KEY}" \
  -d '{
    "model": "meta-llama/Llama-3.1-8B-Instruct",
    "model_size_b": 8,
    "engine": "vllm",
    "scenario_path": "scenarios/basic_8b.yaml"
  }' | tee /tmp/run.json

RUN_ID=$(jq -r '.id' /tmp/run.json)
```

#### 4.c — Suivre l'avancement

```bash
make logs
curl -s http://localhost:8000/runs/${RUN_ID} | jq .
curl -s http://localhost:8000/leaderboard | jq .
```

Cycle attendu : `queued` → `provisioning` (terraform apply, ~1-2 min) →
`running` (cloud-init + download HF + bench, 3-10 min selon le modèle) →
`done` après le POST `/complete` du runner (puis terraform destroy auto).

Côté VM, les logs du runner sont dans systemd-journald **pendant la vie de la VM**.
À la fin du run (succès ou fail), le runner uploade `/var/log/llmgrill-runner.log`
sur S3 et l'orchestrateur set `runs.logs_url`. Le log survit donc à la destruction
de la VM.

Trois façons de regarder les logs :

```bash
# Pendant le run, via SSH (raccourci Make qui résout l'IP automatiquement)
make vm-logs RUN_ID=<uuid>

# Après le run (ou même pendant si le upload a déjà eu lieu), via S3
make run-logs RUN_ID=<uuid>
# ou directement
curl -s http://localhost:8000/runs/<uuid>/logs

# Shell complet sur la VM
make vm-shell RUN_ID=<uuid>
```

Erreurs fréquentes :

| Symptôme | Cause |
|---|---|
| `terraform: not found` dans les logs | image obsolète — `docker compose build --no-cache orchestrator` |
| `PermissionError: '/terraform'` | code pas à jour — `_TERRAFORM_DIR` doit pointer vers `/app/terraform` |
| `Error: failed to authenticate` (Scaleway) | `SCW_ACCESS_KEY` / `SCW_SECRET_KEY` / `SCW_DEFAULT_PROJECT_ID` manquants dans `.env` |
| `out of stock` répété | normal : `OutOfStockError` re-queue automatiquement jusqu'à `PROVISION_MAX_ATTEMPTS` (30 par défaut) |
| Le run reste en `queued` | la boucle de polling n'a pas tourné — vérifier `POLL_INTERVAL_SECONDS` et les logs |
| Le run reste en `running` indéfiniment | la VM ne peut pas joindre `ORCHESTRATOR_URL` — vérifier ngrok (étape 4.a) et que l'URL est bien la publique, pas `localhost` |
| `ssh <user>@<ip>` → `Permission denied (publickey)` | `SSH_PUBLIC_KEYS` vide dans `.env`. Le remplir avec `cat ~/.ssh/id_ed25519.pub`, recréer le conteneur, et créer un nouveau run. Les VMs déjà provisionnées sans clé restent inaccessibles. |
| VM Scaleway en état `archived` après un run | `terraform destroy` n'a pas été déclenché (run sans `/complete` reçu, orchestrateur redémarré, etc.). Voir « Nettoyage manuel » plus bas. |

#### Nettoyage manuel des VMs orphelines

Lister puis supprimer (instance + volumes + IP) :

```bash
scw instance server list
scw instance server delete <SERVER_ID> with-ip=true with-volumes=all zone=fr-par-2
# pour une instance archived :
scw instance server delete <SERVER_ID> with-volumes=all zone=fr-par-2
```

Le watchdog `RUN_RUNNING_TIMEOUT_MINUTES` évite ce cas pour les runs futurs :
si aucun `/complete` n'arrive dans le délai (60 min par défaut), l'orchestrateur
lance lui-même `terraform destroy` et marque le run en `failed`.

Pour l'utilisateur SSH sur les VMs GPU provisionnées par l'orchestrateur :
c'est **`root`**. Les clés viennent de `SSH_PUBLIC_KEYS` injectées dans
`cloud-init` (voir `terraform/cloud-init.tpl.yaml`).

```bash
ssh root@<VM_IP> "journalctl -u llmgrill-runner -f"
```

> ⚠️ En Test 0 avec `ORCHESTRATOR_URL=http://localhost:8000`, la VM ne peut pas
> joindre l'orchestrateur ; le upload S3 du log file (et l'appel `/complete`)
> échoueront. `make vm-logs` reste utilisable tant que la VM tourne. Le upload
> S3 sera utile dès qu'on sera sur dev-1 (URL publique de l'orchestrateur).

Pré-requis pour SSH : `SSH_PUBLIC_KEYS=<ta clé publique>` dans `.env` **avant** de
créer le run. Les VMs déjà provisionnées sans clé restent inaccessibles.

Autres checks pendant la vie de la VM (via `make vm-shell`) :

```bash
cloud-init status --wait        # cloud-init terminé
systemctl status llmgrill-runner # service runner actif
nvidia-smi                       # le GPU est bien là
tail -f /var/log/llmgrill-runner.log
```

### 5. Arrêter

```bash
make down          # conserve les volumes (DB intacte)
make down-volumes  # wipe complet
```

---

## Test 1 — Provisioning avec vraie VM GPU

Valide que Terraform crée la VM, que cloud-init installe Docker, et que l'orchestrateur démarre avec les migrations. **Un vrai benchmark tourne** sur la VM GPU.

### Prérequis

- Terraform ≥ 1.6 installé (`terraform --version`)
- Credentials Scaleway avec accès GPU et Object Storage
- Une clé SSH ED25519 locale

```bash
terraform --version
aws --version   # pour le backend S3 (AWS CLI)
ssh -V
```

### Étape 1 — Créer le bucket tfstate (une seule fois)

```bash
AWS_ACCESS_KEY_ID=<SCW_ACCESS_KEY> \
AWS_SECRET_ACCESS_KEY=<SCW_SECRET_KEY> \
aws s3api create-bucket \
  --bucket llmgrill-tfstate \
  --endpoint-url https://s3.fr-par.scw.cloud
```

Si le bucket existe déjà, cette commande retourne une erreur ignorable.

### Étape 2 — Créer `infra/terraform.tfvars`

```bash
cp infra/terraform.tfvars.example infra/terraform.tfvars
```

Remplir `infra/terraform.tfvars` :

```hcl
region        = "fr-par"
zone          = "fr-par-2"
instance_type = "GPU-3070-S"   # instance GPU L40S
deploy_user   = "deploy"

ssh_public_keys = [
  "ssh-ed25519 AAAA...",   # ta clé publique : cat ~/.ssh/id_ed25519.pub
]

admin_cidrs = [
  "X.X.X.X/32",   # ton IP publique : curl -s ifconfig.me
]
```

> `infra/terraform.tfvars` est dans `.gitignore` — ne pas commiter.

### Étape 3 — Init et apply

```bash
cd infra

AWS_ACCESS_KEY_ID=<SCW_ACCESS_KEY> \
AWS_SECRET_ACCESS_KEY=<SCW_SECRET_KEY> \
SCW_ACCESS_KEY=<SCW_ACCESS_KEY> \
SCW_SECRET_KEY=<SCW_SECRET_KEY> \
terraform init

AWS_ACCESS_KEY_ID=<SCW_ACCESS_KEY> \
AWS_SECRET_ACCESS_KEY=<SCW_SECRET_KEY> \
SCW_ACCESS_KEY=<SCW_ACCESS_KEY> \
SCW_SECRET_KEY=<SCW_SECRET_KEY> \
terraform apply
```

Terraform affiche l'IP publique à la fin :

```
Outputs:
  public_ip = "X.X.X.X"
```

### Étape 4 — Attendre cloud-init (~2 min)

```bash
VM_IP=<public_ip>

until ssh -o StrictHostKeyChecking=no deploy@${VM_IP} "docker info > /dev/null 2>&1"; do
  echo "Waiting..."; sleep 10
done
echo "VM ready"

ssh-keyscan -H ${VM_IP} >> ~/.ssh/known_hosts
```

### Étape 5 — Déployer l'orchestrateur

```bash
# Copier le repo
rsync -az --exclude='.git' --exclude='.venv' --exclude='__pycache__' \
  ./ deploy@${VM_IP}:~/llm-grill-nightly/

# Écrire le .env
ssh deploy@${VM_IP} "cat > ~/llm-grill-nightly/.env" << EOF
POSTGRES_USER=llmgrill
POSTGRES_PASSWORD=changeme
POSTGRES_HOST=postgres
POSTGRES_DB=llmgrill
ORCHESTRATOR_URL=http://${VM_IP}:8000
API_KEY=$(openssl rand -hex 32)
HF_TOKEN=<ton token HF>
SCW_ACCESS_KEY=<SCW_ACCESS_KEY>
SCW_SECRET_KEY=<SCW_SECRET_KEY>
SCW_BUCKET=llmgrill-results
SCW_REGION=fr-par
GPU_ZONE=fr-par-2
DEBUG=false
EOF

# Démarrer la stack avec migrations
ssh deploy@${VM_IP} "
  cd ~/llm-grill-nightly
  docker compose \
    -f docker-compose.yml \
    -f docker-compose.with-migrations.yaml \
    up --build -d postgres migration orchestrator
"
```

### Étape 6 — Vérifier

```bash
# Health check
curl http://${VM_IP}:8000/health
# → {"status":"ok"}

# Logs si problème
ssh deploy@${VM_IP} "docker logs llmgrill-orchestrator --tail=50"
ssh deploy@${VM_IP} "docker logs llmgrill-migration --tail=50"
```

### Étape 7 — Lancer un bench réel

```bash
API_KEY=<api_key_du_env>

# Déclencher un bench sur un modèle 8B
curl -s -X POST http://${VM_IP}:8000/bench \
  -H "Content-Type: application/json" \
  -H "X-Api-Key: ${API_KEY}" \
  -d '{
    "model": "meta-llama/Llama-3.1-8B-Instruct",
    "scenario_path": "scenarios/basic_8b.yaml"
  }' | jq .

# Suivre l'avancement
watch -n 5 "curl -s http://${VM_IP}:8000/runs | jq '[.[] | {id,status,model}]'"

# Résultat final
curl -s http://${VM_IP}:8000/leaderboard | jq .
```

### Étape 8 — Détruire

```bash
cd infra

AWS_ACCESS_KEY_ID=<SCW_ACCESS_KEY> \
AWS_SECRET_ACCESS_KEY=<SCW_SECRET_KEY> \
SCW_ACCESS_KEY=<SCW_ACCESS_KEY> \
SCW_SECRET_KEY=<SCW_SECRET_KEY> \
terraform destroy
```

---

## Test 2 — End-to-end (pipeline CI complète)

Valide la pipeline entière : provision → bench → export leaderboard → destroy.

### Prérequis

Tous les secrets GitHub suivants doivent être configurés dans `Settings → Secrets → Actions` (environment `production`) :

| Secret | Comment l'obtenir |
|---|---|
| `DEPLOY_SSH_KEY` | Clé privée ED25519 : `cat ~/.ssh/id_ed25519` |
| `DEPLOY_SSH_PUBLIC_KEY` | Clé publique correspondante : `ssh-keygen -y -f ~/.ssh/id_ed25519` |
| `POSTGRES_USER` | Ex: `llmgrill` |
| `POSTGRES_PASSWORD` | Ex: `openssl rand -hex 16` |
| `API_KEY` | `openssl rand -hex 32` |
| `HF_TOKEN` | https://huggingface.co/settings/tokens |
| `SCW_ACCESS_KEY` | Console Scaleway → IAM → API Keys |
| `SCW_SECRET_KEY` | idem |
| `SCW_BUCKET` | Nom du bucket résultats (ex: `llmgrill-results`) |
| `SCW_REGION` | `fr-par` |
| `GPU_ZONE` | `fr-par-2` |

Le bucket `llmgrill-tfstate` doit exister (voir Test 1, Étape 1).

### Lancer un test rapide (un seul modèle)

1. Aller dans **Actions → bench → Run workflow**
2. Remplir :
   - `force` : `false`
   - `model` : nom partiel d'un petit modèle de `orchestrator/models.yaml` (ex: `Qwen`)
3. Cliquer **Run workflow**

### Suivre l'exécution

```
provision  (~5 min)   terraform apply + docker compose up + migrations
bench      (variable) POST /bench → poll → export leaderboard.json
teardown   (~2 min)   terraform destroy
```

Le job `teardown` tourne **toujours**, même si `bench` échoue.

### Vérifier le résultat

```bash
AWS_ACCESS_KEY_ID=<SCW_ACCESS_KEY> \
AWS_SECRET_ACCESS_KEY=<SCW_SECRET_KEY> \
aws s3 ls s3://<SCW_BUCKET>/ \
  --endpoint-url https://s3.fr-par.scw.cloud

AWS_ACCESS_KEY_ID=<SCW_ACCESS_KEY> \
AWS_SECRET_ACCESS_KEY=<SCW_SECRET_KEY> \
aws s3 cp s3://<SCW_BUCKET>/leaderboard.json - \
  --endpoint-url https://s3.fr-par.scw.cloud | jq .
```

### Si un job échoue

| Symptôme | Où regarder |
|---|---|
| `provision` échoue sur terraform apply | Vérifier les secrets `SCW_ACCESS_KEY` / `SCW_SECRET_KEY` et que le bucket tfstate existe |
| `provision` bloque sur "Waiting for SSH" | cloud-init trop lent — augmenter le timeout dans `bench.yml` |
| `provision` bloque sur "Waiting for /health" | `ssh deploy@${VM_IP} "docker logs llmgrill-orchestrator"` |
| migrations échouent | `ssh deploy@${VM_IP} "docker logs llmgrill-migration"` |
| `bench` échoue sur "run(s) failed" | Logs du runner GPU via `GET /runs/{id}` → `error_message` |
| `teardown` échoue | La VM reste up — lancer `terraform destroy` manuellement (voir Test 1, Étape 8) |
