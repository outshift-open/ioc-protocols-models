"""
Basic validation tests for Python language bindings generated from JSON Schema.

These tests use the generated pydantic models directly for validation.

This approach ensures type safety and validates the generated Python bindings
work correctly with the IOC L9 protocol specification.
"""

import json
import pytest
from pydantic import ValidationError

# Import generated models using relative import
try:
    from ioc_l9.language_bindings.python import generated_models as gen
except ImportError:
    pytest.skip("Generated models not found. Run generate.sh first.", allow_module_level=True)


class TestGeneratedModelValidation:
    """Test validation features of generated models."""

    def test_actor_required_fields(self):
        """Test that Actor model validates required fields."""
        # Valid data
        valid_actor = gen.Actor(
            id="actor_001",
            type="human",
            name="John Doe",
            role="analyst"
        )
        assert valid_actor.id == "actor_001"
        
        # Missing required fields
        with pytest.raises(ValidationError):
            gen.Actor(id="test")  # Missing type, name, role

    def test_actor_type_validation(self):
        """Test that Actor model validates field types."""
        with pytest.raises(ValidationError):
            gen.Actor(
                id=123,  # Should be string
                type="human",
                name="John Doe",
                role="analyst"
            )

    def test_semantic_context_required_fields(self):
        """Test SemanticContext required field validation."""
        # Valid data
        valid_context = gen.SemanticContext(
            schema_id="ioc_l9_v1.0",
            ontology_ref="https://example.com/ontology",
            cognition_protocol="reasoning_v1"
        )
        assert valid_context.schema_id == "ioc_l9_v1.0"
        
        # Missing required fields
        with pytest.raises(ValidationError):
            gen.SemanticContext(schema_id="test")

    def test_group_validation(self):
        """Test Group model validation."""
        # Valid data
        valid_group = gen.Group(
            id="group_001",
            name="Security Team",
            type="operational"
        )
        assert valid_group.name == "Security Team"
        
        # Invalid types
        with pytest.raises(ValidationError):
            gen.Group(
                id=None,  # Should be string
                name="Security Team",
                type="operational"
            )

    def test_policy_label_validation(self):
        """Test PolicyLabel model validation."""
        # Valid data
        valid_policy = gen.PolicyLabel(
            sensitivity="confidential",
            propagation="restricted",
            retention_policy="30_days"
        )
        assert valid_policy.sensitivity == "confidential"
        
        # Missing required fields
        with pytest.raises(ValidationError):
            gen.PolicyLabel(sensitivity="confidential")

    def test_l9_header_nested_validation(self):
        """Test L9Header validates nested models correctly."""
        # Valid nested data
        valid_header = gen.L9Header(
            protocol="IOC_L9",
            version="1.0.0",
            kind="threat_intel",
            sub_kind="indicator",
            group={
                "id": "group_001",
                "name": "Security Team",
                "type": "operational"
            },
            actors=[{
                "id": "actor_001",
                "type": "human",
                "name": "John Doe",
                "role": "analyst"
            }],
            semantic={
                "schema_id": "ioc_l9_v1.0",
                "ontology_ref": "https://example.com/ontology",
                "cognition_protocol": "reasoning_v1"
            }
        )
        assert valid_header.protocol == "IOC_L9"
        
        # Invalid nested data
        with pytest.raises(ValidationError):
            gen.L9Header(
                protocol="IOC_L9",
                version="1.0.0",
                kind="threat_intel",
                sub_kind="indicator",
                group="invalid_group",  # Should be Group object/dict
                actors=[],
                semantic={}  # Should be SemanticContext object/dict
            )

    def test_l9_payload_validation(self):
        """Test L9Payload validation."""
        # Valid data
        valid_payload = gen.L9Payload(
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
            gen.L9Payload(type="indicator")  # Missing data

    def test_complete_l9_validation(self):
        """Test complete L9 message validation."""
        # Valid complete message
        valid_l9 = gen.L9(
            header={
                "protocol": "IOC_L9",
                "version": "1.0.0",
                "kind": "threat_intel",
                "sub_kind": "indicator",
                "group": {
                    "id": "group_001",
                    "name": "Security Team",
                    "type": "operational"
                },
                "actors": [{
                    "id": "actor_001",
                    "type": "human",
                    "name": "John Doe",
                    "role": "analyst"
                }],
                "semantic": {
                    "schema_id": "ioc_l9_v1.0",
                    "ontology_ref": "https://example.com/ontology",
                    "cognition_protocol": "reasoning_v1"
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
            gen.L9(header={})  # Missing payload

    def test_state_management_validation(self):
        """Test complex model validation with nested structures."""
        # Valid L9 message with header and payload
        valid_l9 = gen.L9(
            header=gen.L9Header(
                protocol="L9",
                version="1.0",
                kind="message",
                sub_kind="chat",
                group=gen.Group(id="group1", name="Test Group"),
                actors=[gen.Actor(id="user1", type="human", name="John", role="analyst")],
                semantic=gen.SemanticContext(
                    schema_id="l9_v1",
                    ontology_ref="standard",
                    cognition_protocol="chat"
                )
            ),
            payload=gen.L9Payload(
                type="text",
                data={"content": "Hello, world!"}
            )
        )
        assert valid_l9.header.protocol == "L9"
        assert valid_l9.payload.data["content"] == "Hello, world!"
        
        # Valid Group with multiple actors
        valid_group = gen.Group(
            id="group_001",
            name="Test Group"
        )
        assert valid_group.id == "group_001"

    def test_empty_required_fields(self):
        """Test validation with missing required fields."""
        with pytest.raises(ValidationError):
            gen.Actor()  # Missing all required fields
        
        with pytest.raises(ValidationError):
            gen.Group()  # Missing all required fields
            
        with pytest.raises(ValidationError):
            gen.Actor(id="test")  # Missing type, name, role

    def test_none_values_validation(self):
        """Test validation with None values for required fields."""
        with pytest.raises(ValidationError):
            gen.Actor(id=None, type="human", name="John", role="analyst")


class TestJSONSchemaValidation:
    """Test JSON serialization/deserialization validation."""

    def test_json_roundtrip_validation(self):
        """Test that models can be serialized to JSON and back with validation."""
        # Create a valid L9 message
        l9_data = {
            "header": {
                "protocol": "IOC_L9",
                "version": "1.0.0",
                "kind": "threat_intel",
                "sub_kind": "indicator",
                "group": {
                    "id": "group_001",
                    "name": "Security Team",
                    "type": "operational"
                },
                "actors": [{
                    "id": "actor_001",
                    "type": "human",
                    "name": "John Doe",
                    "role": "analyst"
                }],
                "semantic": {
                    "schema_id": "ioc_l9_v1.0",
                    "ontology_ref": "https://example.com/ontology",
                    "cognition_protocol": "reasoning_v1"
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
        l9_model = gen.L9(**l9_data)
        
        # Serialize to JSON
        json_str = l9_model.model_dump_json()
        
        # Verify it's valid JSON
        json_data = json.loads(json_str)
        
        # Deserialize from JSON and validate
        l9_model_restored = gen.L9(**json_data)
        
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
            gen.L9(**invalid_data)

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
            gen.L9(**partial_data)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
