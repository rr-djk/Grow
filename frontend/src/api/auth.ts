import { inLang } from "../lib/format";
import { DEMO, demoDeleteUser, demoSignIn, demoSignUp } from "./demo";
import { ApiError } from "./errors";
import type { ErrorCode } from "./types";

const REGION = import.meta.env.VITE_COGNITO_REGION;
const CLIENT_ID = import.meta.env.VITE_COGNITO_CLIENT_ID;
const KEY = "alphaforge.tokens";

type Tokens = { accessToken: string; refreshToken: string; expiresAt: number };

function read(): Tokens | null {
  try { return JSON.parse(sessionStorage.getItem(KEY) ?? "null"); } catch { return null; }
}
function write(t: Tokens | null) {
  if (t) sessionStorage.setItem(KEY, JSON.stringify(t)); else sessionStorage.removeItem(KEY);
}

async function cognito(target: string, body: unknown): Promise<any> {
  if (!REGION || !CLIENT_ID) throw new ApiError("INTERNAL", inLang("Cognito n'est pas configuré (VITE_COGNITO_REGION, VITE_COGNITO_CLIENT_ID).", "Cognito is not configured (VITE_COGNITO_REGION, VITE_COGNITO_CLIENT_ID)."), 0);
  let res: Response;
  try {
    res = await fetch(`https://cognito-idp.${REGION}.amazonaws.com/`, {
      method: "POST",
      headers: { "Content-Type": "application/x-amz-json-1.1", "X-Amz-Target": `AWSCognitoIdentityProviderService.${target}` },
      body: JSON.stringify(body),
    });
  } catch {
    throw new ApiError("NETWORK", inLang("Connexion à Cognito impossible.", "Unable to reach Cognito."), 0);
  }
  const json = await res.json().catch(() => ({}));
  if (!res.ok) {
    const type = String(json.__type ?? "").split("#").pop() ?? "";
    const known = COGNITO_ERRORS[type];
    if (known) throw new ApiError(known[0], known[1], res.status);
    throw new ApiError("UNAUTHORIZED", json.message ?? inLang("Échec de la requête Cognito.", "The Cognito request failed."), res.status);
  }
  return json;
}

const COGNITO_ERRORS: Record<string, [ErrorCode, string]> = {
  NotAuthorizedException: ["UNAUTHORIZED", "Identifiants invalides."],
  UserNotFoundException: ["UNAUTHORIZED", "Identifiants invalides."],
  UserNotConfirmedException: ["UNAUTHORIZED", inLang("Ce compte n'est pas confirmé. Contactez l'équipe.", "This account is not confirmed. Contact the team.")],
  UsernameExistsException: ["VALIDATION_ERROR", inLang("Ce nom d'utilisateur est déjà pris.", "This username is already taken.")],
  InvalidPasswordException: ["VALIDATION_ERROR", inLang("Mot de passe refusé : au moins 8 caractères avec majuscule, minuscule, chiffre et symbole.", "Password rejected: at least 8 characters with an uppercase letter, a lowercase letter, a digit and a symbol.")],
  InvalidParameterException: ["VALIDATION_ERROR", inLang("Un des champs est invalide (vérifiez le courriel et le nom d'utilisateur).", "One of the fields is invalid (check the email and the username).")],
  LimitExceededException: ["VALIDATION_ERROR", inLang("Trop de tentatives. Réessayez dans quelques minutes.", "Too many attempts. Try again in a few minutes.")],
  TooManyRequestsException: ["VALIDATION_ERROR", inLang("Trop de tentatives. Réessayez dans quelques minutes.", "Too many attempts. Try again in a few minutes.")],
};

function store(r: any, fallbackRefresh?: string): Tokens {
  const a = r.AuthenticationResult;
  const t: Tokens = {
    accessToken: a.AccessToken,
    refreshToken: a.RefreshToken ?? fallbackRefresh,
    expiresAt: Date.now() + (a.ExpiresIn ?? 3600) * 1000,
  };
  write(t);
  return t;
}

export async function signIn(username: string, password: string) {
  if (DEMO) { write({ accessToken: demoSignIn(username, password), refreshToken: "", expiresAt: Date.now() + 365 * 86400000 }); return; }
  const r = await cognito("InitiateAuth", { AuthFlow: "USER_PASSWORD_AUTH", ClientId: CLIENT_ID, AuthParameters: { USERNAME: username, PASSWORD: password } });
  if (!r.AuthenticationResult) throw new ApiError("UNAUTHORIZED", inLang("Cette connexion demande une étape supplémentaire (ex. changement de mot de passe). Contactez l'équipe.", "This sign-in needs an extra step (e.g. a password change). Contact the team."), 401);
  store(r);
}

export async function signUp(username: string, password: string, email: string, givenName: string, familyName: string): Promise<void> {
  if (DEMO) { demoSignUp(username, password, email, `${givenName} ${familyName}`); return; }
  await cognito("SignUp", {
    ClientId: CLIENT_ID, Username: username, Password: password,
    UserAttributes: [
      { Name: "email", Value: email },
      { Name: "given_name", Value: givenName },
      { Name: "family_name", Value: familyName },
    ],
  });
}

export function signOut() { write(null); inflight = null; }
export async function deleteOwnAccount(): Promise<void> {
  const token = await getAccessToken();
  if (DEMO) demoDeleteUser(token);
  else await cognito("DeleteUser", { AccessToken: token });
  signOut();
}
export const hasSession = () => read() !== null;

let inflight: Promise<string> | null = null;

export async function getAccessToken(forceRefresh = false): Promise<string> {
  const t = read();
  if (!t) throw new ApiError("UNAUTHORIZED", inLang("Session expirée.", "Session expired."), 401);
  if (!forceRefresh && t.expiresAt - Date.now() > 30_000) return t.accessToken;
  if (DEMO) { write(null); throw new ApiError("UNAUTHORIZED", inLang("Session expirée.", "Session expired."), 401); }
  inflight ??= cognito("InitiateAuth", { AuthFlow: "REFRESH_TOKEN_AUTH", ClientId: CLIENT_ID, AuthParameters: { REFRESH_TOKEN: t.refreshToken } })
    .then((r) => store(r, t.refreshToken).accessToken)
    .catch((e) => { write(null); throw e instanceof ApiError && e.code === "NETWORK" ? e : new ApiError("UNAUTHORIZED", inLang("Session expirée.", "Session expired."), 401); })
    .finally(() => { inflight = null; });
  return inflight;
}
