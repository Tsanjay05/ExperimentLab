# ExperimentLab data dictionary

This dictionary describes the SQLite schema in `src/experimentlab/storage/schema.sql`.
All database timestamps are UTC strings in `YYYY-MM-DDTHH:MM:SSZ` form. JSON columns
contain valid JSON text. IDs are text primary keys and are generated deterministically
by the seeded data-generation layer.

## Entities and relationships

| Entity | Table | Primary key | Relationships |
|---|---|---|---|
| Experiment | `experiments` | `experiment_id` | Parent of variants, assignments, metric definitions, guardrails, and results. Its optional primary metric must belong to the same experiment. |
| Variant | `variants` | `variant_id` | Belongs to an experiment. Assignments and results may reference it only within that experiment. |
| AudienceMember | `audience_members` | `audience_member_id` | May be assigned to experiments. Attributes are pre-experiment values only. |
| Assignment | `assignments` | `assignment_id` | Joins one audience member to one variant in one experiment. |
| ExposureEvent | `exposure_events` | `exposure_event_id` | References an assignment in its experiment. |
| ConversionEvent | `conversion_events` | `conversion_event_id` | References an assignment and a metric definition from the same experiment. |
| MetricDefinition | `metric_definitions` | `metric_definition_id` | Versioned definition owned by an experiment; referenced by events, guardrails, and results. |
| GuardrailMetric | `guardrail_metrics` | `guardrail_id` | References a metric definition from the same experiment. |
| ExperimentResult | `experiment_results` | `result_id` | References one experiment's metric definition and control/treatment variants. Stores an immutable intention-to-treat result. |

Composite foreign keys enforce that assignments point to variants in their own
experiment and that metric definitions referenced by conversions, guardrails, and
results belong to the same experiment. SQLite foreign-key enforcement is enabled by
the connection factory for every connection.

## Field definitions

Required means `NOT NULL` or part of the primary key. Optional fields accept SQL `NULL`.
Where a field has a default, the default is shown in its rule.

### Experiment (`experiments`)

| Field | SQLite type | Required | Allowed values / units | Uniqueness | Validation |
|---|---|---:|---|---|---|
| `experiment_id` | TEXT | Yes | `EXP-2026-` plus six digits | Primary key | Must match the specified ID format. |
| `name` | TEXT | Yes | Non-empty human-readable name | Globally unique | Trimmed value cannot be empty. |
| `hypothesis` | TEXT | Yes | Non-empty text | — | Trimmed value cannot be empty. |
| `status` | TEXT | Yes | `draft`, `running`, `paused`, `completed`, `analyzed`, `archived` | — | Defaults to `draft`; CHECK restricts lifecycle values. |
| `randomization_unit` | TEXT | Yes | `audience_member` | — | Defaults to and currently restricted to `audience_member`. |
| `start_at` | TEXT | No | UTC timestamp | — | If present, must parse as the canonical timestamp format. |
| `end_at` | TEXT | No | UTC timestamp | — | If present, must parse and be later than `start_at` when both are set. |
| `primary_metric_definition_id` | TEXT | No | Metric definition ID | Unique with experiment ID | Composite FK ensures the metric is from this experiment. |
| `created_at` | TEXT | Yes | UTC timestamp | — | Must parse as canonical timestamp. |
| `updated_at` | TEXT | Yes | UTC timestamp | — | Must parse as canonical timestamp. |

### Variant (`variants`)

