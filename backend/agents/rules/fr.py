"""Version française des textes connus d'avance (traduction fixe, sans Amazon Translate ni LLM).

Clé = le texte anglais exact de `rules.py` (motifs par défaut) ou de `rules_config.json` (mentions). Un texte absent
de la table (motif reformulé par l'auditeur, mention surchargée par RULES_CONFIG_PATH) passe par Amazon Translate.

Ces textes viennent du glossaire de l'équipe (backend/agents/translate/terminology/grow-finance-en-fr.csv) et n'ont
pas été relus par un spécialiste. Aucun ne dit qu'un scénario « convient » ou « est conforme » : une règle non
déclenchée se dit « non déclenchée ». Les mentions de province nomment légitimement « planificateur financier »
(titre réservé) : elles ne passent pas par les contrôles de formulations interdites du vérificateur.
"""

from __future__ import annotations

LOOK_THROUGH_SUFFIX_EN = " Fund look-through is incomplete for some funds."
LOOK_THROUGH_SUFFIX_FR = " La décomposition par transparence est incomplète pour certains fonds."

MESSAGES_FR: dict[str, str] = {
    "The scenario's volatility band does not exceed the retained level (the lower of tolerance and capacity).":
        "La bande de volatilité du scénario ne dépasse pas le niveau retenu (le plus bas entre la tolérance et la capacité).",
    "The tested idea implies a higher risk profile than the retained one, which is the lower of risk tolerance and risk capacity.":
        "L'idée testée suppose un profil de risque plus élevé que le profil retenu, soit le plus bas entre la tolérance au risque et la capacité à prendre des risques.",
    "The portfolio's volatility implies a higher risk profile than the retained one.":
        "La volatilité du portefeuille suppose un profil de risque plus élevé que le profil retenu.",
    "The historical drawdown could not be computed for this scenario.":
        "La baisse maximale historique n'a pas pu être calculée pour ce scénario.",
    "The worst simulated historical decline exceeds the maximum acceptable loss for this mandate.":
        "La pire baisse historique simulée dépasse la perte maximale acceptable de ce mandat.",
    "The worst simulated historical decline comes close to the maximum acceptable loss for this mandate.":
        "La pire baisse historique simulée s'approche de la perte maximale acceptable de ce mandat.",
    "The worst simulated historical decline does not reach the warning threshold derived from the maximum acceptable loss of this mandate.":
        "La pire baisse historique simulée n'atteint pas le seuil d'alerte tiré de la perte maximale acceptable de ce mandat.",
    "The portfolio is empty: the impact cannot be measured on an existing portfolio.":
        "Le portefeuille est vide : l'effet ne peut pas être mesuré sur un portefeuille existant.",
    "The impact is measured on the whole portfolio, not on the added security alone; the rule was not triggered.":
        "L'effet est mesuré sur l'ensemble du portefeuille, et non sur le seul titre ajouté ; la règle n'a pas été déclenchée.",
    "No comparison by asset category was requested.":
        "Aucune comparaison par catégorie d'actifs n'a été demandée.",
    "A comparison by asset category is shown as an additional scenario.":
        "Une comparaison par catégorie d'actifs est présentée comme scénario supplémentaire.",
    "The requested comparison could not be built from the dataset.":
        "La comparaison demandée n'a pas pu être construite à partir du jeu de données.",
    "A security symbol appears in the visible scenario texts.":
        "Un symbole de titre apparaît dans les textes visibles des scénarios.",
    "No security symbol appears in the visible scenario texts: the rule was not triggered.":
        "Aucun symbole de titre n'apparaît dans les textes visibles des scénarios ; la règle n'a pas été déclenchée.",
    "A single security, including through fund holdings, carries a very large share of the portfolio.":
        "Un seul titre, y compris par les titres détenus par les fonds, représente une très grande part du portefeuille.",
    "A single security, including through fund holdings, carries a large share of the portfolio.":
        "Un seul titre, y compris par les titres détenus par les fonds, représente une grande part du portefeuille.",
    "No single security, including through fund holdings, exceeds the concentration warning threshold.":
        "Aucun titre individuel, y compris par les titres détenus par les fonds, ne dépasse le seuil d'alerte de concentration.",
    "A single sector, including through fund holdings, carries a large share of the portfolio.":
        "Un seul secteur, y compris par les titres détenus par les fonds, représente une grande part du portefeuille.",
    "The scenario holds no crypto assets: the rule does not apply.":
        "Le scénario ne détient aucun crypto-actif : la règle ne s'applique pas.",
    "Crypto-asset exposure exceeds the cap for this mandate; crypto assets carry specific platform and custody risks.":
        "L'exposition aux crypto-actifs dépasse le plafond de ce mandat ; les crypto-actifs comportent des risques propres aux plateformes et à la garde.",
    "Crypto-asset exposure stays within the cap for this mandate, but crypto assets carry specific platform and custody risks.":
        "L'exposition aux crypto-actifs reste sous le plafond de ce mandat, mais les crypto-actifs comportent des risques propres aux plateformes et à la garde.",
    "The mandate has no ESG preference: the rule does not apply.":
        "Le mandat n'exprime aucune préférence ESG : la règle ne s'applique pas.",
    "Every holding has a published issuer ESG methodology: the rule was not triggered.":
        "Chaque position a une méthodologie ESG publiée par l'émetteur ; la règle n'a pas été déclenchée.",
    "Some holdings have no published ESG methodology: for equities only the sector is known and controversies are not verified.":
        "Certaines positions n'ont pas de méthodologie ESG publiée : pour les actions, seul le secteur est connu et les controverses ne sont pas vérifiées.",
    "Province notices name the regulator and the protected titles this tool does not use.":
        "Les mentions de la province nomment l'autorité de réglementation et les titres protégés que cet outil n'utilise pas.",
    "A macroeconomic value was used before its publication date.":
        "Une valeur macroéconomique a été utilisée avant sa date de publication.",
    "Only daily macroeconomic series, known on their observation date, were used: the rule was not triggered.":
        "Seules des séries macroéconomiques quotidiennes, connues à leur date d'observation, ont été utilisées ; la règle n'a pas été déclenchée.",
}

