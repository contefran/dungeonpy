class Combatant:
    
    def __init__(self, name, initiative, hp="", conditions=None, pos=None, icon=None):
        self.name = name
        self.initiative = initiative
        self.hp = hp or ""
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
        return cls(
            name=data.get("name"),
            initiative=data.get("initiative", 0),
            hp=data.get("hp", ""),
            conditions=data.get("conditions", []),
            pos=data.get("pos"),
            icon=data.get("icon")
        )

    def is_down(self):
        return self.hp == "0" or "Down" in self.conditions

    def __repr__(self):
        return f"<Combatant {self.name} (init: {self.initiative})>"
    