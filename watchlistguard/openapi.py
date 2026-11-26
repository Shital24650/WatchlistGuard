"""OpenAPI 3.0 contract for the routes implemented by app.py."""


def openapi_document():
    """Return the API contract as a JSON-serializable Python object."""
    error = {
        "type": "object",
        "required": ["error"],
        "properties": {"error": {"type": "string"}},
    }
    return {
        "openapi": "3.0.3",
        "info": {
            "title": "WatchlistGuard API",
            "version": "1.0.0",
            "description": (
                "Idempotent CSV ingestion skips identical SHA-256 files and deduplicates changed files by unique transaction_ref. "
                "Educational transaction-screening demo using synthetic data only. "
                "Do not submit personal, banking, or production customer information."
            ),
        },
        "servers": [{"url": "/"}],
        "tags": [
            {"name": "Health"},
            {"name": "Transactions"},
            {"name": "Screening"},
            {"name": "Audit"},
        ],
        "paths": {
            "/health": {
                "get": {
                    "tags": ["Health"],
                    "summary": "Check application and SQLite availability",
                    "responses": {
                        "200": {"description": "Application is available"},
                        "503": {"description": "Database is unavailable"},
                    },
                }
            },
            "/api/openapi.json": {
                "get": {
                    "summary": "Retrieve this OpenAPI document",
                    "responses": {"200": {"description": "OpenAPI 3.0 document"}},
                }
            },
            "/api/docs": {
                "get": {
                    "summary": "Open interactive Swagger UI documentation",
                    "responses": {"200": {"description": "Swagger UI HTML"}},
                }
            },
            "/api/upload": {
                "post": {
                    "tags": ["Transactions"],
                    "summary": "Validate and ingest a CSV file",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "multipart/form-data": {
                                "schema": {
                                    "type": "object",
                                    "required": ["file"],
                                    "properties": {
                                        "file": {"type": "string", "format": "binary"}
                                    },
                                }
                            }
                        },
                    },
                    "responses": {
                        "200": {
                            "description": "CSV processed",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "message": {"type": "string"},
                                            "inserted": {"type": "integer"},
                                            "rejected": {"type": "integer"},
                                            "duplicates": {"type": "integer"},
                                            "skipped_file": {"type": "integer"},
                                        },
                                    }
                                }
                            },
                        },
                        "400": {"description": "Missing, invalid, or malformed CSV", "content": {"application/json": {"schema": error}}},
                        "413": {"description": "Upload exceeds 1 MB", "content": {"application/json": {"schema": error}}},
                        "500": {"description": "Unexpected processing error", "content": {"application/json": {"schema": error}}},
                    },
                }
            },
            "/api/screen": {
                "post": {
                    "tags": ["Screening"],
                    "summary": "Screen all pending transactions",
                    "responses": {
                        "200": {
                            "description": "Screening completed",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "required": ["message", "screened"],
                                        "properties": {
                                            "message": {"type": "string"},
                                            "screened": {"type": "integer"},
                                        },
                                    }
                                }
                            },
                        },
                        "500": {"description": "Screening failed", "content": {"application/json": {"schema": error}}},
                    },
                }
            },
            "/api/report": {
                "get": {
                    "tags": ["Transactions"],
                    "summary": "Return a paginated screening report",
                    "description": "Results are ordered by transaction insertion ID. Defaults: page=1, page_size=20.",
                    "parameters": [
                        {"name": "page", "in": "query", "required": False, "schema": {"type": "integer", "minimum": 1, "default": 1}},
                        {"name": "page_size", "in": "query", "required": False, "schema": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20}},
                        {"name": "risk_level", "in": "query", "required": False, "schema": {"type": "string", "enum": ["PENDING", "LOW", "MEDIUM", "HIGH"]}},
                        {"name": "screening_status", "in": "query", "required": False, "schema": {"type": "string", "enum": ["PENDING", "SCREENED"]}},
                    ],
                    "responses": {
                        "200": {
                            "description": "Filtered page and pagination metadata",
                            "content": {"application/json": {"schema": {
                                "type": "object",
                                "required": ["count", "results", "pagination"],
                                "properties": {
                                    "count": {"type": "integer", "description": "Total matching rows"},
                                    "results": {"type": "array", "items": {"type": "object", "properties": {
                                        "transaction_ref": {"type": "string"},
                                        "customer_name": {"type": "string"},
                                        "amount": {"type": "number"},
                                        "currency": {"type": "string"},
                                        "risk_level": {"type": "string", "enum": ["PENDING", "LOW", "MEDIUM", "HIGH"]},
                                        "risk_score": {"type": "integer"},
                                        "match_type": {"type": "string"},
                                        "explanation": {"type": "string"},
                                    }}},
                                    "pagination": {"type": "object", "required": ["page", "page_size", "total", "total_pages"],
                                        "properties": {
                                            "page": {"type": "integer"}, "page_size": {"type": "integer"},
                                            "total": {"type": "integer"}, "total_pages": {"type": "integer"},
                                        }},
                                },
                            }}},
                        },
                        "400": {"description": "Invalid query parameter", "content": {"application/json": {"schema": error}}},
                        "500": {"description": "Report generation failed", "content": {"application/json": {"schema": error}}},
                    },
                }
            },
            "/api/audit/verify": {
                "post": {
                    "tags": ["Audit"],
                    "summary": "Verify the SHA-256 audit chain and record the verification event",
                    "responses": {
                        "200": {
                            "description": "Audit chain is valid",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "required": ["valid", "message"],
                                        "properties": {
                                            "valid": {"type": "boolean"},
                                            "message": {"type": "string"},
                                        },
                                    }
                                }
                            },
                        },
                        "409": {"description": "Audit chain verification failed", "content": {"application/json": {"schema": {"type": "object", "properties": {"valid": {"type": "boolean"}, "message": {"type": "string"}}}}}},
                        "500": {"description": "Audit verification error", "content": {"application/json": {"schema": error}}},
                    },
                }
            },
        },
    }