NOTICES_FR: dict[str, str] = {
    "Educational simulation only, not financial advice. No order is placed.":
        "Simulation éducative seulement, pas un conseil financier. Aucun ordre n'est passé.",
    "In Québec, securities activities are overseen by the Autorité des marchés financiers (AMF). The title \"financial planner\" is reserved by law; this tool is not a financial planner or a registered adviser. For personalized advice, consult a registered professional.":
        "Au Québec, les activités en valeurs mobilières sont encadrées par l'Autorité des marchés financiers (AMF). Le titre « planificateur financier » est réservé par la loi ; cet outil n'est ni un planificateur financier ni un conseiller inscrit. Pour des conseils personnalisés, consultez un professionnel inscrit.",
    "In Ontario, the titles \"financial planner\" and \"financial advisor\" are protected under the FSRA title protection framework; this tool uses neither title and is not a registered adviser. For personalized advice, consult a credentialed professional.":
        "En Ontario, les titres « planificateur financier » et « conseiller financier » sont protégés par le cadre de protection des titres de la FSRA ; cet outil n'utilise aucun de ces titres et n'est pas un conseiller inscrit. Pour des conseils personnalisés, consultez un professionnel accrédité.",
    "In Saskatchewan, the FCAA has proposed title protection rules for financial planners and advisors; this tool is not a financial planner or a registered adviser. For personalized advice, consult a registered professional.":
        "En Saskatchewan, la FCAA a proposé des règles de protection des titres pour les planificateurs financiers et les conseillers ; cet outil n'est ni un planificateur financier ni un conseiller inscrit. Pour des conseils personnalisés, consultez un professionnel inscrit.",
    "Securities activities are overseen by your provincial or territorial securities regulator; this tool is not a registered adviser. For personalized advice, consult a registered professional.":
        "Les activités en valeurs mobilières sont encadrées par l'autorité en valeurs mobilières de votre province ou territoire ; cet outil n'est pas un conseiller inscrit. Pour des conseils personnalisés, consultez un professionnel inscrit.",
}


def fixed_message(message_en: str) -> str | None:
    """Motif par défaut en français, ou None si le texte n'est pas dans la table (motif reformulé)."""
    if message_en in MESSAGES_FR:
        return MESSAGES_FR[message_en]
    if message_en.endswith(LOOK_THROUGH_SUFFIX_EN):
        base = MESSAGES_FR.get(message_en[: -len(LOOK_THROUGH_SUFFIX_EN)])
        if base is not None:
            return base + LOOK_THROUGH_SUFFIX_FR
    return None


def fixed_notice(notice_en: str) -> str | None:
    return NOTICES_FR.get(notice_en)
