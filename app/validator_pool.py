"""
Uruchamia równolegle N niezależnych walidatorów dla żółtej akcji i zbiera
głosy (PLAN-WDROZENIA.md sekcja 3, SKRYPTY.md kategoria C). Próg zgody
(np. 2 z 3) pochodzi z approval_policy.yaml przez risk_classifier.py.
"""

from concurrent.futures import ThreadPoolExecutor

from validators import ALL_VALIDATORS


def run_validators(task, execution_result, requirements, validators=None):
    """requirements: {"validator_count": int, "required_agreement": int}
    (risk_classifier.validator_requirements). Zwraca pełny wynik + decyzję."""
    validators = validators or ALL_VALIDATORS
    names = list(validators.keys())[: requirements.get("validator_count", len(validators))]

    with ThreadPoolExecutor(max_workers=len(names) or 1) as pool:
        futures = [pool.submit(validators[name], task, execution_result) for name in names]
        results = [f.result() for f in futures]

    agreement = sum(1 for r in results if r["approved"])
    required = requirements.get("required_agreement", len(names))
    auto_approved = agreement >= required

    return {
        "results": results,
        "agreement": agreement,
        "required": required,
        "total": len(names),
        "auto_approved": auto_approved,
    }


if __name__ == "__main__":
    sample_task = {"acceptance_criteria": ["coś"], "max_ai_cost_usd": 1.0}
    sample_execution = {"cost_usd": 0.2, "acceptance_notes": "spełnione"}
    requirements = {"validator_count": 3, "required_agreement": 2}
    print(run_validators(sample_task, sample_execution, requirements))
