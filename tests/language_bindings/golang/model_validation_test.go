// Copyright 2026 Cisco Systems, Inc. and its affiliates
//
// SPDX-License-Identifier: Apache-2.0

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
	l9 "github.com/outshift-open/ioc-protocols-models/SSTP/language_bindings/golang"
)

// TestActorRequiredFields tests Actor required field validation
func TestActorRequiredFields(t *testing.T) {
	// Check if generated models exist
	if !generatedModelsExist(t) {
		return
	}

	// Test valid Actor using generated struct
	validActor := l9.Actor{
		ID:   "actor-123",
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
	if unmarshaledActor.Role != validActor.Role {
		t.Errorf("Actor Role mismatch: expected %s, got %s", validActor.Role, unmarshaledActor.Role)
	}

	// Test invalid Actor JSON (missing required fields)
	invalidActorJSON := `{"id": "actor-123"}`

	var invalidActor l9.Actor
	err = json.Unmarshal([]byte(invalidActorJSON), &invalidActor)
	if err == nil {
		t.Error("Expected unmarshal error for Actor missing required 'role' field")
	}

	t.Log("✓ Actor required fields validation passed")
}

// TestActorOptionalAttestation tests Actor optional attestation field
func TestActorOptionalAttestation(t *testing.T) {
	if !generatedModelsExist(t) {
		return
	}

	actorJSON := `{"id": "actor-123", "role": "analyst", "attestation": "signed_token"}`

	var actor l9.Actor
	err := json.Unmarshal([]byte(actorJSON), &actor)
	if err != nil {
		t.Errorf("Failed to unmarshal Actor with attestation: %v", err)
		return
	}

	if actor.ID != "actor-123" {
		t.Errorf("Actor ID mismatch: expected actor-123, got %s", actor.ID)
	}

	t.Log("✓ Actor optional attestation validation passed")
}

// TestActorsRequiredFields tests Actors struct required field validation
func TestActorsRequiredFields(t *testing.T) {
	if !generatedModelsExist(t) {
		return
	}

	// Test valid ParticipantSet
	validActors := l9.ParticipantSet{
		Actors: []l9.Actor{{ID: "actor-123", Role: "analyst"}},
	}

	jsonBytes, err := json.Marshal(validActors)
	if err != nil {
		t.Errorf("Failed to marshal valid ParticipantSet: %v", err)
		return
	}

	var unmarshaledActors l9.ParticipantSet
	err = json.Unmarshal(jsonBytes, &unmarshaledActors)
	if err != nil {
		t.Errorf("Failed to unmarshal ParticipantSet JSON: %v", err)
		return
	}

	if len(unmarshaledActors.Actors) != 1 {
		t.Errorf("Expected 1 actor, got %d", len(unmarshaledActors.Actors))
	}

	t.Log("✓ ParticipantSet required fields validation passed")
}

// TestSemanticRequiredFields tests Semantic required field validation
func TestSemanticRequiredFields(t *testing.T) {
	if !generatedModelsExist(t) {
		return
	}

	// Test valid Semantic
	validSemantic := l9.Semantic{
		SchemaID:    "ioc_l9_v1.0",
		OntologyRef: "https://example.com/ontology",
	}

	jsonBytes, err := json.Marshal(validSemantic)
	if err != nil {
		t.Errorf("Failed to marshal valid Semantic: %v", err)
		return
	}

	var unmarshaledSemantic l9.Semantic
	err = json.Unmarshal(jsonBytes, &unmarshaledSemantic)
	if err != nil {
		t.Errorf("Failed to unmarshal Semantic JSON: %v", err)
		return
	}

	if unmarshaledSemantic.SchemaID != validSemantic.SchemaID {
		t.Errorf("SchemaID mismatch: expected %s, got %s", validSemantic.SchemaID, unmarshaledSemantic.SchemaID)
	}
	if unmarshaledSemantic.OntologyRef != validSemantic.OntologyRef {
		t.Errorf("OntologyRef mismatch: expected %s, got %s", validSemantic.OntologyRef, unmarshaledSemantic.OntologyRef)
	}

	// Test invalid Semantic JSON (missing required fields)
	invalidSemanticJSON := `{"schema_id": "test"}`
	var invalidSemantic l9.Semantic
	err = json.Unmarshal([]byte(invalidSemanticJSON), &invalidSemantic)
	if err == nil {
		t.Error("Expected unmarshal error for Semantic missing required 'ontology_ref' field")
	}

	t.Log("✓ Semantic required fields validation passed")
}

// TestPolicyLabelValidation tests PolicyLabel model validation
func TestPolicyLabelValidation(t *testing.T) {
	if !generatedModelsExist(t) {
		return
	}

	// Test valid PolicyLabel
	validPolicy := l9.PolicyLabel{
		Sensitivity:     "confidential",
		Propagation:     "restricted",
		RetentionPolicy: "30_days",
	}

	jsonBytes, err := json.Marshal(validPolicy)
	if err != nil {
		t.Errorf("Failed to marshal valid PolicyLabel: %v", err)
		return
	}

	var unmarshaledPolicy l9.PolicyLabel
	err = json.Unmarshal(jsonBytes, &unmarshaledPolicy)
	if err != nil {
		t.Errorf("Failed to unmarshal PolicyLabel JSON: %v", err)
		return
	}

	if unmarshaledPolicy.Sensitivity != "confidential" {
		t.Errorf("Expected sensitivity 'confidential', got %s", unmarshaledPolicy.Sensitivity)
	}

	// Test missing required fields
	invalidPolicyJSON := `{"sensitivity": "confidential"}`
	var invalidPolicy l9.PolicyLabel
	err = json.Unmarshal([]byte(invalidPolicyJSON), &invalidPolicy)
	if err == nil {
		t.Error("Expected unmarshal error for PolicyLabel missing required fields")
	}

	t.Log("✓ PolicyLabel validation passed")
}

// TestMessageValidation tests Message model validation
func TestMessageValidation(t *testing.T) {
	if !generatedModelsExist(t) {
		return
	}

	// Test valid Message (stateful design - only has ID)
	validMessage := l9.Message{
		ID: "msg-001",
	}

	jsonBytes, err := json.Marshal(validMessage)
	if err != nil {
		t.Errorf("Failed to marshal valid Message: %v", err)
		return
	}

	var unmarshaledMessage l9.Message
	err = json.Unmarshal(jsonBytes, &unmarshaledMessage)
	if err != nil {
		t.Errorf("Failed to unmarshal Message JSON: %v", err)
		return
	}

	if unmarshaledMessage.ID != "msg-001" {
		t.Errorf("Expected message ID 'msg-001', got %v", unmarshaledMessage.ID)
	}

	// Test missing required fields
	invalidMessageJSON := `{}`
	var invalidMessage l9.Message
	err = json.Unmarshal([]byte(invalidMessageJSON), &invalidMessage)
	if err == nil {
		t.Error("Expected unmarshal error for Message missing required fields")
	}

	t.Log("✓ Message validation passed")
}

// TestContextValidation tests Context model validation
func TestContextValidation(t *testing.T) {
	if !generatedModelsExist(t) {
		return
	}

	// Test valid Context with required field only
	validContextJSON := `{"topic": "threat_analysis"}`

	var context l9.Context
	err := json.Unmarshal([]byte(validContextJSON), &context)
	if err != nil {
		t.Errorf("Failed to unmarshal Context JSON: %v", err)
		return
	}

	if context.Topic != "threat_analysis" {
		t.Errorf("Expected topic 'threat_analysis', got %s", context.Topic)
	}

	// Test missing required field
	invalidContextJSON := `{}`
	var invalidContext l9.Context
	err = json.Unmarshal([]byte(invalidContextJSON), &invalidContext)
	if err == nil {
		t.Error("Expected unmarshal error for Context missing required 'topic' field")
	}

	t.Log("✓ Context validation passed")
}

// TestL9HeaderValidation tests L9Header model validation
func TestL9HeaderValidation(t *testing.T) {
	if !generatedModelsExist(t) {
		return
	}

	// Test valid L9Header JSON (stateful design with session)
	validHeaderJSON := `{
		"protocol": "L9",
		"subprotocol": "SSTP",
		"version": "1.0",
		"kind": "exchange",
		"subkind": "chat",
		"participants": {
			"actors": [{"id": "actor-123", "role": "analyst"}],
			"groups": {}
		},
		"session": {
			"id": "session-001",
			"episodes": [
				{
					"id": "ep-001",
					"messages": [{"id": "msg-001"}]
				}
			]
		}
	}`

	var header l9.L9Header
	err := json.Unmarshal([]byte(validHeaderJSON), &header)
	if err != nil {
		t.Errorf("Failed to unmarshal valid L9Header JSON: %v", err)
		return
	}

	if header.Protocol != "L9" {
		t.Errorf("Expected protocol 'L9', got %s", header.Protocol)
	}
	if header.Subprotocol != "SSTP" {
		t.Errorf("Expected subprotocol 'SSTP', got %s", header.Subprotocol)
	}
	if header.Subkind != "chat" {
		t.Errorf("Expected subkind 'chat', got %s", header.Subkind)
	}
	if len(header.Participants.Actors) != 1 {
		t.Errorf("Expected 1 actor, got %d", len(header.Participants.Actors))
	}

	// Test missing required fields
	invalidHeaderJSON := `{"protocol": "L9", "version": "1.0"}`
	var invalidHeader l9.L9Header
	err = json.Unmarshal([]byte(invalidHeaderJSON), &invalidHeader)
	if err == nil {
		t.Error("Expected unmarshal error for L9Header missing required fields")
	}

	t.Log("✓ L9Header validation passed")
}

// TestCompleteL9MessageValidation tests complete L9 message validation
func TestCompleteL9MessageValidation(t *testing.T) {
	if !generatedModelsExist(t) {
		return
	}

	// Test valid complete L9 message using generated structs (stateful design with session)
	validL9 := l9.L9{
		Header: l9.L9Header{
			Protocol:    "L9",
			Subprotocol: "SSTP",
			Version:     "1.0",
			Kind:        l9.KindExchange,
			Subkind:     "chat",
			Participants: l9.ParticipantSet{
				Actors: []l9.Actor{{ID: "actor-123", Role: "analyst"}},
			},
			Session: l9.Session{
				ID: "session-001",
				Episodes: []l9.Episode{
					{
						ID:       "ep-001",
						Messages: []l9.Message{{ID: "msg-001"}},
					},
				},
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
	var unmarshaledL9 l9.L9
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
	if unmarshaledL9.Header.Subkind != validL9.Header.Subkind {
		t.Errorf("Subkind mismatch: expected %s, got %s", validL9.Header.Subkind, unmarshaledL9.Header.Subkind)
	}
	if unmarshaledL9.Header.Subprotocol != validL9.Header.Subprotocol {
		t.Errorf("Subprotocol mismatch: expected %s, got %s", validL9.Header.Subprotocol, unmarshaledL9.Header.Subprotocol)
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
	originalActor := l9.Actor{
		ID:   "actor-123",
		Role: "analyst",
	}

	jsonBytes, err := json.Marshal(originalActor)
	if err != nil {
		t.Errorf("Failed to marshal Actor: %v", err)
		return
	}

	var roundTripActor l9.Actor
	err = json.Unmarshal(jsonBytes, &roundTripActor)
	if err != nil {
		t.Errorf("Failed to unmarshal round-trip Actor JSON: %v", err)
		return
	}

	if originalActor.ID != roundTripActor.ID {
		t.Errorf("Round-trip failed for id: expected %v, got %v", originalActor.ID, roundTripActor.ID)
	}
	if originalActor.Role != roundTripActor.Role {
		t.Errorf("Round-trip failed for role: expected %v, got %v", originalActor.Role, roundTripActor.Role)
	}

	t.Log("✓ JSON serialization round-trip passed")
}

// TestGeneratedModelsStructure tests the structure of generated Go models
func TestGeneratedModelsStructure(t *testing.T) {
	generatedModelsPath := filepath.Join("..", "..", "..", "SSTP", "language_bindings", "golang", "data_model.go")

	data, err := os.ReadFile(generatedModelsPath)
	if err != nil {
		t.Skip("Generated models file not found, skipping structure tests")
		return
	}

	content := string(data)

	// Check for expected struct definitions
	expectedStructs := []string{
		"type Actor struct",
		"type ParticipantSet struct",
		"type Semantic struct",
		"type Context struct",
		"type L9Header struct",
		"type L9Payload struct",
		"type L9 struct",
		"type PolicyLabel struct",
		"type Message struct",
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
	generatedModelsPath := filepath.Join("..", "..", "..", "SSTP", "language_bindings", "golang", "data_model.go")

	if _, err := os.Stat(generatedModelsPath); os.IsNotExist(err) {
		t.Skip("Generated models file does not exist. Run 'make generate_bindings LANGUAGE=golang' first.")
		return false
	}

	return true
}