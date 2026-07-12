import pytest
from pydantic import ValidationError

from gengowatcher.web import PaginationParams, StoredFileUploadResponse


def test_pagination_params_defaults_and_bounds():
    params = PaginationParams()

    assert (params.page, params.limit) == (1, 20)
    with pytest.raises(ValueError):
        PaginationParams(page=0)
    with pytest.raises(ValueError):
        PaginationParams(limit=101)


def test_stored_file_upload_response_validates_nested_file():
    response = StoredFileUploadResponse.model_validate(
        {
            "status": "success",
            "file": {
                "stored_name": "job.txt",
                "original_name": "job.txt",
                "size_bytes": 12,
                "modified_at": 1.0,
                "download_url": "/api/files/job.txt",
            },
        }
    )

    assert response.file.stored_name == "job.txt"
    with pytest.raises(ValidationError):
        StoredFileUploadResponse.model_validate({"status": "success"})
