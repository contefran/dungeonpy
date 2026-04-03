def _migrate_timers(raw: dict) -> dict:
    """Upgrade old {cond: round_int} format to {cond: [round, initiative]}."""
    return {k: v if isinstance(v, list) else [v, 999] for k, v in raw.items()}


class Combatant:
    
    def __init__(self, name, initiative, hp=None, max_hp=None, conditions=None,
                 condition_timers=None, pos=None, icon=None, notes=''):
        self.name = name
        self.initiative = initiative
        self.hp = hp  # int or None
        self.max_hp = max_hp  # int or None
        self.conditions = conditions or []
        self.condition_timers = condition_timers or {}  # {condition_name: expiry_turn}
        self.pos = pos  # [x, y] or None
        self.icon = icon
        self.notes = notes

    def to_dict(self):
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
        }

    @classmethod
    def from_dict(cls, data):
        return cls(
            name=data.get("name"),
            initiative=data.get("initiative", 0),
            hp=data.get("hp"),
            max_hp=data.get("max_hp"),
            conditions=data.get("conditions", []),
            condition_timers=_migrate_timers(data.get("condition_timers", {})),
            pos=data.get("pos"),
            icon=data.get("icon"),
            notes=data.get("notes", ''),
        )

    def is_down(self):
        return self.hp == 0 or "Unconscious" in self.conditions

    def __repr__(self):
        return f"<Combatant {self.name} (init: {self.initiative})>"
    