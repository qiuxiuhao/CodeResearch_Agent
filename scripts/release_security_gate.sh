#!/usr/bin/env bash
set -euo pipefail

required=(pip-audit npm gitleaks trivy)
for command_name in "${required[@]}"; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "release gate unavailable: $command_name" >&2
    exit 2
  fi
done

python -m pip check
pip-audit
npm --prefix frontend audit --audit-level=high
gitleaks detect --no-banner --redact
trivy fs --severity HIGH,CRITICAL --exit-code 1 .

if rg -n 'pickle|application/x-python-serialize' backend/app/control_plane; then
  echo "unsafe serializer reference found" >&2
  exit 1
fi

echo "release security gate passed"