| Field | SQLite type | Required | Allowed values / units | Uniqueness | Validation |
|---|---|---:|---|---|---|
| `variant_id` | TEXT | Yes | `VAR-{experiment_id}-{A-Z}` | Primary key; unique with experiment | Format is checked; composite unique key supports same-experiment FKs. |
| `experiment_id` | TEXT | Yes | Existing experiment ID | — | FK to `experiments`. |
| `variant_key` | TEXT | Yes | One uppercase letter | Unique per experiment | CHECK enforces one uppercase ASCII letter. |
| `display_name` | TEXT | Yes | Non-empty text | — | Trimmed value cannot be empty. |
| `is_control` | INTEGER | Yes | `0` or `1` | At most one control per experiment | Boolean CHECK and partial unique index. |
| `allocation_probability` | REAL | Yes | Probability in `(0, 1]` | — | CHECK enforces range; total across variants is validated by the generation/validation layer. |
| `config_json` | TEXT | Yes | JSON object/text; default `{}` | — | Must pass SQLite `json_valid`. |
| `status` | TEXT | Yes | `draft`, `active`, `retired` | — | Defaults to `draft`. |

### AudienceMember (`audience_members`)

| Field | SQLite type | Required | Allowed values / units | Uniqueness | Validation |
|---|---|---:|---|---|---|
| `audience_member_id` | TEXT | Yes | `USR-` plus six digits | Primary key | Stable, zero-padded ID format checked. |
| `created_at` | TEXT | Yes | UTC timestamp | — | Must parse as canonical timestamp. |
| `country` | TEXT | No | Country code or name | — | No database-level code list. |
| `platform` | TEXT | No | `web`, `ios`, `android` | — | CHECK when present. |
| `segment` | TEXT | No | Segment label | — | Pre-experiment classification only. |
| `pre_experiment_attributes_json` | TEXT | Yes | JSON; default `{}` | — | Must pass `json_valid`; intended only for pre-treatment covariates. |

### Assignment (`assignments`)

| Field | SQLite type | Required | Allowed values / units | Uniqueness | Validation |
|---|---|---:|---|---|---|
| `assignment_id` | TEXT | Yes | `ASG-{experiment_id}-{audience_member_id}` | Primary key; unique with experiment | CHECK requires exact ID composed from the referenced experiment and member. |
| `experiment_id` | TEXT | Yes | Existing experiment ID | — | Composite FK with variant; unique with assignment ID. |
| `variant_id` | TEXT | Yes | Variant in the same experiment | — | Composite FK to `variants(variant_id, experiment_id)`. |
| `audience_member_id` | TEXT | Yes | Existing audience member ID | Unique per experiment | FK to audience member; unique `(experiment_id, audience_member_id)` prevents baseline multi-variant assignment. |
| `assigned_at` | TEXT | Yes | UTC timestamp | — | Must parse as canonical timestamp. |
| `assignment_probability` | REAL | Yes | Probability in `(0, 1]` | — | CHECK enforces range. |
| `randomization_bucket` | INTEGER | Yes | Integer `0`–`999999` | — | CHECK enforces range. |

### ExposureEvent (`exposure_events`)

| Field | SQLite type | Required | Allowed values / units | Uniqueness | Validation |
|---|---|---:|---|---|---|
| `exposure_event_id` | TEXT | Yes | `EXPOS-2026-` plus six digits | Primary key | ID format checked. |
| `assignment_id` | TEXT | Yes | Existing assignment | — | Composite FK includes experiment ID. |
| `experiment_id` | TEXT | Yes | Experiment for assignment | — | Composite FK to assignment. |
| `occurred_at` | TEXT | Yes | UTC timestamp | — | Canonical timestamp; trigger rejects time earlier than assignment. |
| `event_type` | TEXT | Yes | `client_render`, `server_render` | — | CHECK restricts values. |
| `source` | TEXT | Yes | Non-empty source label | — | Trimmed value cannot be empty. |
| `payload_json` | TEXT | Yes | JSON; default `{}` | — | Must pass `json_valid`. |

### ConversionEvent (`conversion_events`)

