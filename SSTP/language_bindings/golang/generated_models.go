// Copyright 2026 Cisco Systems, Inc. and its affiliates
//
// SPDX-License-Identifier: Apache-2.0

package l9

import "encoding/json"
import "errors"
import "fmt"

type L9HeaderContextEpistemic_0 = Epistemic

// Describes the semantic/ontological framework needed to correctly interpret the
// payload.
// The CFN routing layer uses this to select appropriate cognitive engines (CEs).
type Semantic struct {
	// OntologyRef corresponds to the JSON schema field "ontology_ref".
	OntologyRef string `json:"ontology_ref" yaml:"ontology_ref" mapstructure:"ontology_ref"`

	// Provenance corresponds to the JSON schema field "provenance".
	Provenance *SemanticProvenance `json:"provenance,omitempty,omitzero" yaml:"provenance,omitempty" mapstructure:"provenance,omitempty"`

	// SchemaID corresponds to the JSON schema field "schema_id".
	SchemaID string `json:"schema_id" yaml:"schema_id" mapstructure:"schema_id"`
}

// UnmarshalJSON implements json.Unmarshaler.
func (j *Actor) UnmarshalJSON(value []byte) error {
	var raw map[string]interface{}
	if err := json.Unmarshal(value, &raw); err != nil {
		return err
	}
	if _, ok := raw["id"]; raw != nil && !ok {
		return fmt.Errorf("field id in Actor: required")
	}
	if _, ok := raw["role"]; raw != nil && !ok {
		return fmt.Errorf("field role in Actor: required")
	}
	type Plain Actor
	var plain Plain
	if err := json.Unmarshal(value, &plain); err != nil {
		return err
	}
	*j = Actor(plain)
	return nil
}

type Actors struct {
	// Actors corresponds to the JSON schema field "actors".
	Actors []Actor `json:"actors" yaml:"actors" mapstructure:"actors"`

	// Groups corresponds to the JSON schema field "groups".
	Groups []string `json:"groups" yaml:"groups" mapstructure:"groups"`
}

// UnmarshalJSON implements json.Unmarshaler.
func (j *Actors) UnmarshalJSON(value []byte) error {
	var raw map[string]interface{}
	if err := json.Unmarshal(value, &raw); err != nil {
		return err
	}
	if _, ok := raw["actors"]; raw != nil && !ok {
		return fmt.Errorf("field actors in Actors: required")
	}
	if _, ok := raw["groups"]; raw != nil && !ok {
		return fmt.Errorf("field groups in Actors: required")
	}
	type Plain Actors
	var plain Plain
	if err := json.Unmarshal(value, &plain); err != nil {
		return err
	}
	*j = Actors(plain)
	return nil
}

// Agent epistemic (belief/knowledge) state at the time the message was sent.
// Currently a placeholder — fields will be added as the model is defined.
type Epistemic map[string]interface{}

// UnmarshalJSON implements json.Unmarshaler.
func (j *Epistemic) UnmarshalJSON(value []byte) error {
	type Plain Epistemic
	var plain Plain
	if err := json.Unmarshal(value, &plain); err != nil {
		return err
	}
	*j = Epistemic(plain)
	return nil
}

type ContextEpistemic_0 = Epistemic

// Agent epistemic (belief/knowledge) state at the time the message was sent.
// Currently a placeholder — fields will be added as the model is defined.
type ContextEpistemic map[string]interface{}

// Tracks the origin and lineage of a message — who created it, from what source,
// and through which transformations. Fields TBD.
type Provenance map[string]interface{}

// UnmarshalJSON implements json.Unmarshaler.
func (j *Provenance) UnmarshalJSON(value []byte) error {
	type Plain Provenance
	var plain Plain
	if err := json.Unmarshal(value, &plain); err != nil {
		return err
	}
	*j = Provenance(plain)
	return nil
}

type SemanticProvenance_0 = Provenance

