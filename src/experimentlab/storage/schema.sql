PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS experiments (
    experiment_id TEXT PRIMARY KEY
        CHECK (experiment_id GLOB 'EXP-2026-[0-9][0-9][0-9][0-9][0-9][0-9]'),
    name TEXT NOT NULL UNIQUE CHECK (length(trim(name)) > 0),
    hypothesis TEXT NOT NULL CHECK (length(trim(hypothesis)) > 0),
    status TEXT NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'running', 'paused', 'completed', 'analyzed', 'archived')),
    randomization_unit TEXT NOT NULL DEFAULT 'audience_member'
        CHECK (randomization_unit = 'audience_member'),
    start_at TEXT,
    end_at TEXT,
    primary_metric_definition_id TEXT,
    created_at TEXT NOT NULL
        CHECK (strftime('%Y-%m-%dT%H:%M:%SZ', created_at) IS NOT NULL),
    updated_at TEXT NOT NULL
        CHECK (strftime('%Y-%m-%dT%H:%M:%SZ', updated_at) IS NOT NULL),
    CHECK (start_at IS NULL OR strftime('%Y-%m-%dT%H:%M:%SZ', start_at) IS NOT NULL),
    CHECK (end_at IS NULL OR strftime('%Y-%m-%dT%H:%M:%SZ', end_at) IS NOT NULL),
    CHECK (start_at IS NULL OR end_at IS NULL OR end_at > start_at),
    UNIQUE (experiment_id, primary_metric_definition_id),
    FOREIGN KEY (primary_metric_definition_id, experiment_id)
        REFERENCES metric_definitions (metric_definition_id, experiment_id)
);

CREATE TABLE IF NOT EXISTS audience_members (
    audience_member_id TEXT PRIMARY KEY
        CHECK (audience_member_id GLOB 'USR-[0-9][0-9][0-9][0-9][0-9][0-9]'),
    created_at TEXT NOT NULL
        CHECK (strftime('%Y-%m-%dT%H:%M:%SZ', created_at) IS NOT NULL),
    country TEXT,
    platform TEXT CHECK (platform IS NULL OR platform IN ('web', 'ios', 'android')),
    segment TEXT,
    pre_experiment_attributes_json TEXT NOT NULL DEFAULT '{}'
        CHECK (json_valid(pre_experiment_attributes_json))
);

CREATE TABLE IF NOT EXISTS variants (
    variant_id TEXT PRIMARY KEY
        CHECK (
            variant_id GLOB 'VAR-EXP-2026-[0-9][0-9][0-9][0-9][0-9][0-9]-[A-Z]'
        ),
    experiment_id TEXT NOT NULL,
    variant_key TEXT NOT NULL CHECK (variant_key GLOB '[A-Z]'),
    display_name TEXT NOT NULL CHECK (length(trim(display_name)) > 0),
    is_control INTEGER NOT NULL CHECK (is_control IN (0, 1)),
    allocation_probability REAL NOT NULL
        CHECK (allocation_probability > 0 AND allocation_probability <= 1),
    config_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(config_json)),
    status TEXT NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'active', 'retired')),
    UNIQUE (experiment_id, variant_key),
    UNIQUE (variant_id, experiment_id),
    FOREIGN KEY (experiment_id) REFERENCES experiments (experiment_id)
);

CREATE UNIQUE INDEX IF NOT EXISTS one_control_variant_per_experiment
    ON variants (experiment_id)
    WHERE is_control = 1;

CREATE TABLE IF NOT EXISTS metric_definitions (
    metric_definition_id TEXT PRIMARY KEY
        CHECK (metric_definition_id GLOB 'MET-[0-9][0-9][0-9][0-9][0-9][0-9]'),
    experiment_id TEXT NOT NULL,
    metric_key TEXT NOT NULL CHECK (length(trim(metric_key)) > 0),
    version INTEGER NOT NULL CHECK (version > 0),
    name TEXT NOT NULL CHECK (length(trim(name)) > 0),
    metric_type TEXT NOT NULL
        CHECK (metric_type IN ('binary', 'continuous', 'count', 'currency')),
    unit TEXT NOT NULL CHECK (length(trim(unit)) > 0),
    aggregation TEXT NOT NULL
        CHECK (aggregation IN ('sum', 'mean', 'count', 'proportion', 'unique_count')),
    denominator TEXT,
    attribution_window_days INTEGER NOT NULL CHECK (attribution_window_days > 0),
    definition_json TEXT NOT NULL CHECK (json_valid(definition_json)),
    content_hash TEXT NOT NULL
        CHECK (length(content_hash) = 64 AND content_hash NOT GLOB '*[^0-9a-f]*'),
    created_at TEXT NOT NULL
        CHECK (strftime('%Y-%m-%dT%H:%M:%SZ', created_at) IS NOT NULL),
    effective_at TEXT NOT NULL
        CHECK (strftime('%Y-%m-%dT%H:%M:%SZ', effective_at) IS NOT NULL),
    UNIQUE (experiment_id, metric_key, version),
    UNIQUE (metric_definition_id, experiment_id),
    UNIQUE (metric_definition_id, version),
    FOREIGN KEY (experiment_id) REFERENCES experiments (experiment_id)
);

