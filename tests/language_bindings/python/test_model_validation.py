# Copyright 2026 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

"""
Basic validation tests for Python language bindings generated from JSON Schema.

These tests use the generated pydantic models directly for validation.

This approach ensures type safety and validates the generated Python bindings
work correctly with the IOC L9 protocol specification.
"""

import json
import pytest
from pydantic import ValidationError

# Import generated models from wheel package
try:
    from ai.outshift import data_model
except ImportError:
    pytest.skip("Generated models not found. Run generate.sh first.", allow_module_level=True)


class TestGeneratedModelValidation:
    """Test validation features of generated models."""

    def test_actor_required_fields(self):
        """Test that Actor model validates required fields."""
        # Valid data
        valid_actor = data_model.Actor(
            id="actor_001",
            role="analyst"
        )
        assert valid_actor.id == "actor_001"
        assert valid_actor.role == "analyst"
        assert valid_actor.attestation is None

        # Missing required fields
        with pytest.raises(ValidationError):
            data_model.Actor(id="test")  # Missing role

    def test_actor_type_validation(self):
        """Test that Actor model validates field types."""
        with pytest.raises(ValidationError):
            data_model.Actor(
                id=123,  # Should be string
                role="analyst"
            )

    def test_actor_optional_attestation(self):
        """Test Actor with optional attestation field."""
        actor_with_attestation = data_model.Actor(
            id="actor_001",
            role="analyst",
            attestation="signed_token_xyz"
        )
        assert actor_with_attestation.attestation == "signed_token_xyz"

    def test_actors_required_fields(self):
        """Test Actors model required field validation."""
        # Valid data
        valid_actors = data_model.Actors(
            actors=[data_model.Actor(id="actor_001", role="analyst")],
            groups=["security_team"]
        )
        assert len(valid_actors.actors) == 1
        assert valid_actors.groups == ["security_team"]

        # Missing required fields
        with pytest.raises(ValidationError):
            data_model.Actors(actors=[])  # Missing groups

    def test_semantic_required_fields(self):
        """Test Semantic required field validation."""
        # Valid data
        valid_semantic = data_model.Semantic(
            schema_id="ioc_l9_v1.0",
            ontology_ref="https://example.com/ontology"
        )
        assert valid_semantic.schema_id == "ioc_l9_v1.0"
        assert valid_semantic.provenance is None

        # Missing required fields
        with pytest.raises(ValidationError):
            data_model.Semantic(schema_id="test")  # Missing ontology_ref

    def test_policy_label_validation(self):
        """Test PolicyLabel model validation."""
        # Valid data
        valid_policy = data_model.PolicyLabel(
            sensitivity="confidential",
            propagation="restricted",
            retention_policy="30_days"
        )
        assert valid_policy.sensitivity == "confidential"

        # Missing required fields
        with pytest.raises(ValidationError):
            data_model.PolicyLabel(sensitivity="confidential")  # Missing propagation, retention_policy

    def test_message_validation(self):
        """Test Message model validation."""
        # Valid data
        valid_message = data_model.Message(
            id="msg_001",
            parents="msg_000",
            episode="ep_001"
        )
        assert valid_message.id == "msg_001"

        # Missing required fields
        with pytest.raises(ValidationError):
            data_model.Message(id="msg_001")  # Missing parents, episode

    def test_context_validation(self):
        """Test Context model validation."""
        # Valid data with only required field
        valid_context = data_model.Context(
            topic="threat_analysis"
        )
        assert valid_context.topic == "threat_analysis"
        assert valid_context.epistemic is None
        assert valid_context.semantic is None

        # Valid data with optional semantic
        context_with_semantic = data_model.Context(
            topic="threat_analysis",
            semantic=data_model.Semantic(
                schema_id="ioc_l9_v1.0",
                ontology_ref="https://example.com/ontology"
            )
        )
        assert context_with_semantic.semantic.schema_id == "ioc_l9_v1.0"

        # Missing required fields
        with pytest.raises(ValidationError):
            data_model.Context()  # Missing topic

    def test_l9_header_validation(self):
        """Test L9Header validates fields correctly."""
        # Valid header
        valid_header = data_model.L9Header(
            protocol="IOC_L9",
            subprotocol="SSTP",
            version="1.0.0",
            kind="threat_intel",
            subkind="indicator",
            actors={
                "actors": [{"id": "actor_001", "role": "analyst"}],
                "groups": ["security_team"]
            }
        )
        assert valid_header.protocol == "IOC_L9"
        assert valid_header.subprotocol == "SSTP"
        assert valid_header.subkind == "indicator"

        # Missing required fields
        with pytest.raises(ValidationError):
            data_model.L9Header(
                protocol="IOC_L9",
                version="1.0.0",
                kind="threat_intel"
                # Missing subprotocol, subkind, actors
            )

    def test_l9_header_with_optional_fields(self):
        """Test L9Header with optional context, message, policy."""
        valid_header = data_model.L9Header(
            protocol="IOC_L9",
            subprotocol="SSTP",
            version="1.0.0",
            kind="threat_intel",
            subkind="indicator",
            actors=data_model.Actors(
                actors=[data_model.Actor(id="actor_001", role="analyst")],
                groups=["security_team"]
            ),
            context=data_model.Context(
                topic="threat_analysis",
                semantic=data_model.Semantic(
                    schema_id="ioc_l9_v1.0",
                    ontology_ref="https://example.com/ontology"
                )
            ),
            message=data_model.Message(
                id="msg_001",
                parents="msg_000",
                episode="ep_001"
            ),
            policy=data_model.PolicyLabel(
                sensitivity="confidential",
                propagation="restricted",
                retention_policy="30_days"
            )
        )
        assert valid_header.context.topic == "threat_analysis"
        assert valid_header.message.id == "msg_001"
        assert valid_header.policy.sensitivity == "confidential"

    def test_l9_payload_validation(self):
        """Test L9Payload validation."""
        # Valid data
        valid_payload = data_model.L9Payload(
            type="indicator",
            data={
                "indicator_type": "ip",
                "value": "192.168.1.100",
                "confidence": 0.85
            }
        )
        assert valid_payload.type == "indicator"

        # Missing required fields
        with pytest.raises(ValidationError):
            data_model.L9Payload(type="indicator")  # Missing data

    def test_complete_l9_validation(self):
        """Test complete L9 message validation."""
        # Valid complete message
        valid_l9 = data_model.L9(
            header={
                "protocol": "IOC_L9",
                "subprotocol": "SSTP",
                "version": "1.0.0",
                "kind": "threat_intel",
                "subkind": "indicator",
                "actors": {
                    "actors": [{"id": "actor_001", "role": "analyst"}],
                    "groups": ["security_team"]
                }
            },
            payload={
                "type": "indicator",
                "data": {
                    "indicator_type": "ip",
                    "value": "192.168.1.100"
                }
            }
        )
        assert valid_l9.header.protocol == "IOC_L9"

        # Missing required components
        with pytest.raises(ValidationError):
            data_model.L9(header={})  # Missing payload and invalid header

    def test_state_management_validation(self):
        """Test complex model validation with nested structures."""
        # Valid L9 message with header and payload
        valid_l9 = data_model.L9(
            header=data_model.L9Header(
                protocol="L9",
                subprotocol="SSTP",
                version="1.0",
                kind="message",
                subkind="chat",
                actors=data_model.Actors(
                    actors=[data_model.Actor(id="user1", role="analyst")],
                    groups=["team_alpha"]
                ),
                context=data_model.Context(
                    topic="security_analysis",
                    semantic=data_model.Semantic(
                        schema_id="l9_v1",
                        ontology_ref="standard"
                    )
                )
            ),
            payload=data_model.L9Payload(
                type="text",
                data={"content": "Hello, world!"}
            )
        )
        assert valid_l9.header.protocol == "L9"
        assert valid_l9.payload.data["content"] == "Hello, world!"

    def test_empty_required_fields(self):
        """Test validation with missing required fields."""
        with pytest.raises(ValidationError):
            data_model.Actor()  # Missing all required fields

        with pytest.raises(ValidationError):
            data_model.Actors()  # Missing all required fields

        with pytest.raises(ValidationError):
            data_model.Actor(id="test")  # Missing role

    def test_none_values_validation(self):
        """Test validation with None values for required fields."""
        with pytest.raises(ValidationError):
            data_model.Actor(id=None, role="analyst")


