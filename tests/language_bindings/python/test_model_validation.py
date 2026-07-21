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

    def test_participant_set_required_fields(self):
        """Test ParticipantSet model required field validation."""
        # Valid data
        valid_participants = data_model.ParticipantSet(
            actors=[data_model.Actor(id="actor_001", role="analyst")],
            groups={"security_team": ["actor_001"]}
        )
        assert len(valid_participants.actors) == 1
        assert valid_participants.groups == {"security_team": ["actor_001"]}

        # Valid with null groups
        valid_participants_no_groups = data_model.ParticipantSet(
            actors=[data_model.Actor(id="actor_001", role="analyst")],
            groups=None
        )
        assert valid_participants_no_groups.groups is None

        # Missing required fields
        with pytest.raises(ValidationError):
            data_model.ParticipantSet(actors=[])  # Missing groups

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
        """Test Message model validation (stateful design - only has id)."""
        # Valid data
        valid_message = data_model.Message(id="msg-001")
        assert valid_message.id == "msg-001"

        # Missing required fields
        with pytest.raises(ValidationError):
            data_model.Message()  # Missing id

    def test_kind_enum(self):
        """Test Kind enum values."""
        assert data_model.Kind.intent.value == "intent"
        assert data_model.Kind.contingency.value == "contingency"
        assert data_model.Kind.exchange.value == "exchange"
        assert data_model.Kind.commit.value == "commit"
        assert data_model.Kind.knowledge.value == "knowledge"

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
        """Test L9Header validates fields correctly (stateful design with session)."""
        # Valid header
        valid_header = data_model.L9Header(
            protocol="IOC_L9",
            subprotocol="SSTP",
            version="1.0.0",
            kind=data_model.Kind.intent,
            participants=data_model.ParticipantSet(
                actors=[data_model.Actor(id="actor_001", role="analyst")],
                groups={"security_team": ["actor_001"]}
            ),
            session=data_model.Session(
                id="session-001",
                episodes=[
                    data_model.Episode(
                        id="ep-001",
                        messages=[data_model.Message(id="msg-001")]
                    )
                ]
            )
        )
        assert valid_header.protocol == "IOC_L9"
        assert valid_header.subprotocol == "SSTP"
        assert valid_header.kind == data_model.Kind.intent
        assert valid_header.subkind is None

        # Missing required fields
        with pytest.raises(ValidationError):
            data_model.L9Header(
                protocol="IOC_L9",
                version="1.0.0",
                kind=data_model.Kind.intent
                # Missing subprotocol, participants, session
            )

    def test_l9_header_with_optional_fields(self):
        """Test L9Header with optional context and policy (stateful design)."""
        valid_header = data_model.L9Header(
            protocol="IOC_L9",
            subprotocol="SSTP",
            version="1.0.0",
            kind=data_model.Kind.exchange,
            subkind="indicator",
            participants=data_model.ParticipantSet(
                actors=[data_model.Actor(id="actor_001", role="analyst")],
                groups={"security_team": ["actor_001"]}
            ),
            session=data_model.Session(
                id="session-001",
                episodes=[
                    data_model.Episode(
                        id="ep-001",
                        messages=[data_model.Message(id="msg-001"), data_model.Message(id="msg-002")]
                    )
                ]
            ),
            context=data_model.Context(
                topic="threat_analysis",
                semantic=data_model.Semantic(
                    schema_id="ioc_l9_v1.0",
                    ontology_ref="https://example.com/ontology"
                )
            ),
            policy=data_model.PolicyLabel(
                sensitivity="confidential",
                propagation="restricted",
                retention_policy="30_days"
            )
        )
        assert valid_header.context.topic == "threat_analysis"
        assert valid_header.session.id == "session-001"
        assert len(valid_header.session.episodes[0].messages) == 2
        assert valid_header.policy.sensitivity == "confidential"
        assert valid_header.subkind == "indicator"

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

    def test_complete_l91_validation(self):
        """Test complete L91 message validation (stateful design)."""
        # Valid complete message
        valid_l91 = data_model.L9(
            header=data_model.L9Header(
                protocol="IOC_L9",
                subprotocol="SSTP",
                version="1.0.0",
                kind=data_model.Kind.knowledge,
                participants=data_model.ParticipantSet(
                    actors=[data_model.Actor(id="actor_001", role="analyst")],
                    groups={"security_team": ["actor_001"]}
                ),
                session=data_model.Session(
                    id="session-001",
                    episodes=[
                        data_model.Episode(
                            id="ep-001",
                            messages=[data_model.Message(id="msg-001")]
                        )
                    ]
                )
            ),
            payload=data_model.L9Payload(
                type="indicator",
                data={
                    "indicator_type": "ip",
                    "value": "192.168.1.100"
                }
            )
        )
        assert valid_l91.header.protocol == "IOC_L9"
        assert valid_l91.payload.type == "indicator"

        # Missing required components
        with pytest.raises(ValidationError):
            data_model.L9(header={})  # Missing payload and invalid header

    def test_l9_root_model(self):
        """Test L9Schema RootModel accepts any data."""
        l9_schema = data_model.L9Schema(root={"any": "data"})
        assert l9_schema.root == {"any": "data"}

    def test_state_management_validation(self):
        """Test complex model validation with nested structures (stateful design)."""
        # Valid L91 message with header and payload
        valid_l91 = data_model.L9(
            header=data_model.L9Header(
                protocol="L9",
                subprotocol="SSTP",
                version="1.0",
                kind=data_model.Kind.commit,
                participants=data_model.ParticipantSet(
                    actors=[data_model.Actor(id="user1", role="analyst")],
                    groups={"team_alpha": ["user1"]}
                ),
                session=data_model.Session(
                    id="session-001",
                    episodes=[
                        data_model.Episode(
                            id="ep-001",
                            messages=[data_model.Message(id="msg-001")]
                        )
                    ]
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
        assert valid_l91.header.protocol == "L9"
        assert valid_l91.payload.data["content"] == "Hello, world!"

    def test_empty_required_fields(self):
        """Test validation with missing required fields."""
        with pytest.raises(ValidationError):
            data_model.Actor()  # Missing all required fields

        with pytest.raises(ValidationError):
            data_model.ParticipantSet()  # Missing all required fields

        with pytest.raises(ValidationError):
            data_model.Actor(id="test")  # Missing role

    def test_none_values_validation(self):
        """Test validation with None values for required fields."""
        with pytest.raises(ValidationError):
            data_model.Actor(id=None, role="analyst")

    def test_episode_validation(self):
        """Test Episode model validation (stateful design)."""
        valid_episode = data_model.Episode(
            id="ep_001",
            messages=[data_model.Message(id="msg-001")]
        )
        assert valid_episode.id == "ep_001"
        assert len(valid_episode.messages) == 1

        with pytest.raises(ValidationError):
            data_model.Episode(id="ep_001")  # Missing messages

    def test_session_validation(self):
        """Test Session model validation (stateful design)."""
        valid_session = data_model.Session(
            id="session-001",
            episodes=[
                data_model.Episode(
                    id="ep-001",
                    messages=[data_model.Message(id="msg-001")]
                )
            ]
        )
        assert valid_session.id == "session-001"
        assert len(valid_session.episodes) == 1
        assert len(valid_session.episodes[0].messages) == 1

        with pytest.raises(ValidationError):
            data_model.Session(id="session-001")  # Missing episodes


class TestJSONSchemaValidation:
    """Test JSON serialization/deserialization validation."""

    def test_json_roundtrip_validation(self):
        """Test that models can be serialized to JSON and back with validation (stateful design)."""
        # Create a valid L91 message
        l91_model = data_model.L9(
            header=data_model.L9Header(
                protocol="IOC_L9",
                subprotocol="SSTP",
                version="1.0.0",
                kind=data_model.Kind.knowledge,
                participants=data_model.ParticipantSet(
                    actors=[data_model.Actor(id="actor_001", role="analyst")],
                    groups={"security_team": ["actor_001"]}
                ),
                session=data_model.Session(
                    id="session-001",
                    episodes=[
                        data_model.Episode(
                            id="ep-001",
                            messages=[data_model.Message(id="msg-001")]
                        )
                    ]
                ),
                context=data_model.Context(
                    topic="threat_analysis",
                    semantic=data_model.Semantic(
                        schema_id="ioc_l9_v1.0",
                        ontology_ref="https://example.com/ontology"
                    )
                )
            ),
            payload=data_model.L9Payload(
                type="indicator",
                data={
                    "indicator_type": "ip",
                    "value": "192.168.1.100",
                    "confidence": 0.85
                }
            )
        )

        # Serialize to JSON
        json_str = l91_model.model_dump_json()

        # Verify it's valid JSON
        json_data = json.loads(json_str)

        # Deserialize from JSON and validate
        l91_restored = data_model.L9(**json_data)

        # Verify they're identical
        assert l91_model.model_dump() == l91_restored.model_dump()

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