type ActorAttestation_0 *string

type L9HeaderAttributes map[string]interface{}

// UnmarshalJSON implements json.Unmarshaler.
func (j *L9SchemaJson) UnmarshalJSON(value []byte) error {
	var raw map[string]interface{}
	if err := json.Unmarshal(value, &raw); err != nil {
		return err
	}
	if _, ok := raw["header"]; raw != nil && !ok {
		return fmt.Errorf("field header in L9SchemaJson: required")
	}
	if _, ok := raw["payload"]; raw != nil && !ok {
		return fmt.Errorf("field payload in L9SchemaJson: required")
	}
	type Plain L9SchemaJson
	var plain Plain
	if err := json.Unmarshal(value, &plain); err != nil {
		return err
	}
	*j = L9SchemaJson(plain)
	return nil
}

type ContextSemantic_0 = Semantic

type ContextSemanticProvenance_0 = Provenance

// Tracks the origin and lineage of a message — who created it, from what source,
// and through which transformations. Fields TBD.
type ContextSemanticProvenance map[string]interface{}

// Describes the semantic/ontological framework needed to correctly interpret the
// payload.
// The CFN routing layer uses this to select appropriate cognitive engines (CEs).
type ContextSemantic struct {
	// OntologyRef corresponds to the JSON schema field "ontology_ref".
	OntologyRef string `json:"ontology_ref" yaml:"ontology_ref" mapstructure:"ontology_ref"`

	// Provenance corresponds to the JSON schema field "provenance".
	Provenance *ContextSemanticProvenance `json:"provenance,omitempty,omitzero" yaml:"provenance,omitempty" mapstructure:"provenance,omitempty"`

	// SchemaID corresponds to the JSON schema field "schema_id".
	SchemaID string `json:"schema_id" yaml:"schema_id" mapstructure:"schema_id"`
}

// UnmarshalJSON implements json.Unmarshaler.
func (j *ContextSemantic) UnmarshalJSON(value []byte) error {
	var raw map[string]interface{}
	if err := json.Unmarshal(value, &raw); err != nil {
		return err
	}
	var contextSemantic_0 ContextSemantic_0
	var errs []error
	if err := contextSemantic_0.UnmarshalJSON(value); err != nil {
		errs = append(errs, err)
	}
	if len(errs) == 1 {
		return fmt.Errorf("all validators failed: %s", errors.Join(errs...))
	}
	type Plain ContextSemantic
	var plain Plain
	if err := json.Unmarshal(value, &plain); err != nil {
		return err
	}
	*j = ContextSemantic(plain)
	return nil
}

type Context struct {
	// Epistemic corresponds to the JSON schema field "epistemic".
	Epistemic *ContextEpistemic `json:"epistemic,omitempty,omitzero" yaml:"epistemic,omitempty" mapstructure:"epistemic,omitempty"`

	// Semantic corresponds to the JSON schema field "semantic".
	Semantic *ContextSemantic `json:"semantic,omitempty,omitzero" yaml:"semantic,omitempty" mapstructure:"semantic,omitempty"`

	// Topic corresponds to the JSON schema field "topic".
	Topic string `json:"topic" yaml:"topic" mapstructure:"topic"`
}

// UnmarshalJSON implements json.Unmarshaler.
func (j *Context) UnmarshalJSON(value []byte) error {
	var raw map[string]interface{}
	if err := json.Unmarshal(value, &raw); err != nil {
		return err
	}
	if _, ok := raw["topic"]; raw != nil && !ok {
		return fmt.Errorf("field topic in Context: required")
	}
	type Plain Context
	var plain Plain
	if err := json.Unmarshal(value, &plain); err != nil {
		return err
	}
	*j = Context(plain)
	return nil
}

type L9HeaderAttributes_0 map[string]interface{}