CREATE TABLE IF NOT EXISTS assignments (
    assignment_id TEXT PRIMARY KEY,
    experiment_id TEXT NOT NULL,
    variant_id TEXT NOT NULL,
    audience_member_id TEXT NOT NULL,
    assigned_at TEXT NOT NULL
        CHECK (strftime('%Y-%m-%dT%H:%M:%SZ', assigned_at) IS NOT NULL),
    assignment_probability REAL NOT NULL
        CHECK (assignment_probability > 0 AND assignment_probability <= 1),
    randomization_bucket INTEGER NOT NULL CHECK (randomization_bucket BETWEEN 0 AND 999999),
    UNIQUE (experiment_id, audience_member_id),
    UNIQUE (assignment_id, experiment_id),
    CHECK (
        assignment_id =
        'ASG-' || experiment_id || '-' || audience_member_id
    ),
    FOREIGN KEY (variant_id, experiment_id)
        REFERENCES variants (variant_id, experiment_id),
    FOREIGN KEY (audience_member_id) REFERENCES audience_members (audience_member_id)
);

CREATE TABLE IF NOT EXISTS exposure_events (
    exposure_event_id TEXT PRIMARY KEY
        CHECK (
            exposure_event_id GLOB 'EXPOS-2026-[0-9][0-9][0-9][0-9][0-9][0-9]'
        ),
    assignment_id TEXT NOT NULL,
    experiment_id TEXT NOT NULL,
    occurred_at TEXT NOT NULL
        CHECK (strftime('%Y-%m-%dT%H:%M:%SZ', occurred_at) IS NOT NULL),
    event_type TEXT NOT NULL
        CHECK (event_type IN ('client_render', 'server_render')),
    source TEXT NOT NULL CHECK (length(trim(source)) > 0),
    payload_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(payload_json)),
    FOREIGN KEY (assignment_id, experiment_id)
        REFERENCES assignments (assignment_id, experiment_id)
);

CREATE TABLE IF NOT EXISTS conversion_events (
    conversion_event_id TEXT PRIMARY KEY
        CHECK (
            conversion_event_id GLOB 'CONV-2026-[0-9][0-9][0-9][0-9][0-9][0-9]'
        ),
    assignment_id TEXT NOT NULL,
    experiment_id TEXT NOT NULL,
    metric_definition_id TEXT NOT NULL,
    occurred_at TEXT NOT NULL
        CHECK (strftime('%Y-%m-%dT%H:%M:%SZ', occurred_at) IS NOT NULL),
    value REAL NOT NULL,
    currency TEXT,
    source TEXT NOT NULL CHECK (length(trim(source)) > 0),
    payload_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(payload_json)),
    FOREIGN KEY (assignment_id, experiment_id)
        REFERENCES assignments (assignment_id, experiment_id),
    FOREIGN KEY (metric_definition_id, experiment_id)
        REFERENCES metric_definitions (metric_definition_id, experiment_id)
);

CREATE TABLE IF NOT EXISTS guardrail_metrics (
    guardrail_id TEXT PRIMARY KEY
        CHECK (guardrail_id GLOB 'GRD-[0-9][0-9][0-9][0-9][0-9][0-9]'),
    experiment_id TEXT NOT NULL,
    metric_definition_id TEXT NOT NULL,
    comparison_direction TEXT NOT NULL
        CHECK (comparison_direction IN ('higher_is_better', 'lower_is_better')),
    threshold REAL NOT NULL,
    max_regression REAL NOT NULL CHECK (max_regression >= 0),
    severity TEXT NOT NULL CHECK (severity IN ('info', 'warning', 'blocker')),
    enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
    created_at TEXT NOT NULL
        CHECK (strftime('%Y-%m-%dT%H:%M:%SZ', created_at) IS NOT NULL),
    FOREIGN KEY (metric_definition_id, experiment_id)
        REFERENCES metric_definitions (metric_definition_id, experiment_id)
);

