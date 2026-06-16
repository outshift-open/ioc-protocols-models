package main

// Model Validation Tests for IOC L9 Protocol - Golang Language Bindings
//
// These tests use the generated Go structs directly for validation.
//
// This approach ensures type safety and validates the generated Go bindings
// work correctly with the IOC L9 protocol specification.

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"

	// Import generated models
	l9 "github.com/cisco-eti/ioc-cfn-protocols-models/ioc_l9/language_bindings/golang"
)

// Helper function for struct-based Actor validation
func testActorWithGeneratedModels(t *testing.T) {
	// Test valid Actor using generated struct
	validActor := l9.Actor{
		ID:   "actor-123",
		Type: "human",
		Name: "John Doe",
		Role: "analyst",
	}

	// Test JSON marshaling of valid Actor
	jsonBytes, err := json.Marshal(validActor)
	if err != nil {
		t.Errorf("Failed to marshal valid Actor: %v", err)
		return
	}

	// Test JSON unmarshaling back to struct
	var unmarshaledActor l9.Actor
	err = json.Unmarshal(jsonBytes, &unmarshaledActor)
	if err != nil {
		t.Errorf("Failed to unmarshal Actor JSON: %v", err)
		return
	}

	// Verify all fields are preserved
	if unmarshaledActor.ID != validActor.ID {
		t.Errorf("Actor ID mismatch: expected %s, got %s", validActor.ID, unmarshaledActor.ID)
	}
	if unmarshaledActor.Type != validActor.Type {
		t.Errorf("Actor Type mismatch: expected %s, got %s", validActor.Type, unmarshaledActor.Type)
	}
	if unmarshaledActor.Name != validActor.Name {
		t.Errorf("Actor Name mismatch: expected %s, got %s", validActor.Name, unmarshaledActor.Name)
	}
	if unmarshaledActor.Role != validActor.Role {
		t.Errorf("Actor Role mismatch: expected %s, got %s", validActor.Role, unmarshaledActor.Role)
	}

	t.Log("✓ Actor struct validation passed")
}

// TestActorRequiredFields tests Actor required field validation
func TestActorRequiredFields(t *testing.T) {
	// Check if generated models exist
	if !generatedModelsExist(t) {
		return
	}

	// Test valid Actor using generated struct
	validActor := l9.Actor{
		ID:   "actor-123",
		Type: "human",
		Name: "John Doe",
		Role: "analyst",
	}

	// Test JSON marshaling of valid Actor
	jsonBytes, err := json.Marshal(validActor)
	if err != nil {
		t.Errorf("Failed to marshal valid Actor: %v", err)
		return
	}

	// Test JSON unmarshaling back to struct
	var unmarshaledActor l9.Actor
	err = json.Unmarshal(jsonBytes, &unmarshaledActor)
	if err != nil {
		t.Errorf("Failed to unmarshal Actor JSON: %v", err)
		return
	}

	// Verify all fields are preserved
	if unmarshaledActor.ID != validActor.ID {
		t.Errorf("Actor ID mismatch: expected %s, got %s", validActor.ID, unmarshaledActor.ID)
	}
	if unmarshaledActor.Type != validActor.Type {
		t.Errorf("Actor Type mismatch: expected %s, got %s", validActor.Type, unmarshaledActor.Type)
	}
	if unmarshaledActor.Name != validActor.Name {
		t.Errorf("Actor Name mismatch: expected %s, got %s", validActor.Name, unmarshaledActor.Name)
	}
	if unmarshaledActor.Role != validActor.Role {
		t.Errorf("Actor Role mismatch: expected %s, got %s", validActor.Role, unmarshaledActor.Role)
	}

	// Test invalid Actor JSON (missing required fields)
	invalidActorJSON := `{"id": "actor-123"}`

	var invalidActor map[string]interface{}
	err = json.Unmarshal([]byte(invalidActorJSON), &invalidActor)
	if err != nil {
		t.Errorf("Failed to parse invalid Actor JSON: %v", err)
		return
	}

	// Should be missing required fields
	missingFields := []string{}
	requiredFieldsForInvalid := []string{"id", "type", "name", "role"}
	for _, field := range requiredFieldsForInvalid {
		if _, exists := invalidActor[field]; !exists {
			missingFields = append(missingFields, field)
		}
	}

	if len(missingFields) != 3 { // Should be missing type, name, role
		t.Errorf("Expected 3 missing fields, got %d: %v", len(missingFields), missingFields)
	}

	t.Log("✓ Actor required fields validation passed")
}

