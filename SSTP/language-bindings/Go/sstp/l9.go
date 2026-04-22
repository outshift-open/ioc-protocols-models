// Copyright 2026 Cisco Systems, Inc. and its affiliates
//
// SPDX-License-Identifier: Apache-2.0

// Package sstp provides Go types and a header builder for the
// Structured Semantic Transport Protocol (SSTP) L9 envelope.
//
// Run `./generate.sh` to regenerate l9_types.go from the canonical
// JSON schema at SSTP/JSON schema/sstp-schema.json.
package sstp

import (
	"crypto/sha256"
	"fmt"
	"time"
)

// Transport identifies the L9 wire protocol modality.
type Transport string

const (
	TransportSSTP Transport = "SSTP"
	TransportCSTP Transport = "CSTP"
	TransportLSTP Transport = "LSTP"

	Version = "0"
)

// Kind is the SSTP semantic kind vocabulary.
type Kind string

const (
	KindIntent        Kind = "intent"
	KindDelegation    Kind = "delegation"
	KindKnowledge     Kind = "knowledge"
	KindQuery         Kind = "query"
	KindCommit        Kind = "commit"
	KindMemoryDelta   Kind = "memory_delta"
	KindEvidenceBundle Kind = "evidence_bundle"
	KindNegotiate     Kind = "negotiate"
)

// Origin identifies the producing agent.
type Origin struct {
	ActorID     string `json:"actor_id"`
	TenantID    string `json:"tenant_id,omitempty"`
	Attestation string `json:"attestation,omitempty"`
}

// SemanticContext carries schema and cognition profile metadata.
type SemanticContext struct {
	SchemaID           string  `json:"schema_id"`
	SchemaVersion      string  `json:"schema_version"`
	Encoding           string  `json:"encoding"`
	SchemaTrustLevel   string  `json:"schema_trust_level"`
	OntologyRef        *string `json:"ontology_ref,omitempty"`
	CognitionProfileID *string `json:"cognition_profile_id,omitempty"`
	CognitionProtocol  *string `json:"cognition_protocol,omitempty"`
}

// PolicyLabels carries sensitivity and propagation policy.
type PolicyLabels struct {
	Sensitivity     string `json:"sensitivity"`
	Propagation     string `json:"propagation"`
	RetentionPolicy string `json:"retention_policy,omitempty"`
}

// Provenance records upstream sources and processing transforms.
type Provenance struct {
	Sources    []string `json:"sources"`
	Transforms []string `json:"transforms"`
}

// Header is the canonical SSTP L9 envelope header.
type Header struct {
	Protocol        Transport       `json:"protocol"`
	Version         string          `json:"version"`
	Kind            Kind            `json:"kind"`
	MessageID       string          `json:"message_id"`
	DtCreated       string          `json:"dt_created"`
	Origin          Origin          `json:"origin"`
	SemanticContext SemanticContext `json:"semantic_context"`
	PolicyLabels    PolicyLabels    `json:"policy_labels"`
	Provenance      Provenance      `json:"provenance"`
	StateObjectID   *string         `json:"state_object_id,omitempty"`
	ParentIDs       []string        `json:"parent_ids"`
	LogicalClock    *string         `json:"logical_clock,omitempty"`
	ConfidenceScore *float64        `json:"confidence_score,omitempty"`
	RiskScore       *float64        `json:"risk_score,omitempty"`
	TTLSeconds      int             `json:"ttl_seconds"`
	MergeStrategy   string          `json:"merge_strategy"`
}

// MessageID generates a deterministic UUIDv5-style ID from sender + timestamp.
func MessageID(sender string, timestampMs int64) string {
	h := sha256.Sum256([]byte(fmt.Sprintf("%s:%d", sender, timestampMs)))
	return fmt.Sprintf("%x-%x-%x-%x-%x", h[0:4], h[4:6], h[6:8], h[8:10], h[10:16])
}

// Now returns the current UTC time as ISO 8601.
func Now() string {
	return time.Now().UTC().Format(time.RFC3339)
}