// UnmarshalJSON implements json.Unmarshaler.
func (j *L9HeaderAttributes_0) UnmarshalJSON(value []byte) error {
	type Plain L9HeaderAttributes_0
	var plain Plain
	if err := json.Unmarshal(value, &plain); err != nil {
		return err
	}
	*j = L9HeaderAttributes_0(plain)
	return nil
}

// A participant in a protocol exchange — can be a human, an AI agent, or a system.
// Multiple actors are listed in L9Header.actors to identify sender(s) and
// receiver(s).
type Actor struct {
	// Attestation corresponds to the JSON schema field "attestation".
	Attestation interface{} `json:"attestation,omitempty,omitzero" yaml:"attestation,omitempty" mapstructure:"attestation,omitempty"`

	// ID corresponds to the JSON schema field "id".
	ID string `json:"id" yaml:"id" mapstructure:"id"`

	// Role corresponds to the JSON schema field "role".
	Role string `json:"role" yaml:"role" mapstructure:"role"`
}

// Data governance and access-control labels applied to the message.
// ## TODO Nandu, Peter please review
type L9HeaderPolicy struct {
	// Propagation corresponds to the JSON schema field "propagation".
	Propagation string `json:"propagation" yaml:"propagation" mapstructure:"propagation"`

	// RetentionPolicy corresponds to the JSON schema field "retention_policy".
	RetentionPolicy string `json:"retention_policy" yaml:"retention_policy" mapstructure:"retention_policy"`

	// Sensitivity corresponds to the JSON schema field "sensitivity".
	Sensitivity string `json:"sensitivity" yaml:"sensitivity" mapstructure:"sensitivity"`
}

// A complete L9 message: header (routing/metadata) + payload (content).
// This is the top-level structure passed between agents and through the CFN.
type L9SchemaJson struct {
	// Header corresponds to the JSON schema field "header".
	Header L9Header `json:"header" yaml:"header" mapstructure:"header"`

	// Payload corresponds to the JSON schema field "payload".
	Payload L9Payload `json:"payload" yaml:"payload" mapstructure:"payload"`
}

// Agent epistemic (belief/knowledge) state at the time the message was sent.
// Currently a placeholder — fields will be added as the model is defined.
type L9HeaderContextEpistemic map[string]interface{}

type L9HeaderContextSemantic_0 = Semantic

type L9HeaderContextSemanticProvenance_0 = Provenance

// Tracks the origin and lineage of a message — who created it, from what source,
// and through which transformations. Fields TBD.
type L9HeaderContextSemanticProvenance map[string]interface{}

// Describes the semantic/ontological framework needed to correctly interpret the
// payload.
// The CFN routing layer uses this to select appropriate cognitive engines (CEs).
type L9HeaderContextSemantic struct {
	// OntologyRef corresponds to the JSON schema field "ontology_ref".
	OntologyRef string `json:"ontology_ref" yaml:"ontology_ref" mapstructure:"ontology_ref"`

	// Provenance corresponds to the JSON schema field "provenance".
	Provenance *L9HeaderContextSemanticProvenance `json:"provenance,omitempty,omitzero" yaml:"provenance,omitempty" mapstructure:"provenance,omitempty"`

	// SchemaID corresponds to the JSON schema field "schema_id".
	SchemaID string `json:"schema_id" yaml:"schema_id" mapstructure:"schema_id"`
}

// UnmarshalJSON implements json.Unmarshaler.
func (j *L9HeaderContextSemantic) UnmarshalJSON(value []byte) error {
	var raw map[string]interface{}
	if err := json.Unmarshal(value, &raw); err != nil {
		return err
	}
	var l9HeaderContextSemantic_0 L9HeaderContextSemantic_0
	var errs []error
	if err := l9HeaderContextSemantic_0.UnmarshalJSON(value); err != nil {
		errs = append(errs, err)
	}
	if len(errs) == 1 {
		return fmt.Errorf("all validators failed: %s", errors.Join(errs...))
	}
	type Plain L9HeaderContextSemantic
	var plain Plain
	if err := json.Unmarshal(value, &plain); err != nil {
		return err
	}
	*j = L9HeaderContextSemantic(plain)
	return nil
}

