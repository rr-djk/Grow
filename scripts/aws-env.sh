_repo_root="$(cd "$(git -C "$(dirname "${BASH_SOURCE[0]:-${(%):-%x}}")" rev-parse --path-format=absolute --git-common-dir)/.." && pwd)"
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN
export AWS_CONFIG_FILE="$_repo_root/.aws-local/config"
export AWS_SHARED_CREDENTIALS_FILE="$_repo_root/.aws-local/credentials"
export AWS_PROFILE=alphaforge
unset _repo_root
aws sts get-caller-identity --query Arn --output text
