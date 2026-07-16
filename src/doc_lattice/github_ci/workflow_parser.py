"""Boundary module: validate GitHub Actions YAML into a typed audit model."""

from pathlib import Path
from typing import Any, Never

from ruamel.yaml import YAML
from ruamel.yaml.constructor import DuplicateKeyError
from ruamel.yaml.error import YAMLError
from ruamel.yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode

from ..error_types import ConfigError
from .model import (
    PermissionValue,
    WorkflowDocument,
    WorkflowJob,
    WorkflowScalar,
    WorkflowStep,
    WorkflowTrigger,
)


def parse_workflow(path: Path, text: str) -> WorkflowDocument:
    """Validate workflow YAML into the typed subset required by audit.

    Args:
        path: Display path used in the returned model and any validation error.
        text: Complete workflow YAML text.

    Returns:
        A typed workflow document containing the fields required by policy audit.

    Raises:
        ConfigError: If the YAML is malformed or has a shape the audit cannot inspect.
    """
    yaml = YAML(typ="safe")
    yaml.allow_duplicate_keys = False
    try:
        syntax_tree = yaml.compose(text)
        _reject_duplicate_keys(syntax_tree, path, set())
        raw: Any = yaml.load(text)
    except YAMLError as exc:
        detail = (
            "duplicate YAML mapping key" if isinstance(exc, DuplicateKeyError) else "malformed YAML"
        )
        raise ConfigError(f"cannot parse GitHub workflow {path}: {detail}") from exc

    root = _require_mapping(raw, path, ())
    scalars = tuple(_collect_scalars(root, path, (), set()))
    triggers = _parse_triggers(root["on"], path) if "on" in root else ()
    permissions = _parse_permissions(root.get("permissions"), path, ("permissions",))
    if "jobs" not in root:
        _invalid(path, ("jobs",), "must be a mapping")
    jobs = _parse_jobs(root["jobs"], path)
    return WorkflowDocument(
        path=path,
        triggers=triggers,
        permissions=permissions,
        jobs=jobs,
        scalars=scalars,
    )


def _reject_duplicate_keys(node: Node | None, workflow_path: Path, active_nodes: set[int]) -> None:
    if node is None or isinstance(node, ScalarNode):
        return
    node_id = id(node)
    if node_id in active_nodes:
        return
    active_nodes.add(node_id)
    if isinstance(node, MappingNode):
        seen: set[tuple[str, str]] = set()
        for key_node, value_node in node.value:
            if isinstance(key_node, ScalarNode):
                marker = (key_node.tag, key_node.value)
                if marker in seen:
                    raise ConfigError(
                        f"cannot parse GitHub workflow {workflow_path}: duplicate YAML mapping key"
                    )
                seen.add(marker)
            _reject_duplicate_keys(key_node, workflow_path, active_nodes)
            _reject_duplicate_keys(value_node, workflow_path, active_nodes)
    elif isinstance(node, SequenceNode):
        for value_node in node.value:
            _reject_duplicate_keys(value_node, workflow_path, active_nodes)
    active_nodes.remove(node_id)


def _parse_triggers(raw: Any, workflow_path: Path) -> tuple[WorkflowTrigger, ...]:
    if isinstance(raw, str):
        return (WorkflowTrigger(name=raw, shape="null", branches=None),)
    if isinstance(raw, list):
        triggers: list[WorkflowTrigger] = []
        for index, event in enumerate(raw):
            if not isinstance(event, str):
                _invalid(workflow_path, ("on", str(index)), "event name must be a string")
            triggers.append(WorkflowTrigger(name=event, shape="null", branches=None))
        return tuple(triggers)
    if not isinstance(raw, dict):
        _invalid(workflow_path, ("on",), "must be a string, sequence, or mapping")

    triggers = []
    for event, config in raw.items():
        if config is None:
            triggers.append(WorkflowTrigger(name=event, shape="null", branches=None))
        elif isinstance(config, dict):
            branches = (
                _parse_branches(config["branches"], workflow_path, ("on", event, "branches"))
                if "branches" in config
                else None
            )
            triggers.append(WorkflowTrigger(name=event, shape="mapping", branches=branches))
        elif isinstance(config, list):
            triggers.append(WorkflowTrigger(name=event, shape="sequence", branches=None))
        else:
            _invalid(
                workflow_path,
                ("on", event),
                "event configuration must be null, a mapping, or a sequence",
            )
    return tuple(triggers)


def _parse_branches(raw: Any, workflow_path: Path, yaml_path: tuple[str, ...]) -> tuple[str, ...]:
    if isinstance(raw, str):
        return (raw,)
    if isinstance(raw, list) and all(isinstance(branch, str) for branch in raw):
        return tuple(raw)
    _invalid(workflow_path, yaml_path, "branches must be a string or a sequence of strings")


def _parse_permissions(
    raw: Any, workflow_path: Path, yaml_path: tuple[str, ...]
) -> PermissionValue:
    if raw is None or isinstance(raw, str):
        return raw
    if not isinstance(raw, dict):
        _invalid(workflow_path, yaml_path, "permissions must be a string, mapping, or null")
    pairs: list[tuple[str, str]] = []
    for key, value in raw.items():
        if not isinstance(value, str):
            _invalid(
                workflow_path,
                (*yaml_path, key),
                "permission value must be a string",
            )
        pairs.append((key, value))
    return tuple(sorted(pairs))