| Field | SQLite type | Required | Allowed values / units | Uniqueness | Validation |
|---|---|---:|---|---|---|
| `conversion_event_id` | TEXT | Yes | `CONV-2026-` plus six digits | Primary key | ID format checked. |
| `assignment_id` | TEXT | Yes | Existing assignment | — | Composite FK includes experiment ID. |
| `experiment_id` | TEXT | Yes | Experiment for assignment and metric | — | Composite FKs enforce same experiment. |
| `metric_definition_id` | TEXT | Yes | Existing metric definition | — | Composite FK ensures metric belongs to experiment. |
| `occurred_at` | TEXT | Yes | UTC timestamp | — | Canonical timestamp; trigger rejects time earlier than assignment. |
| `value` | REAL | Yes | Numeric value in metric's declared unit | — | SQLite numeric storage; metric-specific validation occurs in analysis. |
| `currency` | TEXT | No | ISO currency code when applicable | — | Required by application validation for currency metrics. |
| `source` | TEXT | Yes | Non-empty source label | — | Trimmed value cannot be empty. |
| `payload_json` | TEXT | Yes | JSON; default `{}` | — | Must pass `json_valid`. |

### MetricDefinition (`metric_definitions`)

| Field | SQLite type | Required | Allowed values / units | Uniqueness | Validation |
|---|---|---:|---|---|---|
| `metric_definition_id` | TEXT | Yes | `MET-` plus six digits | Primary key; unique with experiment | ID format checked. |
| `experiment_id` | TEXT | Yes | Existing experiment ID | — | FK to experiment; composite unique key supports scoped references. |
| `metric_key` | TEXT | Yes | Non-empty stable key | Unique with version per experiment | Trimmed value cannot be empty. |
| `version` | INTEGER | Yes | Positive integer | Unique with metric key and experiment | CHECK requires `> 0`. |
| `name` | TEXT | Yes | Non-empty display name | — | Trimmed value cannot be empty. |
| `metric_type` | TEXT | Yes | `binary`, `continuous`, `count`, `currency` | — | CHECK restricts type. |
| `unit` | TEXT | Yes | Metric-specific unit label | — | Trimmed value cannot be empty. |
| `aggregation` | TEXT | Yes | `sum`, `mean`, `count`, `proportion`, `unique_count` | — | CHECK restricts aggregation. |
| `denominator` | TEXT | No | Denominator description/key | — | Used for rate/proportion definitions. |
| `attribution_window_days` | INTEGER | Yes | Positive number of days | — | CHECK requires `> 0`. |
| `definition_json` | TEXT | Yes | Valid JSON definition | — | `json_valid` CHECK. |
| `content_hash` | TEXT | Yes | 64 lowercase hexadecimal characters | — | CHECK enforces shape. |
| `created_at` | TEXT | Yes | UTC timestamp | — | Must parse as canonical timestamp. |
| `effective_at` | TEXT | Yes | UTC timestamp | — | Must parse as canonical timestamp. |

Metric definitions cannot be updated or deleted. A changed definition is represented
by inserting a new version; prior events and results continue referencing the old ID.

### GuardrailMetric (`guardrail_metrics`)

| Field | SQLite type | Required | Allowed values / units | Uniqueness | Validation |
|---|---|---:|---|---|---|
| `guardrail_id` | TEXT | Yes | `GRD-` plus six digits | Primary key | ID format checked. |
| `experiment_id` | TEXT | Yes | Existing experiment ID | — | Composite FK with metric definition. |
| `metric_definition_id` | TEXT | Yes | Definition from same experiment | — | Composite FK ensures correct experiment. |
| `comparison_direction` | TEXT | Yes | `higher_is_better`, `lower_is_better` | — | CHECK restricts values. |
| `threshold` | REAL | Yes | Metric's declared unit | — | Numeric threshold. |
| `max_regression` | REAL | Yes | Non-negative metric units | — | CHECK requires `>= 0`. |
| `severity` | TEXT | Yes | `info`, `warning`, `blocker` | — | CHECK restricts values. |
| `enabled` | INTEGER | Yes | `0` or `1`; default `1` | — | Boolean CHECK. |
| `created_at` | TEXT | Yes | UTC timestamp | — | Must parse as canonical timestamp. |

### ExperimentResult (`experiment_results`)