type L9HeaderContext struct {
	// Epistemic corresponds to the JSON schema field "epistemic".
	Epistemic *L9HeaderContextEpistemic `json:"epistemic,omitempty,omitzero" yaml:"epistemic,omitempty" mapstructure:"epistemic,omitempty"`

	// Semantic corresponds to the JSON schema field "semantic".
	Semantic *L9HeaderContextSemantic `json:"semantic,omitempty,omitzero" yaml:"semantic,omitempty" mapstructure:"semantic,omitempty"`

	// Topic corresponds to the JSON schema field "topic".
	Topic string `json:"topic" yaml:"topic" mapstructure:"topic"`
}

// UnmarshalJSON implements json.Unmarshaler.
func (j *L9HeaderContext) UnmarshalJSON(value []byte) error {
	var raw map[string]interface{}
	if err := json.Unmarshal(value, &raw); err != nil {
		return err
	}
	var l9HeaderContext_0 L9HeaderContext_0
	var errs []error
	if err := l9HeaderContext_0.UnmarshalJSON(value); err != nil {
		errs = append(errs, err)
	}
	if len(errs) == 1 {
		return fmt.Errorf("all validators failed: %s", errors.Join(errs...))
	}
	type Plain L9HeaderContext
	var plain Plain
	if err := json.Unmarshal(value, &plain); err != nil {
		return err
	}
	*j = L9HeaderContext(plain)
	return nil
}

// Represents a message in the protocol.
type Message struct {
	// Episode corresponds to the JSON schema field "episode".
	Episode string `json:"episode" yaml:"episode" mapstructure:"episode"`

	// ID corresponds to the JSON schema field "id".
	ID string `json:"id" yaml:"id" mapstructure:"id"`

	// Parents corresponds to the JSON schema field "parents".
	Parents string `json:"parents" yaml:"parents" mapstructure:"parents"`
}

// UnmarshalJSON implements json.Unmarshaler.
func (j *Message) UnmarshalJSON(value []byte) error {
	var raw map[string]interface{}
	if err := json.Unmarshal(value, &raw); err != nil {
		return err
	}
	if _, ok := raw["episode"]; raw != nil && !ok {
		return fmt.Errorf("field episode in Message: required")
	}
	if _, ok := raw["id"]; raw != nil && !ok {
		return fmt.Errorf("field id in Message: required")
	}
	if _, ok := raw["parents"]; raw != nil && !ok {
		return fmt.Errorf("field parents in Message: required")
	}
	type Plain Message
	var plain Plain
	if err := json.Unmarshal(value, &plain); err != nil {
		return err
	}
	*j = Message(plain)
	return nil
}

type L9HeaderMessage_0 = Message

// Represents a message in the protocol.
type L9HeaderMessage struct {
	// Episode corresponds to the JSON schema field "episode".
	Episode string `json:"episode" yaml:"episode" mapstructure:"episode"`

	// ID corresponds to the JSON schema field "id".
	ID string `json:"id" yaml:"id" mapstructure:"id"`

	// Parents corresponds to the JSON schema field "parents".
	Parents string `json:"parents" yaml:"parents" mapstructure:"parents"`
}

// UnmarshalJSON implements json.Unmarshaler.
func (j *L9HeaderMessage) UnmarshalJSON(value []byte) error {
	var raw map[string]interface{}
	if err := json.Unmarshal(value, &raw); err != nil {
		return err
	}
	var l9HeaderMessage_0 L9HeaderMessage_0
	var errs []error
	if err := l9HeaderMessage_0.UnmarshalJSON(value); err != nil {
		errs = append(errs, err)
	}
	if len(errs) == 1 {
		return fmt.Errorf("all validators failed: %s", errors.Join(errs...))
	}
	type Plain L9HeaderMessage
	var plain Plain
	if err := json.Unmarshal(value, &plain); err != nil {
		return err
	}
	*j = L9HeaderMessage(plain)
	return nil
}

