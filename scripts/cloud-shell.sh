#!/usr/bin/env bash
# Interactive Cloud Shell launcher. Never creates billed cloud resources.
set -euo pipefail

if [[ ! -t 0 ]]; then
  echo 'Run this saved script from an interactive Cloud Shell terminal.' >&2
  exit 1
fi

task_dir="/tmp/pes26ar-cloud-import"
mkdir -p "$task_dir"
cd "$task_dir"

python3 - <<'PY'
import shutil,zipfile
from pathlib import Path
free=shutil.disk_usage('.').free
print(f'Temporary disk available: {free/1024**3:.1f} GiB')
complete=Path('source.zip').is_file() and zipfile.is_zipfile('source.zip')
minimum=512*1024**2 if complete else 11*1024**3
if free<minimum:
    raise SystemExit('Stopped before downloading: at least 11 GiB temporary disk is required. No paid storage will be created.')
PY

if ! command -v gh >/dev/null 2>&1; then
  if [[ "$(uname -m)" != 'x86_64' ]]; then
    echo 'Unsupported CPU for the pinned GitHub CLI package.' >&2
    exit 1
  fi
  curl --fail --location --retry 3 --output gh.tar.gz \
    'https://github.com/cli/cli/releases/download/v2.104.0/gh_2.104.0_linux_amd64.tar.gz'
  echo '98cb101ad87dbbd3f6b2f2bfcbd43197ccd07643140121d8a9cfaa91eadbc24e  gh.tar.gz' | sha256sum --check
  tar -xzf gh.tar.gz gh_2.104.0_linux_amd64/bin/gh
  export PATH="$task_dir/gh_2.104.0_linux_amd64/bin:$PATH"
fi

# Keep the device-login credentials in a task-specific, temporary configuration.
export GH_CONFIG_DIR="$task_dir/github-config"
if ! gh auth status --hostname github.com >/dev/null 2>&1; then
  echo 'Authorize GitHub using the device code shown below. Do not share tokens.'
  gh auth login --hostname github.com --git-protocol https --web
fi
account="$(gh api user --jq .login)"
if [[ "${account,,}" != 'moatezsager' ]]; then
  echo "Wrong account: $account. Sign in as Moatezsager to upload to the intended repository." >&2
  exit 1
fi

if [[ ! -d repository/.git ]]; then
  git clone --depth 1 https://github.com/Moatezsager/pes26ar-updates.git repository
else
  git -C repository fetch origin main --depth 1
  git -C repository merge --ff-only origin/main
fi

python3 -m venv .venv
.venv/bin/pip install --no-cache-dir gdown==6.5.2

input_name='cloud-visual-input-20261119.zip'
input_sha='471a8e9242a8a47f49ba735edbb1c494d74fd268b342ad91002eb036b0422115'
if [[ ! -f visual-input.zip ]]; then
  gh release download build-input-2026.11.19 --repo Moatezsager/pes26ar-updates --pattern "$input_name"
  printf '%s  %s\n' "$input_sha" "$input_name" | sha256sum --check
  mv "$input_name" visual-input.zip
fi
printf '%s  visual-input.zip\n' "$input_sha" | sha256sum --check

echo 'Starting cloud import. This only creates/uploads a DRAFT data release.'
echo 'Keep this an interactive session. Cloud Shell can terminate idle sessions.'
echo 'If interrupted, run the launcher again; verified GitHub chunks are reused.'
.venv/bin/python repository/scripts/import_drive.py \
  --drive-id 10k7_kP4bDIVGmJRetWI-8wswCqZrNSww --release 2026.11.19.1

echo 'DRAFT COMPLETE. Ask the maintainer to review the manifest before publication.'
gh auth logout --hostname github.com --user Moatezsager
