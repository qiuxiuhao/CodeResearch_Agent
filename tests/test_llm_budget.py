from concurrent.futures import ThreadPoolExecutor

from backend.app.llm.budget import BudgetManager


def test_provider_request_reservation_is_atomic():
    budget = BudgetManager(max_total_entities=100, max_provider_requests=20)

    def reserve(index: int) -> bool:
        return budget.try_reserve_provider_request("mock", "function_explain", str(index)).allowed

    with ThreadPoolExecutor(max_workers=16) as executor:
        allowed = list(executor.map(reserve, range(200)))

    assert sum(allowed) == 20
    assert budget.snapshot()["reserved_provider_requests"] == 20


def test_entity_and_provider_budgets_are_independent():
    budget = BudgetManager(max_total_entities=2, max_provider_requests=4)
    assert budget.try_reserve_entities("function_explain", 3).reserved == 2
    for index in range(4):
        assert budget.try_reserve_provider_request("mock", "function_explain", str(index)).allowed
    assert not budget.try_reserve_provider_request("mock", "function_explain", "overflow").allowed