| Field | SQLite type | Required | Allowed values / units | Uniqueness | Validation |
|---|---|---:|---|---|---|
| `result_id` | TEXT | Yes | `RES-` plus six digits | Primary key | ID format checked. |
| `experiment_id` | TEXT | Yes | Existing experiment ID | — | Scoped composite FKs for metric and variants. |
| `metric_definition_id` | TEXT | Yes | Definition from same experiment | — | Composite FK enforces experiment. |
| `metric_definition_version` | INTEGER | Yes | Positive integer | — | Composite FK requires this to match the referenced metric definition version. |
| `control_variant_id` | TEXT | Yes | Variant from same experiment | — | Composite FK; cannot equal treatment variant. |
| `treatment_variant_id` | TEXT | Yes | Variant from same experiment | — | Composite FK; cannot equal control variant. |
| `computed_at` | TEXT | Yes | UTC timestamp | — | Must parse as canonical timestamp. |
| `analysis_plan_version` | TEXT | Yes | Non-empty version identifier | — | Trimmed value cannot be empty. |
| `outcome_window_start` | TEXT | Yes | UTC timestamp | — | Must parse; must precede window end. |
| `outcome_window_end` | TEXT | Yes | UTC timestamp | — | Must parse; must follow window start. |
| `control_n` | INTEGER | Yes | Non-negative participants | — | CHECK requires `>= 0`. |
| `treatment_n` | INTEGER | Yes | Non-negative participants | — | CHECK requires `>= 0`. |
| `effect_estimate` | REAL | Yes | Metric's declared unit | — | Numeric estimate; must lie inside stored confidence interval. |
| `standard_error` | REAL | Yes | Metric units | — | CHECK requires `>= 0`. |
| `confidence_level` | REAL | Yes | Probability strictly between 0 and 1 | — | CHECK enforces range. |
| `ci_lower` | REAL | Yes | Metric units | — | Must be `<= effect_estimate`. |
| `ci_upper` | REAL | Yes | Metric units | — | Must be `>= effect_estimate`. |
| `p_value` | REAL | Yes | Probability `[0, 1]` | — | CHECK enforces range. |
| `srm_p_value` | REAL | No | Probability `[0, 1]` | — | If present, CHECK enforces range. SRM compares observed counts to planned allocation. |
| `srm_status` | TEXT | Yes | `pass`, `warning`, `not_evaluated` | — | Diagnostic only; ITT analysis remains primary. |
| `guardrail_status` | TEXT | Yes | `pass`, `warning`, `fail`, `not_evaluated` | — | CHECK restricts values. |
| `decision` | TEXT | Yes | `ship`, `iterate`, `do_not_ship`, `inconclusive` | — | CHECK restricts values. |
| `analysis_method` | TEXT | Yes | `intention_to_treat` | — | Defaults to and is restricted to ITT. |
| `analysis_config_json` | TEXT | Yes | Valid JSON | — | `json_valid` CHECK. |
| `input_snapshot_hash` | TEXT | Yes | 64 lowercase hexadecimal characters | — | CHECK enforces shape for reproducibility. |

Results cannot be updated or deleted; a rerun creates another result with its own
analysis-plan version, metric-definition version, outcome window, and input snapshot
hash.

## History, anomalies, and ground truth

Exposure events, conversion events, metric-definition versions, and results are
append-only in the database. Database triggers reject updates/deletes for these records.
Missing telemetry is represented by absent events. Event timestamps retain delayed
conversions and are evaluated against the metric definition's outcome window by the
analysis layer.

The normal baseline database enforces one assignment per member per experiment and
valid event ordering. Deliberate anomaly fixtures (multiple variant assignments,
exposure before assignment, inconsistent outcome windows, ignored SRM, and metric
changes after results) and synthetic ground-truth labels belong in separate scenario
fixtures, not in baseline analytical inputs.

Ground truth is for validation only and must never be joined into analytical features.
SRM is stored as a diagnostic based on planned allocation; it does not change the
intention-to-treat population or silently remove participants.