def _parse_jobs(raw: Any, workflow_path: Path) -> tuple[WorkflowJob, ...]:
    jobs = _require_mapping(raw, workflow_path, ("jobs",))
    parsed: list[WorkflowJob] = []
    for job_id, raw_job in jobs.items():
        job_path = ("jobs", job_id)
        job = _require_mapping(raw_job, workflow_path, job_path)
        permissions = _parse_permissions(
            job.get("permissions"), workflow_path, (*job_path, "permissions")
        )
        env = (
            _parse_scalar_mapping(job["env"], workflow_path, (*job_path, "env"))
            if "env" in job
            else ()
        )
        steps = (
            _parse_steps(job["steps"], workflow_path, (*job_path, "steps"))
            if "steps" in job
            else ()
        )
        parsed.append(
            WorkflowJob(
                job_id=job_id,
                if_condition=_optional_audited_string(
                    job.get("if"), workflow_path, (*job_path, "if")
                ),
                environment=job.get("environment")
                if isinstance(job.get("environment"), str)
                else None,
                runs_on=job.get("runs-on") if isinstance(job.get("runs-on"), str) else None,
                permissions=permissions,
                env=env,
                steps=steps,
            )
        )
    return tuple(parsed)


def _parse_steps(
    raw: Any, workflow_path: Path, yaml_path: tuple[str, ...]
) -> tuple[WorkflowStep, ...]:
    if not isinstance(raw, list):
        _invalid(workflow_path, yaml_path, "steps must be a sequence of mappings")
    parsed: list[WorkflowStep] = []
    for index, raw_step in enumerate(raw):
        step_path = (*yaml_path, str(index))
        step = _require_mapping(raw_step, workflow_path, step_path)
        env = (
            _parse_scalar_mapping(step["env"], workflow_path, (*step_path, "env"))
            if "env" in step
            else ()
        )
        with_values = (
            _parse_scalar_mapping(step["with"], workflow_path, (*step_path, "with"))
            if "with" in step
            else ()
        )
        parsed.append(
            WorkflowStep(
                index=index,
                step_id=_optional_audited_string(step.get("id"), workflow_path, (*step_path, "id")),
                name=_optional_audited_string(
                    step.get("name"), workflow_path, (*step_path, "name")
                ),
                uses=_optional_audited_string(
                    step.get("uses"), workflow_path, (*step_path, "uses")
                ),
                run=_optional_audited_string(step.get("run"), workflow_path, (*step_path, "run")),
                env=env,
                with_values=with_values,
            )
        )
    return tuple(parsed)


def _parse_scalar_mapping(
    raw: Any, workflow_path: Path, yaml_path: tuple[str, ...]
) -> tuple[tuple[str, str], ...]:
    mapping = _require_mapping(raw, workflow_path, yaml_path)
    pairs: list[tuple[str, str]] = []
    for key, value in mapping.items():
        pairs.append((key, _normalize_scalar(value, workflow_path, (*yaml_path, key))))
    return tuple(sorted(pairs))


def _normalize_scalar(raw: Any, workflow_path: Path, yaml_path: tuple[str, ...]) -> str:
    if isinstance(raw, str):
        return raw
    if isinstance(raw, bool):
        return "true" if raw else "false"
    if isinstance(raw, (int, float)):
        return str(raw)
    _invalid(workflow_path, yaml_path, "value must be a string, boolean, or number")


def _optional_audited_string(
    raw: Any, workflow_path: Path, yaml_path: tuple[str, ...]
) -> str | None:
    if isinstance(raw, str):
        return raw
    if isinstance(raw, (dict, list, set, tuple)):
        _invalid(workflow_path, yaml_path, "value must be a scalar")
    return None


def _require_mapping(raw: Any, workflow_path: Path, yaml_path: tuple[str, ...]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        detail = "workflow root must be a mapping" if not yaml_path else "must be a mapping"
        _invalid(workflow_path, yaml_path, detail)
    for key in raw:
        if not isinstance(key, str):
            _invalid(workflow_path, yaml_path, "mapping keys must be strings")
    return raw


def _collect_scalars(
    raw: Any,
    workflow_path: Path,
    yaml_path: tuple[str, ...],
    active_containers: set[int],
) -> list[WorkflowScalar]:
    if isinstance(raw, str):
        return [WorkflowScalar(path=yaml_path, value=raw)]
    if isinstance(raw, dict):
        container_id = id(raw)
        if container_id in active_containers:
            _invalid(workflow_path, yaml_path, "recursive YAML aliases are not supported")
        active_containers.add(container_id)
        scalars: list[WorkflowScalar] = []
        for key, value in raw.items():
            if not isinstance(key, str):
                _invalid(workflow_path, yaml_path, "mapping keys must be strings")
            scalars.extend(
                _collect_scalars(value, workflow_path, (*yaml_path, key), active_containers)
            )
        active_containers.remove(container_id)
        return scalars
    if isinstance(raw, list):
        container_id = id(raw)
        if container_id in active_containers:
            _invalid(workflow_path, yaml_path, "recursive YAML aliases are not supported")
        active_containers.add(container_id)
        scalars = []
        for index, value in enumerate(raw):
            scalars.extend(
                _collect_scalars(
                    value,
                    workflow_path,
                    (*yaml_path, str(index)),
                    active_containers,
                )
            )
        active_containers.remove(container_id)
        return scalars
    if isinstance(raw, (set, tuple)):
        _invalid(workflow_path, yaml_path, "unsupported YAML container")
    return []


def _invalid(workflow_path: Path, yaml_path: tuple[str, ...], detail: str) -> Never:
    location = ".".join(yaml_path) if yaml_path else "root"
    raise ConfigError(f"invalid GitHub workflow {workflow_path} at {location}: {detail}")
