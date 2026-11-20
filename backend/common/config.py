"""Lecture des variables d'environnement, à l'appel (jamais à l'import).

Les noms ci-dessous sont fixés par WS0 (docs/workstreams.md) et partagés par
tous les chantiers : le backend/api, le backend/agents et l'infra Terraform
définissent exactement ces variables dans les Lambdas. Tout le reste du code
lit la configuration via ces fonctions, jamais avec `os.environ` directement.
"""

from __future__ import annotations

import os


class MissingEnvVar(RuntimeError):
    """Variable d'environnement requise absente : déploiement incomplet."""


def _required(name: str) -> str:
    """Retourne la variable d'environnement, ou lève MissingEnvVar si absente."""
    value = os.environ.get(name)
    if not value:
        raise MissingEnvVar(f"Variable d'environnement requise absente : {name}")
    return value



def users_table() -> str:
    """Nom de la table Users (partition : userId)."""
    return _required("USERS_TABLE")


def conversations_table() -> str:
    """Nom de la table Conversations (partition : userId, tri : sessionId)."""
    return _required("CONVERSATIONS_TABLE")


def messages_table() -> str:
    """Nom de la table Messages (partition : sessionId, tri : messageId)."""
    return _required("MESSAGES_TABLE")


def portfolios_table() -> str:
    """Nom de la table Portfolios (partition : userId, tri : portfolioId)."""
    return _required("PORTFOLIOS_TABLE")


def analyses_table() -> str:
    """Nom de la table Analyses (partition : sessionId, tri : itemKey).

    itemKey = MANDATE#<version sur 3 chiffres> ou RUN#<runId> (contrat v0.4.0).
    """
    return _required("ANALYSES_TABLE")



def dataset_bucket() -> str:
    """Nom du bucket S3 privé qui héberge le jeu de données."""
    return _required("DATASET_BUCKET")


def dataset_version() -> str:
    """Version du jeu de données à lire (préfixe dataset/{version}/ du bucket)."""
    return _required("DATASET_VERSION")



def model_orchestrator() -> str | None:
    """Profil d'inférence Bedrock de agent-orchestrator, None tant que non configuré."""
    return os.environ.get("MODEL_ORCHESTRATOR")


def model_auditor() -> str | None:
    """Profil d'inférence Bedrock de agent-auditor, None tant que non configuré."""
    return os.environ.get("MODEL_AUDITOR")


def model_writer() -> str | None:
    """Profil d'inférence Bedrock de agent-writer, None tant que non configuré."""
    return os.environ.get("MODEL_WRITER")



def kb_id() -> str | None:
    """Identifiant de la Knowledge Base réglementaire, None tant que non configuré."""
    return os.environ.get("KB_ID")


def kb_corpus_version() -> str | None:
    """Version du corpus réellement ingérée dans la Knowledge Base (variable posée après l'ingestion), None sinon.

    Absente : ancien corpus (sans métadonnée `citable`) ; présente : filtre `citable` strict et citations fixées (E2)."""
    return os.environ.get("KB_CORPUS_VERSION") or None


def guardrail_id() -> str | None:
    """Identifiant du Guardrail Bedrock, None tant que non configuré."""
    return os.environ.get("GUARDRAIL_ID")


def guardrail_version() -> str | None:
    """Version publiée du Guardrail Bedrock, None tant que non configurée."""
    return os.environ.get("GUARDRAIL_VERSION")


def rules_config_path() -> str | None:
    """Chemin optionnel du fichier de seuils des règles R1-R10 (hypothèses d'équipe).

    None = le module de règles utilise son fichier de configuration embarqué.
    """
    return os.environ.get("RULES_CONFIG_PATH")



DEFAULT_TRANSLATE_TERMINOLOGY = "grow-finance-en-fr"


def translate_terminology() -> str | None:
    """Nom de la terminologie Translate à citer, ou None (variable vide = aucune terminologie).

    Importée par scripts/import_terminology.py ; absente du compte, la traduction se fait sans elle."""
    value = os.environ.get("TRANSLATE_TERMINOLOGY")
    if value is None:
        return DEFAULT_TRANSLATE_TERMINOLOGY
    return value.strip() or None



def log_level() -> str:
    """Niveau de journalisation, INFO par défaut."""
    return os.environ.get("LOG_LEVEL", "INFO")



def langfuse_public_key() -> str | None:
    """Clé publique du projet Langfuse (pk-lf-...), None si non configurée."""
    return os.environ.get("LANGFUSE_PUBLIC_KEY")


def langfuse_secret_key() -> str | None:
    """Clé secrète Langfuse (sk-lf-...), en local seulement (.env). Sur AWS, utiliser SSM."""
    return os.environ.get("LANGFUSE_SECRET_KEY")


def langfuse_secret_param() -> str | None:
    """Nom du paramètre SSM SecureString contenant la clé secrète Langfuse (ex. /alphaforge/langfuse/secret-key)."""
    return os.environ.get("LANGFUSE_SECRET_PARAM")


def langfuse_base_url() -> str:
    """URL de base Langfuse (région US par défaut)."""
    return os.environ.get("LANGFUSE_BASE_URL", "https://us.cloud.langfuse.com")