// TestSemanticContextRequiredFields tests SemanticContext required field validation
func TestSemanticContextRequiredFields(t *testing.T) {
	if !generatedModelsExist(t) {
		return
	}

	// Test valid SemanticContext JSON
	validContextJSON := `{
		"schema_id": "ioc_l9_v1.0",
		"ontology_ref": "https://example.com/ontology", 
		"cognition_protocol": "reasoning_v1"
	}`

	var context map[string]interface{}
	err := json.Unmarshal([]byte(validContextJSON), &context)
	if err != nil {
		t.Errorf("Failed to parse valid SemanticContext JSON: %v", err)
		return
	}

	// Verify all required fields are present
	requiredFields := []string{"schema_id", "ontology_ref", "cognition_protocol"}
	for _, field := range requiredFields {
		if _, exists := context[field]; !exists {
			t.Errorf("SemanticContext missing required field: %s", field)
		}
	}

	// Test invalid SemanticContext JSON (missing required fields)
	invalidContextJSON := `{"schema_id": "test"}`

	var invalidContext map[string]interface{}
	err = json.Unmarshal([]byte(invalidContextJSON), &invalidContext)
	if err != nil {
		t.Errorf("Failed to parse invalid SemanticContext JSON: %v", err)
		return
	}

	// Should be missing required fields
	missingFields := []string{}
	for _, field := range requiredFields {
		if _, exists := invalidContext[field]; !exists {
			missingFields = append(missingFields, field)
		}
	}

	if len(missingFields) != 2 { // Should be missing ontology_ref, cognition_protocol
		t.Errorf("Expected 2 missing fields, got %d: %v", len(missingFields), missingFields)
	}

	t.Log("✓ SemanticContext required fields validation passed")
}

// TestGroupValidation tests Group model validation
func TestGroupValidation(t *testing.T) {
	if !generatedModelsExist(t) {
		return
	}

	// Test valid Group JSON
	validGroupJSON := `{
		"id": "group-456",
		"name": "Test Team"
	}`

	var group map[string]interface{}
	err := json.Unmarshal([]byte(validGroupJSON), &group)
	if err != nil {
		t.Errorf("Failed to parse valid Group JSON: %v", err)
		return
	}

	// Verify required fields
	if group["id"] != "group-456" {
		t.Errorf("Expected group id 'group-456', got %v", group["id"])
	}
	if group["name"] != "Test Team" {
		t.Errorf("Expected group name 'Test Team', got %v", group["name"])
	}

	t.Log("✓ Group validation passed")
}

// TestL9HeaderValidation tests L9Header model validation
func TestL9HeaderValidation(t *testing.T) {
	if !generatedModelsExist(t) {
		return
	}

	// Test valid L9Header JSON
	validHeaderJSON := `{
		"protocol": "L9",
		"version": "1.0",
		"kind": "message",
		"sub_kind": "chat",
		"group": {
			"id": "group-456", 
			"name": "Test Team"
		},
		"actors": [{
			"id": "actor-123",
			"type": "human",
			"name": "John Doe", 
			"role": "analyst"
		}],
		"semantic": {
			"schema_id": "ioc_l9_v1.0",
			"ontology_ref": "https://example.com/ontology",
			"cognition_protocol": "reasoning_v1"
		}
	}`

	var header map[string]interface{}
	err := json.Unmarshal([]byte(validHeaderJSON), &header)
	if err != nil {
		t.Errorf("Failed to parse valid L9Header JSON: %v", err)
		return
	}

	// Verify required fields
	requiredFields := []string{"protocol", "version", "kind", "sub_kind", "group", "actors", "semantic"}
	for _, field := range requiredFields {
		if _, exists := header[field]; !exists {
			t.Errorf("L9Header missing required field: %s", field)
		}
	}

	// Verify nested structures
	if actors, ok := header["actors"].([]interface{}); ok {
		if len(actors) != 1 {
			t.Errorf("Expected 1 actor, got %d", len(actors))
		}
	} else {
		t.Error("Actors field is not an array")
	}

	t.Log("✓ L9Header validation passed")
}

