from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CURRENT_SPEC = ROOT / "outputs/原系统融合重构执行/evidence/route_product_spec/route_product_spec.json"
TARGET_SPEC = ROOT / "outputs/原系统融合重构执行/evidence/target_product_spec/target_product_route_spec.json"
FUSION_MATRIX = ROOT / "outputs/原系统融合重构执行/evidence/fusion_scope_matrix/fusion_scope_matrix.json"
CONTRACT = ROOT / "frontend/src/router/routeMigrationContract.json"
ROUTER = ROOT / "frontend/src/router/index.js"
APP = ROOT / "frontend/src/App.vue"
LEDGER_DIR = (
    ROOT
    / "outputs/原系统融合重构执行/evidence/context_recovery/atomic_requirement_ledgers"
    / "EDUMATRIX-F9-F10-CONTEXT-SAFE-FUSION-COMPLETION"
)


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _matches_target(destination: str, target_patterns: set[str]) -> bool:
    for pattern in target_patterns:
        expression = re.sub(r":[^/]+", r"[^/]+", re.escape(pattern))
        expression = expression.replace(r"\[\^/\]\+", "[^/]+")
        if re.fullmatch(expression, destination):
            return True
    return False


def test_runtime_contract_reconciles_every_authoritative_current_route():
    current = _load(CURRENT_SPEC)
    contract = _load(CONTRACT)

    current_paths = [item["path"] for item in current]
    contract_paths = [item["sourcePath"] for item in contract]
    assert contract_paths == current_paths
    assert len(contract_paths) == len(set(contract_paths))

    required = {
        "sourcePath",
        "sourceName",
        "disposition",
        "destination",
        "roles",
        "featureFlag",
        "enabledByDefault",
        "rollbackRoute",
        "notice",
    }
    allowed_roles = {"student", "teacher", "admin"}
    for item in contract:
        assert required <= item.keys(), item["sourcePath"]
        assert item["disposition"]
        assert item["destination"].startswith("/")
        assert item["featureFlag"].startswith("f10.route.")
        assert item["rollbackRoute"] == item["sourcePath"]
        assert set(item["roles"]) <= allowed_roles

    feature_flags = [item["featureFlag"] for item in contract]
    assert len(feature_flags) == len(set(feature_flags))


def test_every_destination_is_a_real_target_pattern_or_the_recovery_surface():
    targets = {item["path"] for item in _load(TARGET_SPEC)}
    contract = _load(CONTRACT)

    for item in contract:
        destinations = [item["destination"], *(item.get("roleDestinations") or {}).values()]
        for destination in destinations:
            assert destination == "/context-recovery" or _matches_target(destination, targets), (
                item["sourcePath"],
                destination,
            )
        if not item["enabledByDefault"]:
            assert item["destination"] == "/context-recovery"
            assert item.get("recoveryReason") in {"feature_internal", "feature_deferred", "feature_removed"}


def test_chat_capability_routes_converge_on_their_approved_learning_spaces():
    by_path = {item["sourcePath"]: item for item in _load(CONTRACT)}
    assert by_path["/assessment"]["destination"] == "/workspace/assessment/entry"
    assert by_path["/formal-exams"]["destination"] == "/workspace/assessment/exams"
    assert by_path["/speech-training"]["destination"] == "/workspace/feynman/legacy"
    assert by_path["/interactive-lab"]["destination"] == "/workspace/resources/models/legacy"
    assert by_path["/resources"]["destination"] == "/workspace/resources"
    assert by_path["/media-context"]["destination"] == "/learn"


def test_internal_deferred_and_removed_workbenches_do_not_render_as_normal_routes():
    contract = _load(CONTRACT)
    hidden_tokens = ("internal", "deferred", "removed")
    hidden = [item for item in contract if any(token in item["disposition"] for token in hidden_tokens)]
    assert hidden

    router_source = ROUTER.read_text(encoding="utf-8")
    app_source = APP.read_text(encoding="utf-8")
    for item in hidden:
        if item["enabledByDefault"]:
            continue
        assert item["destination"] == "/context-recovery"
        assert f"path: '{item['sourcePath']}'" not in router_source
        assert item["sourcePath"] not in app_source


def test_router_consumes_the_contract_and_exposes_migration_metadata():
    source = ROUTER.read_text(encoding="utf-8")
    for fragment in (
        "import routeMigrationContract from './routeMigrationContract.json'",
        "CURRENT_ROUTE_MIGRATION_CONTRACT.map",
        "!TARGET_ROUTE_PATH_SET.has(contract.sourcePath)",
        ".map(legacy)",
        "...legacyRoutes",
        "disposition: contract.disposition",
        "destination: contract.destination",
        "featureFlag: contract.featureFlag",
        "rollbackRoute: contract.rollbackRoute",
        "sourceRoute: contract.sourcePath",
        "legacy_path: contract.sourcePath",
        "return_to: to.fullPath",
    ):
        assert fragment in source
    # History has a dedicated compatibility record; the other legacy routes
    # continue to come from the migration contract rather than parallel lists.
    handwritten_legacy_paths = re.findall(r"\blegacy\(\s*['\"]([^'\"]+)", source)
    assert handwritten_legacy_paths == ["/history"]

    target_block = re.search(
        r"export const TARGET_ROUTE_PATHS = \[(.*?)\n\]",
        source,
        flags=re.DOTALL,
    )
    assert target_block
    runtime_targets = re.findall(r"'([^']+)'", target_block.group(1))
    assert len(runtime_targets) == len(set(runtime_targets))
    # New entry points may extend the historical snapshot. Every current
    # compatibility destination must still resolve within the current targets.
    for item in _load(CONTRACT):
        for destination in [item["destination"], *(item.get("roleDestinations") or {}).values()]:
            assert destination == "/context-recovery" or _matches_target(destination, set(runtime_targets)), (
                item["sourcePath"], destination,
            )


def test_endpoint_and_model_fusion_records_keep_role_value_and_boundary():
    matrix = _load(FUSION_MATRIX)
    assert matrix["route_count"] == len(matrix["routes"])
    assert matrix["model_count"] == len(matrix["models"])
    for record in [*matrix["routes"], *matrix["models"]]:
        assert record["disposition"]
        assert record["destination"]
        assert record["role"]
        assert record["user_value"]
        assert record["boundary"]


def test_f10_t01_uses_no_unreadable_image_as_route_evidence():
    ledgers = list(LEDGER_DIR.glob("F10-T01_*.json"))
    assert len(ledgers) == 1
    ledger = _load(ledgers[0])
    assert {entry["atomic_requirement_id"] for entry in ledger["entries"]} == {
        "G22-R12",
        "G25-R01",
        "G25-R02",
        "G25-R03",
        "G25-R04",
        "G28-R01",
        "G28-R02",
        "G28-R03",
        "G28-R04",
        "G28-R05",
        "G28-R06",
        "G28-R07",
    }
    assert all(entry["source"]["source_images"] == [] for entry in ledger["entries"])

