"""
Consistency checks across entries: references that would make the engine fail later (a
category pointing at a rate that is not in effect, a rule naming an unknown component...).
Writes are refused when they add a problem; packs are checked in CI on several dates.
"""

from finance.tax.config_schema import CategoryData, ComponentData, RuleData
from finance.tax.snapshot import ConfigSnapshot


def lint_snapshot(snapshot: ConfigSnapshot) -> set[str]:
    problems: set[str] = set()

    def missing(kind: str, code: str) -> bool:
        return snapshot.find(kind, code) is None

    for entry in snapshot.entries("component"):
        component: ComponentData = entry.data  # type: ignore[assignment]
        if missing("regime", component.regime):
            problems.add(f"component {entry.code}: regime {component.regime} is not in effect")

    for entry in snapshot.entries("category"):
        category: CategoryData = entry.data  # type: ignore[assignment]
        if missing("regime", category.regime):
            problems.add(f"category {entry.code}: regime {category.regime} is not in effect")
        if category.rate and missing("rate", category.rate):
            problems.add(f"category {entry.code}: rate {category.rate} is not in effect")

    for entry in snapshot.entries("rule"):
        rule: RuleData = entry.data  # type: ignore[assignment]
        if missing("regime", rule.regime):
            problems.add(f"rule {entry.code}: regime {rule.regime} is not in effect")
        for output in rule.then:
            component_entry = snapshot.find("component", output.component)
            if component_entry is None:
                problems.add(f"rule {entry.code}: component {output.component} is not in effect")
            elif component_entry.data.regime != rule.regime:  # type: ignore[attr-defined]
                problems.add(f"rule {entry.code}: component {output.component} belongs to another regime")
            if output.rate and missing("rate", output.rate):
                problems.add(f"rule {entry.code}: rate {output.rate} is not in effect")

    for kind in ("jurisdiction", "withholding_section", "deadline"):
        for entry in snapshot.entries(kind):
            regime = entry.data.regime  # type: ignore[attr-defined]
            if missing("regime", regime):
                problems.add(f"{kind} {entry.code}: regime {regime} is not in effect")

    for entry in snapshot.entries("regime"):
        default_category = entry.data.default_category  # type: ignore[attr-defined]
        if default_category and missing("category", default_category):
            problems.add(f"regime {entry.code}: default category {default_category} is not in effect")
    return problems
