from gengowatcher.web import PaginationParams, app


def test_current_web_api_exposes_core_routes():
    paths = {route.path for route in app.routes}

    assert "/api/status" in paths
    assert "/api/jobs" in paths
    assert "/api/files/upload" in paths


def test_pagination_params_accepts_maximum_limit():
    params = PaginationParams(page=2, limit=PaginationParams.MAX_LIMIT)

    assert params.page == 2
    assert params.limit == 100
