# Contrat d'API - Data Hygiene Watchdog (v0.2)

API (Matheo) pour l'interface (Axel). Adresse : `http://localhost:8000`.
Documentation interactive : `http://localhost:8000/docs`.

## Règles générales

- Toutes les routes commencent par `/api`. Requêtes et réponses en JSON.
- Erreur : `{"detail": "message"}`. Codes : 404 (id inconnu), 409 (action
  impossible dans cet état), 422 (paramètre invalide), 503 (base injoignable).
- `day` = numéro du jour de simulation, de 1 à 28 (jour 1 = lundi 2 novembre).
- Statuts d'un fix : `proposed`, `applied`, `awaiting_approval`, `approved`,
  `rejected`, `undone`.

## Lecture (GET)

| Route | Paramètres | Renvoie |
|---|---|---|
| `/api/health` | - | `{"status": "ok", "database": "up"}` |
| `/api/batches` | `day` | lots du jour |
| `/api/issues` | `day`, `status` | liste d'issues |
| `/api/fixes` | `day`, `status`, `issue_id` | liste de fixes |
| `/api/approvals` | - | fixes en attente d'approbation |
| `/api/agent-log` | `day` | décisions de l'agent et raisonnement |
| `/api/tickets` | - | tickets créés par l'agent |
| `/api/hand-offs` | `day` | lots transférés à un autre agent |
| `/api/quarantine` | `day` | lignes en quarantaine |
| `/api/column-history` | `feed`, `column` (obligatoires) | taux de null par jour (graphique) |
| `/api/kpis` | `day` (facultatif) | tuiles KPI |
| `/api/simulation/state` | - | jour courant et état |
| `/api/simulation/report` | - | résultats par jour et totaux |

Les paramètres sont facultatifs sauf indication contraire.

## Actions (POST)

| Route | Corps | Effet |
|---|---|---|
| `/api/fixes/{id}/approve` | `{"decided_by": "Nom"}` | passe le fix à `approved` |
| `/api/fixes/{id}/reject` | `{"decided_by": "Nom", "rejection_reason": "texte"}` | passe le fix à `rejected` (raison facultative) |
| `/api/fixes/{id}/undo` | aucun | restaure l'ancienne valeur, fix à `undone` |
| `/api/simulation/step` | aucun (facultatif : `agent`) | lance le jour suivant, répond à la fin du jour |

## Formats de réponse

**Issue** (`/api/issues`)

```json
{
  "issue_id": 1, "batch_id": 1, "feed_name": "pos",
  "batch_date": "2026-11-02", "day": 1,
  "issue_key": "pos:orders:unit_price:validity",
  "check_type": "validity", "column_name": "unit_price",
  "affected_rows": 1, "description": "currency symbol",
  "status": "open", "created_at": "2026-11-02T09:00:00+00:00",
  "fix_count": 4
}
```

**Fix** (`/api/fixes`, `/api/approvals`)

```json
{
  "fix_id": 1, "issue_id": 1, "batch_id": 1, "feed_name": "pos",
  "batch_date": "2026-11-02", "day": 1,
  "table_name": "orders", "column_name": "unit_price",
  "fix_type": "standardise_format", "record_id": "2",
  "before_value": "GBP 5.00", "after_value": "5.00",
  "reasoning": "strip prefix", "status": "applied",
  "decided_by": null, "decided_on": null, "applied_on": null,
  "rejection_reason": null, "created_at": "2026-11-02T09:00:00+00:00"
}
```

**KPI** (`/api/kpis`)

```json
{
  "day": null, "issues_detected": 2, "fixes_auto_applied": 3,
  "fixes_awaiting_approval": 2, "fixes_approved": 0,
  "fixes_rejected": 0, "fixes_undone": 0,
  "rows_quarantined": 1, "hand_offs": 1, "data_health": 0.97
}
```

`data_health` vaut `null` tant qu'aucun jour n'est terminé.

**État de la simulation** (`/api/simulation/state`)

```json
{
  "total_days": 28, "last_delivered_day": 2, "unfinished_day": null,
  "next_day": 3, "complete": false, "running": false,
  "default_agent": "noop_agent:run_day"
}
```

**Lancer un jour** (`POST /api/simulation/step`)

```json
{
  "day": 3, "complete": false,
  "result": {"sim_day": "2026-11-04", "caught": 1, "missed": 1,
             "fixed_correctly": 0, "wrongly_changed": 0,
             "false_alarms": 0, "data_health": 0.97, "details": {}},
  "state": {"...": "comme /api/simulation/state"}
}
```

**Annuler un fix** (`POST /api/fixes/{id}/undo`)

```json
{"fix_id": 1, "status": "undone", "staging_rows_restored": 1,
 "rows_already_processed": 0}
```

Si `rows_already_processed` est supérieur à 0, la réponse contient aussi
un champ `warning` à afficher.

## À savoir pour l'interface

- **Approuver ne corrige pas tout de suite** : le simulateur applique le fix
  le lendemain matin. Afficher "approuvé, appliqué demain".
- **Lancer un jour peut durer plusieurs minutes** : la requête reste
  ouverte. Pendant ce temps, interroger `/api/simulation/state` et
  désactiver les boutons tant que `running` vaut `true`.
- **Un seul jour à la fois** : un second lancement renvoie 409.
- **Tout est fini** quand `complete` vaut `true` (`next_day` vaut `null`).

## À décider en équipe

1. Annulation après promotion des données : qui rétablit les tables finales ?
2. Nom du module de l'agent pour `/api/simulation/step`.
3. Pagination : nécessaire ou non ? (absente pour l'instant)
