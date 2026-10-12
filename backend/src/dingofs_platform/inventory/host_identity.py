"""Canonical, explicit host matching without DNS lookups or arbitrary tie-breaking."""

import ipaddress
import re

from sqlalchemy import delete, select

from .models import Machine, MachineHostIdentifier

_HOST_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9_-]{0,61}[a-z0-9])?\Z")


def normalize_host(value: str) -> str:
    value = value.strip().lower().removesuffix(".")
    if not value or len(value) > 253 or "%" in value:
        raise ValueError("invalid hostname or IP")
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        # A malformed IP must not be treated as an unrelated DNS hostname.
        if ":" in value or re.fullmatch(r"[0-9]+(?:\.[0-9]+){3}", value):
            raise ValueError("invalid hostname or IP") from None
    if any(not _HOST_LABEL.fullmatch(label) for label in value.split(".")):
        raise ValueError("invalid hostname or IP")
    return value


def sync_host_identifiers(db, machine: Machine) -> None:
    """Update the lookup index in the same transaction as a machine mutation."""
    db.execute(
        delete(MachineHostIdentifier).where(
            MachineHostIdentifier.machine_id == machine.id
        )
    )
    for identifier in dict.fromkeys(
        normalize_host(value) for value in [machine.address, *(machine.aliases or [])]
    ):
        db.add(MachineHostIdentifier(machine_id=machine.id, identifier=identifier))
    db.flush()


def resolve_hosts(db, hosts) -> dict[str, list[Machine]]:
    """Return every active match, including conflicts, with one batched query."""
    normalized = {}
    result = {host: [] for host in hosts}
    for host in result:
        try:
            normalized[host] = normalize_host(host)
        except ValueError:
            continue
    if not normalized:
        return result
    matches = {}
    rows = db.execute(
        select(MachineHostIdentifier.identifier, Machine)
        .join(Machine, MachineHostIdentifier.machine_id == Machine.id)
        .where(
            MachineHostIdentifier.identifier.in_(set(normalized.values())),
            Machine.archived == False,
        )
        .order_by(Machine.id)
    )
    for identifier, machine in rows:
        matches.setdefault(identifier, {})[machine.id] = machine
    for host, identifier in normalized.items():
        result[host] = list(matches.get(identifier, {}).values())
    return result


def resolve_host(db, host: str) -> list[Machine]:
    """Only a one-element result authorizes a unique machine association."""
    return resolve_hosts(db, [host])[host]


def alias_conflicts(db, machine: Machine) -> dict[str, list[dict]]:
    conflicts = {}
    for alias, matches in resolve_hosts(db, machine.aliases or []).items():
        others = [
            {
                "id": match.id,
                "name": match.name,
                "address": match.address,
                "ssh_port": match.ssh_port,
            }
            for match in matches
            if match.id != machine.id
        ]
        if others:
            conflicts[alias] = others
    return conflicts