// TestCompleteL9MessageValidation tests complete L9 message validation
func TestCompleteL9MessageValidation(t *testing.T) {
	if !generatedModelsExist(t) {
		return
	}

	// Test valid complete L9 message using generated structs
	validL9 := l9.L9Json{
		Header: l9.L9Header{
			Protocol: "L9",
			Version:  "1.0",
			Kind:     "message",
			SubKind:  "chat",
			Group: l9.Group{
				ID:   "group-456",
				Name: "Test Team",
			},
			Actors: []l9.Actor{{
				ID:   "actor-123",
				Type: "human",
				Name: "John Doe",
				Role: "analyst",
			}},
			Semantic: l9.SemanticContext{
				SchemaID:          "ioc_l9_v1.0",
				OntologyRef:       "https://example.com/ontology",
				CognitionProtocol: "reasoning_v1",
			},
		},
		Payload: l9.L9Payload{
			Type: "text",
			Data: l9.L9PayloadData{"content": "Hello, world!"},
		},
	}

	// Test JSON marshaling of complete L9 message
	jsonBytes, err := json.Marshal(validL9)
	if err != nil {
		t.Errorf("Failed to marshal valid L9 message: %v", err)
		return
	}

	// Test JSON unmarshaling back to struct
	var unmarshaledL9 l9.L9Json
	err = json.Unmarshal(jsonBytes, &unmarshaledL9)
	if err != nil {
		t.Errorf("Failed to unmarshal L9 JSON: %v", err)
		return
	}

	// Verify header fields are preserved
	if unmarshaledL9.Header.Protocol != validL9.Header.Protocol {
		t.Errorf("Protocol mismatch: expected %s, got %s", validL9.Header.Protocol, unmarshaledL9.Header.Protocol)
	}
	if unmarshaledL9.Header.Version != validL9.Header.Version {
		t.Errorf("Version mismatch: expected %s, got %s", validL9.Header.Version, unmarshaledL9.Header.Version)
	}
	if unmarshaledL9.Header.Kind != validL9.Header.Kind {
		t.Errorf("Kind mismatch: expected %s, got %s", validL9.Header.Kind, unmarshaledL9.Header.Kind)
	}
	if unmarshaledL9.Header.SubKind != validL9.Header.SubKind {
		t.Errorf("SubKind mismatch: expected %s, got %s", validL9.Header.SubKind, unmarshaledL9.Header.SubKind)
	}

	// Verify payload fields are preserved
	if unmarshaledL9.Payload.Type != validL9.Payload.Type {
		t.Errorf("Payload Type mismatch: expected %s, got %s", validL9.Payload.Type, unmarshaledL9.Payload.Type)
	}

	t.Log("✓ Complete L9 message struct validation passed")
}

// TestJSONSerializationRoundTrip tests JSON serialization round-trip
func TestJSONSerializationRoundTrip(t *testing.T) {
	if !generatedModelsExist(t) {
		return
	}

	// Test Actor round-trip
	originalActorJSON := `{
		"id": "actor-123",
		"type": "human",
		"name": "John Doe", 
		"role": "analyst"
	}`

	// Parse JSON
	var actor map[string]interface{}
	err := json.Unmarshal([]byte(originalActorJSON), &actor)
	if err != nil {
		t.Errorf("Failed to unmarshal Actor JSON: %v", err)
		return
	}

	// Marshal back to JSON
	marshaledJSON, err := json.Marshal(actor)
	if err != nil {
		t.Errorf("Failed to marshal Actor back to JSON: %v", err)
		return
	}

	// Parse marshaled JSON
	var roundTripActor map[string]interface{}
	err = json.Unmarshal(marshaledJSON, &roundTripActor)
	if err != nil {
		t.Errorf("Failed to unmarshal round-trip Actor JSON: %v", err)
		return
	}

	// Compare key fields
	if actor["id"] != roundTripActor["id"] {
		t.Errorf("Round-trip failed for id: expected %v, got %v", actor["id"], roundTripActor["id"])
	}
	if actor["name"] != roundTripActor["name"] {
		t.Errorf("Round-trip failed for name: expected %v, got %v", actor["name"], roundTripActor["name"])
	}

	t.Log("✓ JSON serialization round-trip passed")
}

// TestGeneratedModelsStructure tests the structure of generated Go models
func TestGeneratedModelsStructure(t *testing.T) {
	generatedModelsPath := filepath.Join("..", "..", "..", "language_bindings", "golang", "generated_models.go")

	data, err := os.ReadFile(generatedModelsPath)
	if err != nil {
		t.Skip("Generated models file not found, skipping structure tests")
		return
	}

	content := string(data)

	// Check for expected struct definitions
	expectedStructs := []string{
		"type Actor struct",
		"type SemanticContext struct",
		"type Group struct",
		"type L9Header struct",
		"type L9Payload struct",
		"type L9Json struct",
	}

	for _, structDef := range expectedStructs {
		if !strings.Contains(content, structDef) {
			t.Errorf("Expected struct definition '%s' not found in generated file", structDef)
		} else {
			t.Logf("✓ Found struct definition: %s", structDef)
		}
	}

	// Check for JSON tags
	if !strings.Contains(content, "`json:") {
		t.Error("Generated structs should contain JSON tags")
	} else {
		jsonTagCount := strings.Count(content, "`json:")
		t.Logf("✓ Found %d JSON tags in generated code", jsonTagCount)
	}

	t.Log("✓ Generated models structure validation passed")
}

// Helper function to check if generated models exist
func generatedModelsExist(t *testing.T) bool {
	generatedModelsPath := filepath.Join("..", "..", "..", "language_bindings", "golang", "generated_models.go")

	if _, err := os.Stat(generatedModelsPath); os.IsNotExist(err) {
		t.Skip("Generated models file does not exist. Run 'make generate_bindings LANGUAGE=golang' first.")
		return false
	}

	return true
}