// Data governance and access-control labels applied to the message.
// ## TODO Nandu, Peter please review
type PolicyLabel struct {
	// Propagation corresponds to the JSON schema field "propagation".
	Propagation string `json:"propagation" yaml:"propagation" mapstructure:"propagation"`

	// RetentionPolicy corresponds to the JSON schema field "retention_policy".
	RetentionPolicy string `json:"retention_policy" yaml:"retention_policy" mapstructure:"retention_policy"`

	// Sensitivity corresponds to the JSON schema field "sensitivity".
	Sensitivity string `json:"sensitivity" yaml:"sensitivity" mapstructure:"sensitivity"`
}

// UnmarshalJSON implements json.Unmarshaler.
func (j *PolicyLabel) UnmarshalJSON(value []byte) error {
	var raw map[string]interface{}
	if err := json.Unmarshal(value, &raw); err != nil {
		return err
	}
	if _, ok := raw["propagation"]; raw != nil && !ok {
		return fmt.Errorf("field propagation in PolicyLabel: required")
	}
	if _, ok := raw["retention_policy"]; raw != nil && !ok {
		return fmt.Errorf("field retention_policy in PolicyLabel: required")
	}
	if _, ok := raw["sensitivity"]; raw != nil && !ok {
		return fmt.Errorf("field sensitivity in PolicyLabel: required")
	}
	type Plain PolicyLabel
	var plain Plain
	if err := json.Unmarshal(value, &plain); err != nil {
		return err
	}
	*j = PolicyLabel(plain)
	return nil
}

type L9HeaderPolicy_0 = PolicyLabel

type L9HeaderContext_0 = Context

// UnmarshalJSON implements json.Unmarshaler.
func (j *L9HeaderPolicy) UnmarshalJSON(value []byte) error {
	var raw map[string]interface{}
	if err := json.Unmarshal(value, &raw); err != nil {
		return err
	}
	var l9HeaderPolicy_0 L9HeaderPolicy_0
	var errs []error
	if err := l9HeaderPolicy_0.UnmarshalJSON(value); err != nil {
		errs = append(errs, err)
	}
	if len(errs) == 1 {
		return fmt.Errorf("all validators failed: %s", errors.Join(errs...))
	}
	type Plain L9HeaderPolicy
	var plain Plain
	if err := json.Unmarshal(value, &plain); err != nil {
		return err
	}
	*j = L9HeaderPolicy(plain)
	return nil
}

// Routing and metadata envelope for every L9 message.
// The CFN layer reads the header — especially `kind` and `sub_kind` —
// to decide which Cognitive Engine (CE) should handle the message.
type L9Header struct {
	// Actors corresponds to the JSON schema field "actors".
	Actors Actors `json:"actors" yaml:"actors" mapstructure:"actors"`

	// Attributes corresponds to the JSON schema field "attributes".
	Attributes *L9HeaderAttributes `json:"attributes,omitempty,omitzero" yaml:"attributes,omitempty" mapstructure:"attributes,omitempty"`

	// Context corresponds to the JSON schema field "context".
	Context *L9HeaderContext `json:"context,omitempty,omitzero" yaml:"context,omitempty" mapstructure:"context,omitempty"`

	// Kind corresponds to the JSON schema field "kind".
	Kind string `json:"kind" yaml:"kind" mapstructure:"kind"`

	// Message corresponds to the JSON schema field "message".
	Message *L9HeaderMessage `json:"message,omitempty,omitzero" yaml:"message,omitempty" mapstructure:"message,omitempty"`

	// Policy corresponds to the JSON schema field "policy".
	Policy *L9HeaderPolicy `json:"policy,omitempty,omitzero" yaml:"policy,omitempty" mapstructure:"policy,omitempty"`

	// Protocol corresponds to the JSON schema field "protocol".
	Protocol string `json:"protocol" yaml:"protocol" mapstructure:"protocol"`

	// Subkind corresponds to the JSON schema field "subkind".
	Subkind string `json:"subkind" yaml:"subkind" mapstructure:"subkind"`

	// Subprotocol corresponds to the JSON schema field "subprotocol".
	Subprotocol string `json:"subprotocol" yaml:"subprotocol" mapstructure:"subprotocol"`

	// Version corresponds to the JSON schema field "version".
	Version string `json:"version" yaml:"version" mapstructure:"version"`
}

