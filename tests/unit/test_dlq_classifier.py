import pytest
from services.dlq_classifier.handler import (
    classify_error, get_retry_count, should_retry
)

def test_classify_throttling():
    assert classify_error("ThrottlingException occurred") == "retryable"

def test_classify_too_many_requests():
    assert classify_error("Lambda.TooManyRequestsException") == "retryable"

def test_classify_validation_error():
    assert classify_error("ValidationError: invalid input") == "fatal"

def test_classify_unknown():
    assert classify_error("Something weird happened") == "unknown"

def test_classify_case_insensitive():
    assert classify_error("throttlingexception") == "retryable"

def test_get_retry_count_zero():
    message = {"messageAttributes": {}}
    assert get_retry_count(message) == 0

def test_get_retry_count_existing():
    message = {
        "messageAttributes": {
            "RetryCount": {"stringValue": "2", "dataType": "Number"}
        }
    }
    assert get_retry_count(message) == 2

def test_should_retry_retryable_first():
    assert should_retry("retryable", 0) is True

def test_should_retry_retryable_max():
    assert should_retry("retryable", 3) is False

def test_should_retry_fatal():
    assert should_retry("fatal", 0) is False

def test_should_retry_unknown():
    assert should_retry("unknown", 0) is False
