"""Custom REST connector: the OpenAPI reader (3.x JSON/YAML with local $ref and cycles, Swagger 2 basic)."""

from __future__ import annotations

import json

import pytest

from app.services.rest_connector.openapi_reader import OpenApiError, read_openapi

OPENAPI_YAML = """
openapi: 3.0.3
info: {title: Ticket API, description: Tickets of the service desk}
servers:
  - url: https://{tenant}.tickets.example.test/api
    variables: {tenant: {default: acme}}
components:
  securitySchemes:
    oauth:
      type: oauth2
      flows:
        clientCredentials:
          tokenUrl: https://auth.example.test/token
          scopes: {tickets.read: read}
  parameters:
    Group:
      name: assignment_group
      in: query
      schema: {type: string}
  schemas:
    Node:
      type: object
      properties:
        name: {type: string}
        children:
          type: array
          items: {$ref: '#/components/schemas/Node'}
paths:
  /tickets:
    parameters:
      - $ref: '#/components/parameters/Group'
    get:
      operationId: listTickets
      summary: List tickets
      parameters:
        - {name: limit, in: query, schema: {type: integer}}
        - {name: Authorization, in: header, schema: {type: string}}
    post:
      operationId: createTicket
      requestBody:
        required: true
        content:
          application/json:
            schema: {$ref: '#/components/schemas/Node'}
  /tickets/{id}:
    get:
      operationId: getTicket
      parameters:
        - {name: id, in: path, schema: {type: string}}
"""


def test_openapi3_yaml_with_ref_and_cycle_is_read():
    spec = read_openapi(OPENAPI_YAML)

    assert spec["servers"] == ["https://acme.tickets.example.test/api"]
    assert spec["auth"]["scheme"] == "oauth2_client_credentials"
    assert spec["auth"]["token_url"] == "https://auth.example.test/token"
    operations = {operation["op_key"]: operation for operation in spec["operations"]}
    assert set(operations) == {"list_tickets", "create_ticket", "get_ticket"}
    listing = operations["list_tickets"]
    # The path-level $ref parameter is resolved and merged; the Authorization header is never a model parameter.
    assert {param["name"] for param in listing["parameters"]} == {"assignment_group", "limit"}
    assert listing["read_only"] is True
    assert operations["create_ticket"]["read_only"] is False
    body = operations["create_ticket"]["request_body"]["schema"]
    # The recursive schema is cut at its second visit instead of looping.
    assert body["properties"]["children"]["items"]["description"] == "Recursive reference: #/components/schemas/Node"
    path_param = operations["get_ticket"]["parameters"][0]
    assert path_param["in"] == "path" and path_param["required"] is True


def test_swagger2_basic_is_read():
    document = {
        "swagger": "2.0",
        "info": {"title": "Legacy"},
        "host": "legacy.example.test",
        "basePath": "/v1",
        "schemes": ["https"],
        "securityDefinitions": {"key": {"type": "apiKey", "in": "query", "name": "token"}},
        "definitions": {"Filter": {"type": "object", "properties": {"q": {"type": "string"}}}},
        "paths": {
            "/search": {
                "post": {
                    "operationId": "search",
                    "parameters": [{"in": "body", "name": "body", "schema": {"$ref": "#/definitions/Filter"}}],
                },
                "get": {"parameters": [{"in": "query", "name": "status", "type": "string", "enum": ["open"]}]},
            }
        },
    }

    spec = read_openapi(json.dumps(document))

    assert spec["servers"] == ["https://legacy.example.test/v1"]
    assert spec["auth"] == {"scheme": "api_key_query", "query_name": "token", "source_scheme": "key"}
    operations = {operation["op_key"]: operation for operation in spec["operations"]}
    assert operations["search"]["request_body"]["schema"]["properties"]["q"] == {"type": "string"}
    assert operations["get_search"]["parameters"][0]["schema"] == {"type": "string", "enum": ["open"]}


def test_not_an_openapi_document_is_refused():
    with pytest.raises(OpenApiError):
        read_openapi("just: yaml")


def test_a_scoped_grant_without_result_filter_warns_when_the_model_can_still_query_freely():
    from types import SimpleNamespace

    from app.services.rest_connector.definitions import scope_bypass_warnings

    operation = SimpleNamespace(
        method="GET", params_overlay={},
        parameters=[{"name": "assignment_group", "in": "query"}, {"name": "sysparm_query", "in": "query"}],
        grants=[{"role": "agent", "scope": {"assignment_group": "G1"}, "result_filter": None}])
    [warning] = scope_bypass_warnings(operation)
    assert "sysparm_query" in warning and "result filter" in warning

    operation.grants = [{"role": "agent", "scope": {"assignment_group": "G1"},
                         "result_filter": {"field": "assignment_group", "value": "G1"}}]
    assert scope_bypass_warnings(operation) == []
    operation.grants = [{"role": "agent", "scope": {"assignment_group": "G1"}, "result_filter": None}]
    operation.params_overlay = {"sysparm_query": {"hidden": True}}
    assert scope_bypass_warnings(operation) == []