CREATE TABLE IF NOT EXISTS experiment_results (
    result_id TEXT PRIMARY KEY
        CHECK (result_id GLOB 'RES-[0-9][0-9][0-9][0-9][0-9][0-9]'),
    experiment_id TEXT NOT NULL,
    metric_definition_id TEXT NOT NULL,
    metric_definition_version INTEGER NOT NULL CHECK (metric_definition_version > 0),
    control_variant_id TEXT NOT NULL,
    treatment_variant_id TEXT NOT NULL,
    computed_at TEXT NOT NULL
        CHECK (strftime('%Y-%m-%dT%H:%M:%SZ', computed_at) IS NOT NULL),
    analysis_plan_version TEXT NOT NULL CHECK (length(trim(analysis_plan_version)) > 0),
    outcome_window_start TEXT NOT NULL
        CHECK (strftime('%Y-%m-%dT%H:%M:%SZ', outcome_window_start) IS NOT NULL),
    outcome_window_end TEXT NOT NULL
        CHECK (strftime('%Y-%m-%dT%H:%M:%SZ', outcome_window_end) IS NOT NULL),
    control_n INTEGER NOT NULL CHECK (control_n >= 0),
    treatment_n INTEGER NOT NULL CHECK (treatment_n >= 0),
    effect_estimate REAL NOT NULL,
    standard_error REAL NOT NULL CHECK (standard_error >= 0),
    confidence_level REAL NOT NULL CHECK (confidence_level > 0 AND confidence_level < 1),
    ci_lower REAL NOT NULL,
    ci_upper REAL NOT NULL,
    p_value REAL NOT NULL CHECK (p_value BETWEEN 0 AND 1),
    srm_p_value REAL CHECK (srm_p_value IS NULL OR srm_p_value BETWEEN 0 AND 1),
    srm_status TEXT NOT NULL CHECK (srm_status IN ('pass', 'warning', 'not_evaluated')),
    guardrail_status TEXT NOT NULL
        CHECK (guardrail_status IN ('pass', 'warning', 'fail', 'not_evaluated')),
    decision TEXT NOT NULL
        CHECK (decision IN ('ship', 'iterate', 'do_not_ship', 'inconclusive')),
    analysis_method TEXT NOT NULL DEFAULT 'intention_to_treat'
        CHECK (analysis_method = 'intention_to_treat'),
    analysis_config_json TEXT NOT NULL CHECK (json_valid(analysis_config_json)),
    input_snapshot_hash TEXT NOT NULL
        CHECK (length(input_snapshot_hash) = 64 AND input_snapshot_hash NOT GLOB '*[^0-9a-f]*'),
    CHECK (control_variant_id <> treatment_variant_id),
    CHECK (outcome_window_end > outcome_window_start),
    CHECK (ci_lower <= effect_estimate AND effect_estimate <= ci_upper),
    FOREIGN KEY (metric_definition_id, experiment_id)
        REFERENCES metric_definitions (metric_definition_id, experiment_id),
    FOREIGN KEY (metric_definition_id, metric_definition_version)
        REFERENCES metric_definitions (metric_definition_id, version),
    FOREIGN KEY (control_variant_id, experiment_id)
        REFERENCES variants (variant_id, experiment_id),
    FOREIGN KEY (treatment_variant_id, experiment_id)
        REFERENCES variants (variant_id, experiment_id)
);

CREATE TRIGGER IF NOT EXISTS metric_definitions_no_update
BEFORE UPDATE ON metric_definitions
BEGIN
    SELECT RAISE(ABORT, 'metric definitions are immutable; insert a new version');
END;

CREATE TRIGGER IF NOT EXISTS metric_definitions_no_delete
BEFORE DELETE ON metric_definitions
BEGIN
    SELECT RAISE(ABORT, 'metric definitions are immutable');
END;

CREATE TRIGGER IF NOT EXISTS exposure_events_no_update
BEFORE UPDATE ON exposure_events
BEGIN
    SELECT RAISE(ABORT, 'exposure event history is immutable');
END;

CREATE TRIGGER IF NOT EXISTS exposure_events_no_delete
BEFORE DELETE ON exposure_events
BEGIN
    SELECT RAISE(ABORT, 'exposure event history is immutable');
END;

CREATE TRIGGER IF NOT EXISTS conversion_events_no_update
BEFORE UPDATE ON conversion_events
BEGIN
    SELECT RAISE(ABORT, 'conversion event history is immutable');
END;

CREATE TRIGGER IF NOT EXISTS conversion_events_no_delete
BEFORE DELETE ON conversion_events
BEGIN
    SELECT RAISE(ABORT, 'conversion event history is immutable');
END;

CREATE TRIGGER IF NOT EXISTS experiment_results_no_update
BEFORE UPDATE ON experiment_results
BEGIN
    SELECT RAISE(ABORT, 'experiment results are immutable; insert a new result');
END;

CREATE TRIGGER IF NOT EXISTS experiment_results_no_delete
BEFORE DELETE ON experiment_results
BEGIN
    SELECT RAISE(ABORT, 'experiment results are immutable');
END;

CREATE TRIGGER IF NOT EXISTS exposure_events_not_before_assignment
BEFORE INSERT ON exposure_events
WHEN NEW.occurred_at < (
    SELECT assigned_at
    FROM assignments
    WHERE assignment_id = NEW.assignment_id
      AND experiment_id = NEW.experiment_id
)
BEGIN
    SELECT RAISE(ABORT, 'exposure cannot precede assignment');
END;

CREATE TRIGGER IF NOT EXISTS conversion_events_not_before_assignment
BEFORE INSERT ON conversion_events
WHEN NEW.occurred_at < (
    SELECT assigned_at
    FROM assignments
    WHERE assignment_id = NEW.assignment_id
      AND experiment_id = NEW.experiment_id
)
BEGIN
    SELECT RAISE(ABORT, 'conversion cannot precede assignment');
END;