// UnmarshalJSON implements json.Unmarshaler.
func (j *L9Header) UnmarshalJSON(value []byte) error {
	var raw map[string]interface{}
	if err := json.Unmarshal(value, &raw); err != nil {
		return err
	}
	if _, ok := raw["actors"]; raw != nil && !ok {
		return fmt.Errorf("field actors in L9Header: required")
	}
	if _, ok := raw["kind"]; raw != nil && !ok {
		return fmt.Errorf("field kind in L9Header: required")
	}
	if _, ok := raw["protocol"]; raw != nil && !ok {
		return fmt.Errorf("field protocol in L9Header: required")
	}
	if _, ok := raw["subkind"]; raw != nil && !ok {
		return fmt.Errorf("field subkind in L9Header: required")
	}
	if _, ok := raw["subprotocol"]; raw != nil && !ok {
		return fmt.Errorf("field subprotocol in L9Header: required")
	}
	if _, ok := raw["version"]; raw != nil && !ok {
		return fmt.Errorf("field version in L9Header: required")
	}
	type Plain L9Header
	var plain Plain
	if err := json.Unmarshal(value, &plain); err != nil {
		return err
	}
	*j = L9Header(plain)
	return nil
}

type L9PayloadData map[string]interface{}

// The actual content being carried by an L9 message.
// The `type` field describes the payload format; `data` holds the content.
type L9Payload struct {
	// Data corresponds to the JSON schema field "data".
	Data L9PayloadData `json:"data" yaml:"data" mapstructure:"data"`

	// Type corresponds to the JSON schema field "type".
	Type string `json:"type" yaml:"type" mapstructure:"type"`
}

// UnmarshalJSON implements json.Unmarshaler.
func (j *L9Payload) UnmarshalJSON(value []byte) error {
	var raw map[string]interface{}
	if err := json.Unmarshal(value, &raw); err != nil {
		return err
	}
	if _, ok := raw["data"]; raw != nil && !ok {
		return fmt.Errorf("field data in L9Payload: required")
	}
	if _, ok := raw["type"]; raw != nil && !ok {
		return fmt.Errorf("field type in L9Payload: required")
	}
	type Plain L9Payload
	var plain Plain
	if err := json.Unmarshal(value, &plain); err != nil {
		return err
	}
	*j = L9Payload(plain)
	return nil
}

// Tracks the origin and lineage of a message — who created it, from what source,
// and through which transformations. Fields TBD.
type SemanticProvenance map[string]interface{}

// UnmarshalJSON implements json.Unmarshaler.
func (j *Semantic) UnmarshalJSON(value []byte) error {
	var raw map[string]interface{}
	if err := json.Unmarshal(value, &raw); err != nil {
		return err
	}
	if _, ok := raw["ontology_ref"]; raw != nil && !ok {
		return fmt.Errorf("field ontology_ref in Semantic: required")
	}
	if _, ok := raw["schema_id"]; raw != nil && !ok {
		return fmt.Errorf("field schema_id in Semantic: required")
	}
	type Plain Semantic
	var plain Plain
	if err := json.Unmarshal(value, &plain); err != nil {
		return err
	}
	*j = Semantic(plain)
	return nil
}
