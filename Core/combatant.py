"""
combatant.py — Data class for a single combat participant.

Each Combatant holds the initiative-tracker state (name, initiative, HP,
conditions) and the map state (grid position, icon, size).  Instances are
shared by reference between the Tracker and MapManager in local play so that
a single mutation is visible to both components immediately.
"""


def _migrate_timers(raw: dict) -> dict:
    """Upgrade old {cond: round_int} format to {cond: [round, initiative]}."""
    return {k: v if isinstance(v, list) else [v, 999] for k, v in raw.items()}


class Combatant:
    """A single participant in the combat encounter.

    Attributes:
        name: Unique display name used as the primary key throughout the system.
        initiative: Roll result; combatants are sorted highest-first.
        hp: Current hit points, or None if HP is not being tracked.
        max_hp: Maximum hit points, or None if not set.
        conditions: List of active condition names (e.g. ``["Poisoned", "Prone"]``).
        condition_timers: Maps condition name to ``[expiry_round, expiry_initiative]``.
        pos: ``[col, row]`` top-left tile on the map, or None if not yet placed.
        icon: Filename (no path) of the token image resolved against ``Assets/Combatants/``.
        notes: Freeform DM notes shown in the tracker detail pane.
        is_pc: True for player characters — PCs persist across map loads.
        size: Token footprint in tiles on one side (1 = normal, 2 = large, 3 = huge).
    """

    def __init__(
        self,
        name,
        initiative,
        hp=None,
        max_hp=None,
        conditions=None,
        condition_timers=None,
        pos=None,
        icon=None,
        notes="",
        is_pc=False,
        size=1,
        color=None,
        portrait_source=None,
    ):
        self.name = name
        self.initiative = initiative
        self.hp = hp  # int or None
        self.max_hp = max_hp  # int or None
        self.conditions = conditions or []
        self.condition_timers = condition_timers or {}  # {condition_name: expiry_turn}
        self.pos = pos  # [x, y] or None — top-left corner of the size×size footprint
        self.icon = icon
        self.notes = notes
        self.is_pc = is_pc  # True → kept across map loads; False → removed on new map
        self.size = max(
            1, int(size)
        )  # footprint side length in tiles (1=normal, 2=large, 3=huge…)
        self.color = color                    # hex string e.g. "#4488FF", None until claimed
        self.portrait_source = portrait_source  # source portrait filename used to build icon

    def to_dict(self) -> dict:
        """Serialise to a JSON-compatible dict (used for save files and wire protocol)."""
        return {
            "name": self.name,
            "initiative": self.initiative,
            "hp": self.hp,
            "max_hp": self.max_hp,
            "conditions": self.conditions,
            "condition_timers": self.condition_timers,
            "pos": self.pos,
            "icon": self.icon,
            "notes": self.notes,
            "is_pc": self.is_pc,
            "size": self.size,
            "color": self.color,
            "portrait_source": self.portrait_source,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Combatant":
        """Deserialise from a dict produced by ``to_dict()`` or a save file."""
        return cls(
            name=data.get("name"),
            initiative=data.get("initiative", 0),
            hp=data.get("hp"),
            max_hp=data.get("max_hp"),
            conditions=data.get("conditions", []),
            condition_timers=_migrate_timers(data.get("condition_timers", {})),
            pos=data.get("pos"),
            icon=data.get("icon"),
            notes=data.get("notes", ""),
            is_pc=data.get("is_pc", False),
            size=data.get("size", 1),
            color=data.get("color"),
            portrait_source=data.get("portrait_source"),
        )

    def is_down(self) -> bool:
        """Return True if the combatant is at 0 HP or has the Unconscious condition."""
        return self.hp == 0 or "Unconscious" in self.conditions

    def __repr__(self):
        return f"<Combatant {self.name} (init: {self.initiative})>"
