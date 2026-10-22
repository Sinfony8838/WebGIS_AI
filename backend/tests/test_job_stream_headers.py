from unittest.mock import patch
from backend.app import main

def test_job_stream_disables_proxy_transformation_without_weakening_access_checks():
    request = object()
    with patch.object(main, "_require_job_access") as access:
        response = main.stream_job("job-fixture", request)
    access.assert_called_once_with(request, "job-fixture")
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-store, no-transform"
    assert response.headers["x-accel-buffering"] == "no"
