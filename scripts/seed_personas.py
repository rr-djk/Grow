#!/usr/bin/env python3
"""Crée les comptes Cognito des personas et charge leur profil et leur portefeuille.

Usage (depuis la racine du dépôt, venv activé) :
    source scripts/aws-env.sh && python scripts/seed_personas.py amira mateo
    source scripts/aws-env.sh && python scripts/seed_personas.py robert --accounts-only

- Identifiants du pool, du client et de l'API : `terraform output` (infra/terraform).
- Mots de passe : variables PERSONA_<NOM>_PASSWORD du fichier `.env` (ignoré par git).
  Absents, ils sont générés (simples) et ajoutés à `.env`. Ils ne sont jamais affichés.
- Idempotent : un compte existant est conservé (mot de passe remis), le profil et
  les positions sont remplacés (PUT).
- Les données passent par l'API réelle avec le jeton du compte (identité = JWT).
  Les montants sont en CAD ; les quantités sont calculées au dernier cours du jeu
  de données (converti avec le taux USD/CAD pour les titres cotés en USD).
Données fictives uniquement (aucune donnée personnelle réelle).
"""

from __future__ import annotations

import argparse
import json
import secrets
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

CODE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(CODE_ROOT))
ROOT = Path(subprocess.run(
    ["git", "-C", str(CODE_ROOT), "rev-parse", "--path-format=absolute", "--git-common-dir"],
    check=True, capture_output=True, text=True,
).stdout.strip()).parent

ENV_FILE = ROOT / ".env"
DATASET_DIR = ROOT / "data" / "output" / "2026-11-14"
REGION = "us-east-1"

PERSONAS: dict[str, dict] = {
    "robert": {
        "profile": {
            "riskLevel": "low_moderate", "riskTolerance": 3, "province": "QC",
            "horizonMinYears": 3, "horizonMaxYears": 5,
            "objective": "préservation du capital, retraite proche",
            "constraints": ["diversification minimale"], "preferences": [],
            "excludedAssetClasses": ["crypto"],
        },
        "amounts": {"XIU.TO": 30000, "RY.TO": 8000, "TD.TO": 9000, "XBB.TO": 30000, "ZST.TO": 15000},
    },
    "amira": {
        "profile": {
            "riskLevel": "high", "riskTolerance": 5, "riskCapacity": 4, "province": "ON",
            "horizonMinYears": 15,
            "objective": "croissance à long terme",
            "constraints": ["diversification cohérente avec un risque élevé"], "preferences": ["IA"],
            "excludedAssetClasses": [],
        },
        "amounts": {"XIC.TO": 45000, "XIU.TO": 15000, "SHOP.TO": 5000, "VFV.TO": 8000, "BTC-USD": 6000},
    },
    "mateo": {
        "profile": {
            "riskLevel": "moderate", "riskTolerance": 3, "riskCapacity": 3, "province": "QC",
            "horizonMinYears": 8, "horizonMaxYears": 12,
            "objective": "croissance modérée avec critères ESG",
            "constraints": [], "preferences": ["ESG"],
            "excludedAssetClasses": [],
        },
        "amounts": {"XESG.TO": 30000, "XIC.TO": 15000, "VFV.TO": 12000, "XEF.TO": 10000, "XBB.TO": 25000},
    },
}


def read_env() -> dict[str, str]:
    values: dict[str, str] = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, _, value = line.partition("=")
                values[key.strip()] = value.strip()
    return values


def password_for(name: str) -> str:
    key = f"PERSONA_{name.upper()}_PASSWORD"
    env = read_env()
    if env.get(key):
        return env[key]
    password = f"{name}-forge-{secrets.randbelow(10**6):06d}"
    prefix = "" if not ENV_FILE.exists() or ENV_FILE.read_text().endswith("\n") or not ENV_FILE.read_text() else "\n"
    with ENV_FILE.open("a") as handle:
        handle.write(f"{prefix}{key}={password}\n")
    ENV_FILE.chmod(0o600)
    return password


def terraform_outputs() -> dict[str, str]:
    raw = subprocess.run(
        ["terraform", f"-chdir={ROOT / 'infra' / 'terraform'}", "output", "-json"],
        check=True, capture_output=True, text=True,
    ).stdout
    return {k: v["value"] for k, v in json.loads(raw).items()}


def ensure_account(cognito, pool_id: str, name: str, password: str) -> None:
    try:
        cognito.admin_create_user(UserPoolId=pool_id, Username=name, MessageAction="SUPPRESS")
        print(f"  compte créé : {name}")
    except cognito.exceptions.UsernameExistsException:
        print(f"  compte existant : {name}")
    cognito.admin_set_user_password(UserPoolId=pool_id, Username=name, Password=password, Permanent=True)


def id_token(cognito, client_id: str, name: str, password: str) -> str:
    response = cognito.initiate_auth(
        ClientId=client_id, AuthFlow="USER_PASSWORD_AUTH",
        AuthParameters={"USERNAME": name, "PASSWORD": password},
    )
    return response["AuthenticationResult"]["IdToken"]


def call(api_url: str, token: str, method: str, path: str, body: dict | None = None) -> dict:
    request = urllib.request.Request(
        api_url.rstrip("/") + path, method=method,
        data=None if body is None else json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as error:
        raise SystemExit(f"{method} {path} -> {error.code} {error.read().decode()[:400]}") from error


def holdings_from_amounts(amounts: dict[str, float]) -> list[dict]:
    from backend.agents.data.store import DataStore

    store = DataStore(str(DATASET_DIR), DATASET_DIR.name)
    usdcad = float(store.fx_usdcad().iloc[-1])
    holdings = []
    for ticker, cad in amounts.items():
        close = store.prices(ticker)["close"]
        last = float(close.iloc[-1])
        cost = float(close.iloc[max(0, len(close) - 253)])
        fx = usdcad if store.asset(ticker)["currency"] == "USD" else 1.0
        holdings.append({"ticker": ticker, "quantity": round(cad / fx / last, 6), "avgCost": round(cost, 4)})
    return holdings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("personas", nargs="+", choices=sorted(PERSONAS))
    parser.add_argument("--accounts-only", action="store_true", help="créer les comptes sans charger profil ni portefeuille")
    args = parser.parse_args()

    import boto3

    out = terraform_outputs()
    cognito = boto3.client("cognito-idp", region_name=REGION)
    for name in args.personas:
        print(f"== {name}")
        password = password_for(name)
        ensure_account(cognito, out["cognito_user_pool_id"], name, password)
        if args.accounts_only:
            continue
        token = id_token(cognito, out["cognito_user_pool_client_id"], name, password)
        call(out["api_url"], token, "GET", "/v1/me")
        call(out["api_url"], token, "PUT", "/v1/me/profile", PERSONAS[name]["profile"])
        call(out["api_url"], token, "GET", "/v1/portfolios")
        portfolio = call(out["api_url"], token, "PUT", "/v1/portfolios/main/holdings",
                         {"holdings": holdings_from_amounts(PERSONAS[name]["amounts"])})
        print(f"  profil et {len(portfolio['holdings'])} positions chargés")
    return 0


if __name__ == "__main__":
    sys.exit(main())