class TestJSONSchemaValidation:
    """Test JSON serialization/deserialization validation."""

    def test_json_roundtrip_validation(self):
        """Test that models can be serialized to JSON and back with validation."""
        # Create a valid L9 message
        l9_data = {
            "header": {
                "protocol": "IOC_L9",
                "subprotocol": "SSTP",
                "version": "1.0.0",
                "kind": "threat_intel",
                "subkind": "indicator",
                "actors": {
                    "actors": [{"id": "actor_001", "role": "analyst"}],
                    "groups": ["security_team"]
                },
                "context": {
                    "topic": "threat_analysis",
                    "semantic": {
                        "schema_id": "ioc_l9_v1.0",
                        "ontology_ref": "https://example.com/ontology"
                    }
                }
            },
            "payload": {
                "type": "indicator",
                "data": {
                    "indicator_type": "ip",
                    "value": "192.168.1.100",
                    "confidence": 0.85
                }
            }
        }

        # Create model from data
        l9_model = data_model.L9(**l9_data)

        # Serialize to JSON
        json_str = l9_model.model_dump_json()

        # Verify it's valid JSON
        json_data = json.loads(json_str)

        # Deserialize from JSON and validate
        l9_model_restored = data_model.L9(**json_data)

        # Verify they're identical
        assert l9_model.model_dump() == l9_model_restored.model_dump()

    def test_invalid_json_data(self):
        """Test validation with invalid JSON data."""
        invalid_data = {
            "header": "not_an_object",  # Should be object
            "payload": {
                "type": "indicator",
                "data": {}
            }
        }

        with pytest.raises(ValidationError):
            data_model.L9(**invalid_data)

    def test_partial_json_data(self):
        """Test validation with partial/incomplete JSON data."""
        partial_data = {
            "header": {
                "protocol": "IOC_L9",
                "version": "1.0.0"
                # Missing required fields
            }
        }

        with pytest.raises(ValidationError):
            data_model.L9(**partial_data)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])