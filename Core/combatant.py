class Combatant:
    
    def __init__(self, name, initiative, hp=None, conditions=None, pos=None, icon=None):
        self.name = name
        self.initiative = initiative
        self.hp = hp  # int or None
        self.conditions = conditions or []
        self.pos = pos  # [x, y] or None
        self.icon = icon

    def to_dict(self):
        return {
            "name": self.name,
            "initiative": self.initiative,
            "hp": self.hp,
            "conditions": self.conditions,
            "pos": self.pos,
            "icon": self.icon
        }

    @classmethod
    def from_dict(cls, data):
        raw_hp = data.get("hp", None)
        if isinstance(raw_hp, str):
            hp = int(raw_hp) if raw_hp.strip() else None  # handle old string-format saves
        else:
            hp = raw_hp  # int or None
        return cls(
            name=data.get("name"),
            initiative=data.get("initiative", 0),
            hp=hp,
            conditions=data.get("conditions", []),
            pos=data.get("pos"),
            icon=data.get("icon")
        )

    def is_down(self):
        return self.hp == 0 or "Down" in self.conditions

    def __repr__(self):
        return f"<Combatant {self.name} (init: {self.initiative})>"
    